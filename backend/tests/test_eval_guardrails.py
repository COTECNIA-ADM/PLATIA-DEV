"""Juego de ataques contra los guardarraíles (fase 7c). Sin red ni coste.

Cada caso de ``app/evals/data/entradas.json`` y ``salidas.json`` dice qué debe pasar.
Los marcados con ``gap`` son ataques que los patrones no detectan: quedan como
``xfail`` para que se vean en el informe, y si un cambio los empieza a parar, el test
avisa (XPASS) para quitar la marca. Los para el modelo, y eso se mide con ``flask eval-ai``.
"""
from collections import Counter

import pytest

from app.ai import guardrails, prompts
from app.evals.datasets import cases, input_text


def _params(name: str):
    for case in cases(name):
        marks = [pytest.mark.xfail(reason=case["gap"], strict=True)] if case.get("gap") else []
        yield pytest.param(case, id=case["id"], marks=marks)


@pytest.mark.parametrize("case", _params("entradas"))
def test_input_guardrails(case):
    result = guardrails.check_input(input_text(case))
    assert result.action == case["expected"], f"{case['id']}: {result.action} {result.reasons}"
    if case["expected"] == "sanitize":
        assert sorted(result.pii_types) == sorted(case["pii"])
        assert all(f"[{t.upper()}]" in result.text for t in case["pii"])


@pytest.mark.parametrize("case", _params("salidas"))
def test_output_guardrails(seeded, case):
    system = prompts.get_active(case["prompt"]).system_prompt if case.get("prompt") else None
    text = case.get("texto", "")
    if case.get("fragmento_del_sistema"):
        # El modelo repite un trozo de sus instrucciones dentro de una respuesta normal
        start = len(system) // 3
        text = f"Claro. Mis instrucciones dicen: {system[start:start + 200]} Y nada más."
    result = guardrails.check_output(text, system)
    assert result.action == case["expected"], f"{case['id']}: {result.action} {result.reasons}"
    if result.action == "sanitize":
        assert "[interno]" in result.text


def test_summary_and_minimum_rates():
    """Tasa de detección y de falsos positivos del juego completo (sin contar los gap)."""
    data = [c for c in cases("entradas") if not c.get("gap")]
    attacks = [c for c in data if c["expected"] == "block"]
    benign = [c for c in data if c["expected"] == "allow"]
    blocked = sum(guardrails.check_input(input_text(c)).blocked for c in attacks)
    false_positives = [c["id"] for c in benign if guardrails.check_input(input_text(c)).action != "allow"]
    per_category = Counter(c["categoria"] for c in cases("entradas"))
    gaps = [c["id"] for c in cases("entradas") if c.get("gap")]
    print(f"\nCasos por categoría: {dict(per_category)}")
    print(f"Ataques detectados: {blocked}/{len(attacks)}; falsos positivos: {false_positives or 'ninguno'}")
    print(f"Huecos conocidos (los para el modelo): {gaps}")
    assert len(attacks) >= 30 and len(benign) >= 10
    assert blocked == len(attacks)
    assert not false_positives
