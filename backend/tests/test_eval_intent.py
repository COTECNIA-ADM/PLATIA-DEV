"""Juego de consultas del clasificador de intención (fase 7c). Sin red ni coste.

Mide la capa 1 (patrones de la base de datos) sobre ``app/evals/data/intencion.json``.
Las consultas marcadas ``capa1`` tienen que resolverse sin modelo; el resto se mide con
el modelo rápido en ``flask eval-ai --suite intencion``.
"""
from collections import Counter

import pytest

from app.evals.datasets import cases
from app.search import intent

MIN_LAYER1_ACCURACY = 0.6  # sobre todo el juego, contando el plan B sin modelo


@pytest.mark.parametrize("case", [c for c in cases("intencion") if c.get("capa1")], ids=lambda c: c["id"])
def test_layer1_resolves_the_common_queries(seeded, ai, case):
    r = intent.classify(case["texto"], use_llm=False)
    assert r.layer == "pattern", f"{case['id']}: no la resuelven los patrones ({r.confidence})"
    assert r.intent == case["intent"]
    if case.get("subtype"):
        assert r.subtype == case["subtype"]
    assert not ai.calls


def test_layer1_accuracy_over_the_whole_set(seeded, ai):
    hits, layers, misses = 0, Counter(), []
    for case in cases("intencion"):
        r = intent.classify(case["texto"], use_llm=False)
        layers[r.layer] += 1
        if r.intent == case["intent"]:
            hits += 1
        else:
            misses.append(f"{case['id']}: {r.intent} ({r.layer}) en vez de {case['intent']}")
    accuracy = hits / len(cases("intencion"))
    print(f"\nCapa 1 sin modelo: {hits}/{len(cases('intencion'))} ({accuracy:.0%}); por capa: {dict(layers)}")
    print("Fallos (los resuelve el modelo):\n  " + "\n  ".join(misses))
    assert accuracy >= MIN_LAYER1_ACCURACY
    assert not ai.calls
