"""Cliente HTTP del servicio de IA (solo lo usa el backend, con X-API-Key)."""
from dataclasses import dataclass

import requests
import structlog
from flask import current_app, g, has_request_context

log = structlog.get_logger(__name__)


class AIServiceError(Exception):
    """Error al llamar al servicio de IA. ``body`` trae los intentos si los hubo."""

    def __init__(self, message: str, status: int | None = None, body: dict | None = None):
        super().__init__(message)
        self.status = status
        self.body = body or {}


@dataclass
class AIServiceClient:
    base_url: str
    api_key: str
    timeout: float = 200.0

    def _request(self, method: str, path: str, json: dict | None = None, timeout: float | None = None) -> dict:
        headers = {"X-API-Key": self.api_key}
        if has_request_context() and g.get("request_id"):
            headers["X-Request-ID"] = g.request_id
        try:
            resp = requests.request(method, f"{self.base_url}{path}", json=json, headers=headers,
                                    timeout=timeout or self.timeout)
        except requests.RequestException as exc:
            log.warning("ai_service_unreachable", path=path, error=type(exc).__name__)
            raise AIServiceError("El servicio de IA no responde.") from exc
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code >= 300:
            raise AIServiceError(str(body.get("detail") or f"HTTP {resp.status_code}"), resp.status_code, body)
        return body

    # --- LLM
    def complete(self, payload: dict) -> dict:
        return self._request("POST", "/v1/complete", payload, timeout=payload.get("timeout_seconds", 180) + 20)

    # --- Embeddings y RAG
    def similarity(self, queries: list[str], candidates: list[str], timeout: float = 10) -> list[list[float]]:
        return self._request("POST", "/v1/similarity", {"queries": queries, "candidates": candidates},
                             timeout=timeout)["scores"]

    def index(self, collection: str, ref_id: int, chunks: list[dict], common: dict) -> dict:
        return self._request("POST", "/v1/rag/index", {"collection": collection, "ref_id": ref_id,
                                                       "chunks": chunks, "common": common}, timeout=600)

    def search(self, payload: dict) -> list[dict]:
        return self._request("POST", "/v1/rag/search", payload, timeout=30)["hits"]

    def delete(self, collection: str, ref_id: int) -> None:
        self._request("POST", "/v1/rag/delete", {"collection": collection, "ref_id": ref_id}, timeout=30)

    def set_payload(self, collection: str, ref_id: int, payload: dict) -> None:
        self._request("POST", "/v1/rag/payload", {"collection": collection, "ref_id": ref_id,
                                                  "payload": payload}, timeout=30)

    def count(self, collection: str, ref_id: int) -> int:
        return self._request("POST", "/v1/rag/count", {"collection": collection, "ref_id": ref_id},
                             timeout=30)["points"]

    def refs(self, collection: str) -> dict[int, int]:
        body = self._request("GET", f"/v1/rag/collections/{collection}/refs", timeout=120)
        return {int(k): v for k, v in body["refs"].items()}

    def collections(self) -> dict:
        return self._request("GET", "/v1/rag/collections", timeout=30)

    def health(self) -> dict:
        return self._request("GET", "/health", timeout=5)


def get_ai_client() -> AIServiceClient:
    client = current_app.extensions.get("ai_client")
    if client is None:
        client = AIServiceClient(current_app.config["AI_SERVICE_URL"], current_app.config["AI_SERVICE_API_KEY"])
        current_app.extensions["ai_client"] = client
    return client
