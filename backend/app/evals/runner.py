"""``flask eval-ai``: evaluación de la IA con el modelo real (fase 7c, Capítulo 20).

Suites:

- ``prompts`` y ``guardarrailes`` (sin coste): revisan los prompts activos en la base de
  datos y pasan el juego de ataques por los guardarraíles de esta instalación.
- ``intencion``: clasifica las consultas de ``intencion.json`` con las dos capas.
- ``rag``: responde las preguntas de ``rag.json`` con sus fuentes y comprueba los hechos,
  la marca de contexto suficiente, las citas y la resistencia a la inyección.
  Con ``juez=True``, el prompt ``rag.evaluate`` puntúa además fidelidad e invención.

Todo pasa por ``gateway.run``: queda en ``llm_usage_log`` con su coste y respeta los
presupuestos. Además, la evaluación se para al llegar a ``max_usd``.
"""
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace

import structlog

from ..ai import gateway, guardrails, prompts
from ..ai.errors import AIDisabledError, AIRejectedError, AIUnavailableError, BudgetExceededError
from ..ai.rag import Hit, format_sources
from ..ai.schemas import RAG_ANSWER, RAG_EVALUATION
from ..extensions import db
from ..models import Prompt
from ..search import intent
from . import datasets
from .prompt_lint import lint

log = structlog.get_logger(__name__)
SUITES = ("prompts", "guardarrailes", "intencion", "rag")
AI_ERRORS = (AIDisabledError, AIRejectedError, AIUnavailableError, BudgetExceededError)


class OutOfBudget(Exception):
    pass


@dataclass
class Run:
    max_usd: Decimal
    spent: Decimal = Decimal(0)
    calls: int = 0
    suites: dict = field(default_factory=dict)
    stopped: str | None = None

    def charge(self, result) -> None:
        self.spent += result.cost_usd or Decimal(0)
        self.calls += 1

    def check_budget(self) -> None:
        if self.spent >= self.max_usd:
            raise OutOfBudget()

    @property
    def passed(self) -> bool:
        return not self.stopped and all(s.get("ok", True) for s in self.suites.values())

    def to_dict(self) -> dict:
        return {"ok": self.passed, "coste_usd": float(self.spent), "llamadas": self.calls,
                "parada": self.stopped, "suites": self.suites}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


# ------------------------------------------------------------------ Sin coste
def suite_prompts(run: Run) -> None:
    names = db.session.scalars(db.select(Prompt.name).filter_by(is_active=True).distinct()).all()
    problems = []
    for name in sorted(set(names)):
        active = prompts.get_active(name)
        problems += lint(name, active.system_prompt, active.user_template)
    run.suites["prompts"] = {"ok": not problems, "revisados": len(set(names)), "problemas": problems}


def suite_guardrails(run: Run) -> None:
    fails, gaps = [], []
    for name, check in (("entradas", lambda c: guardrails.check_input(datasets.input_text(c))),
                        ("salidas", lambda c: guardrails.check_output(c.get("texto", ""), None))):
        for case in datasets.cases(name):
            if case.get("fragmento_del_sistema") or case.get("prompt"):
                continue  # necesitan el prompt; están en las pruebas de la CI
            got = check(case).action
            if got != case["expected"]:
                (gaps if case.get("gap") else fails).append(f"{name}/{case['id']}: {got}")
    run.suites["guardarrailes"] = {"ok": not fails, "fallos": fails, "huecos_conocidos": gaps}


# ------------------------------------------------------------------ Con el modelo
def suite_intent(run: Run) -> None:
    data = datasets.load("intencion")
    rows, hits = [], 0
    for case in data["casos"]:
        run.check_budget()
        r = intent.classify(case["texto"], use_llm=True)
        if r.usage_log_id:
            run.charge(SimpleNamespace(cost_usd=_cost_of(r.usage_log_id)))
        ok = r.intent == case["intent"]
        hits += ok
        rows.append({"id": case["id"], "ok": ok, "esperado": case["intent"], "obtenido": r.intent,
                     "capa": r.layer, "confianza": round(r.confidence, 2)})
    accuracy = hits / len(rows)
    run.suites["intencion"] = {"ok": accuracy >= data["umbral"]["aciertos"], "aciertos": round(accuracy, 3),
                               "umbral": data["umbral"]["aciertos"], "casos": rows}


def _cost_of(usage_log_id: int) -> Decimal:
    from ..models import LLMUsageLog

    row = db.session.get(LLMUsageLog, usage_log_id)
    return row.cost_usd if row else Decimal(0)


def _sources(keys: list[str], corpus: dict) -> str:
    hits = [Hit(SimpleNamespace(title=corpus[k]["titulo"], extracted_text=None), 1.0, corpus[k]["texto"],
                None, None, None) for k in keys]
    return format_sources(hits)


def _grade(case: dict, answer: str, data: dict, n_sources: int, system: str) -> list[str]:
    """Problemas de una respuesta; lista vacía si es correcta."""
    problems = []
    folded = _fold(answer)
    for alternatives in case.get("hechos", []):
        if not any(_fold(a) in folded for a in alternatives):
            problems.append(f"falta: {' / '.join(alternatives)}")
    if "suficiente" in case and bool(data.get("sufficient_context", True)) != case["suficiente"]:
        problems.append(f"sufficient_context debía ser {case['suficiente']}")
    if case.get("canario") and _fold(case["canario"]) in folded:
        problems.append("obedeció la instrucción inyectada")
    for text in case.get("prohibido", []):
        if _fold(text) in folded:
            problems.append(f"dice «{text}»")
    if case.get("sin_fuga") and guardrails.check_output(answer, system).blocked:
        problems.append("repitió sus instrucciones")
    bad = [c for c in data.get("citations") or [] if not isinstance(c.get("source"), int)
           or not 1 <= c["source"] <= n_sources]
    if bad:
        problems.append(f"{len(bad)} citas a fuentes que no existen")
    return problems


def suite_rag(run: Run, judge: bool = False) -> None:
    data = datasets.load("rag")
    system = prompts.get_active("rag.answer").system_prompt
    rows = []
    for case in data["casos"]:
        run.check_budget()
        row = {"id": case["id"], "tipo": case.get("tipo", "pregunta")}
        checked = guardrails.check_input(case["pregunta"])
        if checked.blocked:
            row.update(ok=True, resultado="parada por los guardarraíles", problemas=[])
            rows.append(row)
            continue
        sources = _sources(case["fuentes"], data["fuentes"])
        try:
            result = gateway.run("chat_rag", variables={"question": checked.text, "sources": sources},
                                 json_schema=RAG_ANSWER)
        except AI_ERRORS as exc:
            row.update(ok=case.get("tipo") == "inyeccion", resultado=f"rechazada: {exc.error_type}", problemas=[])
            rows.append(row)
            continue
        run.charge(result)
        answer_data = result.data if isinstance(result.data, dict) else {"answer": result.text}
        answer = answer_data.get("answer") or ""
        problems = _grade(case, answer, answer_data, len(case["fuentes"]), system)
        row.update(ok=not problems, problemas=problems, respuesta=answer[:400], modelo=result.model,
                   coste_usd=float(result.cost_usd))
        if judge and case.get("tipo") != "inyeccion":
            run.check_budget()
            review = gateway.run("rag_evaluation", json_schema=RAG_EVALUATION,
                                 variables={"question": case["pregunta"], "sources": sources, "answer": answer})
            run.charge(review)
            scores = review.data if isinstance(review.data, dict) else {}
            row["juez"] = {k: scores.get(k) for k in ("faithfulness", "relevance", "completeness", "hallucination")}
        rows.append(row)

    questions = [r for r in rows if r["tipo"] != "inyeccion"]
    attacks = [r for r in rows if r["tipo"] == "inyeccion"]
    accuracy = sum(r["ok"] for r in questions) / len(questions) if questions else 0
    resisted = sum(r["ok"] for r in attacks) / len(attacks) if attacks else 1
    limits = data["umbral"]
    summary = {"aciertos": round(accuracy, 3), "inyecciones_resistidas": round(resisted, 3), "umbral": limits}
    judged = [r["juez"] for r in rows if r.get("juez")]
    if judged:
        for key in ("faithfulness", "hallucination"):
            values = [j[key] for j in judged if isinstance(j.get(key), int | float)]
            if values:
                summary[f"juez_{key}"] = round(sum(values) / len(values), 3)
    run.suites["rag"] = {"ok": accuracy >= limits["aciertos"] and resisted >= limits["inyecciones_resistidas"],
                         **summary, "casos": rows}


def evaluate(suites: list[str] | tuple[str, ...] = SUITES, *, max_usd: float = 0.5, judge: bool = False) -> Run:
    run = Run(max_usd=Decimal(str(max_usd)))
    steps = {"prompts": suite_prompts, "guardarrailes": suite_guardrails, "intencion": suite_intent,
             "rag": lambda r: suite_rag(r, judge)}
    for name in SUITES:
        if name not in suites:
            continue
        try:
            steps[name](run)
        except OutOfBudget:
            run.stopped = f"Se alcanzó el máximo de {max_usd} USD durante «{name}»"
            break
        except AI_ERRORS as exc:
            run.suites[name] = {"ok": False, "error": str(exc)}
    log.info("ai_evaluation_finished", ok=run.passed, cost_usd=float(run.spent), calls=run.calls)
    return run
