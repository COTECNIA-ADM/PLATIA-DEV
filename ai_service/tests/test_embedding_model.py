"""Prueba con el modelo de embeddings real. Descarga ~220 MB: solo se ejecuta con
RUN_MODEL_TESTS=1 (lo hace la CI)."""
import os

import pytest

from app.embeddings import LocalEmbedder

pytestmark = pytest.mark.skipif(os.environ.get("RUN_MODEL_TESTS") != "1",
                                reason="Necesita descargar el modelo (RUN_MODEL_TESTS=1)")


def test_local_model_captures_meaning(tmp_path):
    emb = LocalEmbedder("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", str(tmp_path))
    query, related, unrelated = emb.embed(
        ["sanciones por retraso en la entrega", "penalizaciones por demora en los plazos",
         "suministro de material de oficina"])
    def cos(a, b):
        return sum(x * y for x, y in zip(a, b))
    assert emb.dims == 384 and emb.status == "ready"
    assert cos(query, related) > cos(query, unrelated) + 0.1
