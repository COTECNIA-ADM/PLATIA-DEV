"""Servicio de IA falso para los tests: mismas respuestas que el real, sin red ni coste.

- ``complete`` devuelve JSON válido para el esquema de cada tipo de tarea y un
  intento con tokens, como el servicio real.
- La "búsqueda vectorial" puntúa por palabras en común y aplica los mismos
  filtros que Qdrant (vigencia, ids, tipos y control de acceso).
"""
import math
import re

from app.ai.client import AIServiceError

_WORD = re.compile(r"\w+", re.UNICODE)

RESPONSES = {
    "document_enrichment": {
        "summary": "Pliego de un servicio de soporte con requisitos de seguridad.",
        "keywords": ["soporte", "ENS", "seguridad"], "doc_type": "pliego",
        "entities": {"organizations": ["Ayuntamiento de Ejemplo"], "amounts": ["120.000 EUR"],
                     "dates": ["12 meses"], "requirements": ["ENS nivel medio"]},
        "language": "es",
    },
    "document_analysis": {
        "verdict": "CONDITIONAL", "confidence": 0.7, "summary": "Encaja si se acredita el ENS.",
        "scores": {"strategic_fit": 8, "technical_capability": 7, "economic_viability": 6, "risk": 4,
                   "competition": 5},
        "requirements": [{"requirement": "ENS nivel medio", "kind": "mandatory", "meets": "partial",
                          "evidence": "Certificación en curso"}],
        "risks": [{"description": "Plazo ajustado", "severity": "medium", "mitigation": "Equipo reforzado"}],
        "conditions": ["Acreditar el ENS antes de la presentación"], "next_steps": ["Pedir aclaraciones"],
        "missing_information": [],
    },
    "chat_rag": {"answer": "El plazo es de doce meses [1].", "sufficient_context": True,
                 "citations": [{"source": 1, "quote": "doce meses"}]},
    "rag_query_rewrite": {"queries": ["plazo de ejecución del contrato"]},
    "rag_evaluation": {"faithfulness": 0.9, "relevance": 1, "completeness": 0.8, "hallucination": 0.1,
                       "issues": []},
    "proposal_generation": {"content": "Texto propuesto para la sección.", "assumptions": [], "sources": [1]},
}


def _vector(text: str) -> dict[str, float]:
    words = {}
    for w in _WORD.findall(text.lower()):
        if len(w) > 2:
            words[w] = words.get(w, 0) + 1
    return words


def _cosine(a: dict, b: dict) -> float:
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na, nb = math.sqrt(sum(v * v for v in a.values())), math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


class FakeAIClient:
    def __init__(self):
        self.calls: list[dict] = []
        self.responses = {k: dict(v) for k, v in RESPONSES.items()}
        self.down = False  # True: el servicio no responde
        self.points: dict[tuple[str, int], list[dict]] = {}
        self.input_tokens = 1000
        self.output_tokens = 200

    def _check(self):
        if self.down:
            raise AIServiceError("El servicio de IA no responde.")

    # --- LLM
    def complete(self, payload: dict) -> dict:
        self.calls.append(payload)
        self._check()
        target = payload["targets"][0]
        data = self.responses.get(payload["service_type"], {"answer": "ok"})
        attempt = {"provider": target["provider"], "model": target["model"], "success": True,
                   "input_tokens": self.input_tokens, "output_tokens": self.output_tokens, "latency_ms": 40,
                   "stop_reason": "end_turn"}
        return {"text": str(data), "data": data, "provider": target["provider"], "model": target["model"],
                "attempts": [attempt], "is_fallback": False, "stop_reason": "end_turn"}

    # --- Embeddings
    def similarity(self, queries, candidates, timeout=10):
        self._check()
        return [[_cosine(_vector(q), _vector(c)) for c in candidates] for q in queries]

    def index(self, collection, ref_id, chunks, common):
        self._check()
        self.points[(collection, ref_id)] = [
            {**common, **(c.get("metadata") or {}), "text": c["text"], "chunk_index": i} for i, c in enumerate(chunks)]
        return {"points": len(chunks), "model": "fake-embeddings", "dims": 3}

    def delete(self, collection, ref_id):
        self._check()
        self.points.pop((collection, ref_id), None)

    def set_payload(self, collection, ref_id, payload):
        self._check()
        for p in self.points.get((collection, ref_id), []):
            p.update(payload)

    def count(self, collection, ref_id):
        return len(self.points.get((collection, ref_id), []))

    def refs(self, collection):
        return {ref: len(pts) for (col, ref), pts in self.points.items() if col == collection}

    def collections(self):
        return {"collections": [{"collection": c, "points": sum(len(p) for (col, _), p in self.points.items()
                                                                 if col == c)} for c in ("documents", "opportunities")]}

    def health(self):
        return {"status": "ok"}

    def search(self, payload):
        self._check()
        query = _vector(payload["query"])
        access = payload.get("access") or {}
        hits = []
        for (collection, ref_id), points in self.points.items():
            if collection not in payload["collections"]:
                continue
            if payload.get("ref_ids") and ref_id not in payload["ref_ids"]:
                continue
            for p in points:
                if payload.get("only_current", True) and not p.get("is_current", True):
                    continue
                if payload.get("doc_types") and p.get("doc_type") not in payload["doc_types"]:
                    continue
                if access and not access.get("bypass"):
                    roles_ok = set(p.get("allowed_roles", ["*"])) & {"*", *access.get("roles", [])}
                    if not roles_ok and p.get("owner_user_id") != access.get("user_id"):
                        continue
                score = _cosine(query, _vector(p["text"]))
                if payload.get("score_threshold") is not None and score < payload["score_threshold"]:
                    continue
                meta = {k: v for k, v in p.items() if k != "text"}
                hits.append({"collection": collection, "score": round(score, 4), "ref_id": ref_id,
                             "text": p["text"], "payload": meta})
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:payload.get("limit", 6)]
