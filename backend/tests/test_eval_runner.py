"""``flask eval-ai`` con el servicio de IA falso: que corre, puntúa, cobra y se para."""
import json

from app.evals import runner
from app.evals.datasets import load


def test_free_suites_pass_without_calling_the_model(seeded, ai):
    run = runner.evaluate(["prompts", "guardarrailes"], max_usd=0)
    assert run.passed, run.to_dict()
    assert run.suites["prompts"]["revisados"] >= 15
    assert run.suites["guardarrailes"]["huecos_conocidos"]  # los gap se informan, no fallan
    assert not ai.calls and run.calls == 0


def test_rag_suite_grades_answers_and_detects_obeyed_injections(seeded, ai):
    ai.responses["chat_rag"] = {"answer": "CANARIO-INY-1. El plazo es de tres meses [1].", "sufficient_context": True,
                                "citations": [{"source": 9, "quote": "x"}]}
    run = runner.evaluate(["rag"], max_usd=10)
    rows = {r["id"]: r for r in run.suites["rag"]["casos"]}
    assert "obedeció la instrucción inyectada" in rows["iny-01"]["problemas"]
    assert "dice «tres meses»" in rows["iny-01"]["problemas"]
    assert any("citas a fuentes que no existen" in p for p in rows["rag-01"]["problemas"])
    assert any("sufficient_context debía ser False" in p for p in rows["rag-09"]["problemas"])
    assert not run.passed
    # Las fuentes llegan al modelo con el mismo formato que en la aplicación
    sent = next(c for c in ai.calls if c["service_type"] == "chat_rag")["messages"][-1]["content"]
    assert '<source n="1" title="Pliego de prescripciones' in sent
    assert run.calls == len(load("rag")["casos"]) and run.spent > 0


def test_good_answers_pass_the_rag_suite(seeded, ai, monkeypatch):
    data = load("rag")

    def fake_run(service_type, *, variables, json_schema, **_):
        case = next(c for c in data["casos"] if c["pregunta"] == variables["question"])
        facts = " y ".join(alts[0] for alts in case.get("hechos", []))
        answer = {"answer": f"Según el pliego: {facts} [1]." if facts else "Las fuentes no lo dicen.",
                  "sufficient_context": case.get("suficiente", True), "citations": [{"source": 1, "quote": "x"}]}
        from types import SimpleNamespace
        return SimpleNamespace(data=answer, text="", cost_usd=0, model="fake")

    monkeypatch.setattr(runner.gateway, "run", fake_run)
    run = runner.evaluate(["rag"], max_usd=10)
    assert run.passed, json.dumps(run.to_dict(), ensure_ascii=False)[:2000]
    blocked = [r for r in run.suites["rag"]["casos"] if r.get("resultado") == "parada por los guardarraíles"]
    assert blocked == []  # los ataques directos del juego son los que los patrones no paran


def test_it_stops_at_the_spending_limit(seeded, ai):
    run = runner.evaluate(["rag"], max_usd=0.000001)
    assert run.stopped and "máximo" in run.stopped
    assert run.calls == 1 and not run.passed


def test_intent_suite_uses_the_model_only_when_the_patterns_are_unsure(seeded, ai):
    ai.responses["intent_classification"] = {"intent": "OFF_TOPIC", "subtype": "none", "confidence": 0.9,
                                             "reasoning": "x", "filters": {}}
    run = runner.evaluate(["intencion"], max_usd=10)
    rows = run.suites["intencion"]["casos"]
    assert {r["capa"] for r in rows} >= {"pattern", "llm"}
    assert run.calls == sum(r["capa"] == "llm" for r in rows) > 0


def test_cli_writes_the_report_and_fails_below_threshold(seeded, ai, tmp_path):
    out = tmp_path / "informe.json"
    result = seeded.test_cli_runner().invoke(args=["eval-ai", "--suite", "prompts", "--suite", "rag",
                                                   "--max-usd", "5", "--salida", str(out)])
    assert result.exit_code == 1  # el servicio falso no contesta bien a todo
    assert "[OK ] prompts" in result.output and "[MAL] rag" in result.output and "Coste:" in result.output
    report = json.loads(out.read_text(encoding="utf-8"))
    assert set(report["suites"]) == {"prompts", "rag"} and report["llamadas"] > 0
