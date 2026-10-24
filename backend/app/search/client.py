"""Cliente HTTP mínimo de Meilisearch (API REST v1).

Solo lo usan el backend y los workers, dentro de ``data_net``. Las escrituras de
Meilisearch son asíncronas: devuelven una tarea y el índice se actualiza unos
milisegundos después. Cuando hace falta esperar (reconstrucción del índice), se
usa ``wait``.
"""
import time
from dataclasses import dataclass

import requests
import structlog
from flask import current_app

from ..errors import DomainError
from .filters import Filter, to_meili

log = structlog.get_logger(__name__)


class SearchUnavailableError(DomainError):
    status_code = 503
    error_type = "search_unavailable"


class MeiliError(Exception):
    def __init__(self, message: str, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass
class MeiliClient:
    base_url: str
    api_key: str
    timeout: float = 5.0

    def _request(self, method: str, path: str, json=None, params=None, timeout: float | None = None):
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            resp = requests.request(method, f"{self.base_url}{path}", json=json, params=params, headers=headers,
                                    timeout=timeout or self.timeout)
        except requests.RequestException as exc:
            raise MeiliError(f"Meilisearch no responde ({type(exc).__name__})") from exc
        if resp.status_code >= 300:
            try:
                body = resp.json()
            except ValueError:
                body = {}
            raise MeiliError(body.get("message") or f"HTTP {resp.status_code}", resp.status_code, body.get("code"))
        return resp.json() if resp.content else {}

    # --- Estado
    def health(self) -> dict:
        return self._request("GET", "/health")

    def version(self) -> dict:
        return self._request("GET", "/version")

    def stats(self) -> dict:
        return self._request("GET", "/stats")

    def index_stats(self, uid: str) -> dict | None:
        try:
            return self._request("GET", f"/indexes/{uid}/stats")
        except MeiliError as exc:
            if exc.code == "index_not_found":
                return None
            raise

    # --- Índices
    def create_index(self, uid: str, primary_key: str = "id") -> dict:
        return self._request("POST", "/indexes", {"uid": uid, "primaryKey": primary_key})

    def delete_index(self, uid: str) -> dict | None:
        try:
            return self._request("DELETE", f"/indexes/{uid}")
        except MeiliError as exc:
            if exc.code == "index_not_found":
                return None
            raise

    def update_settings(self, uid: str, settings: dict) -> dict:
        return self._request("PATCH", f"/indexes/{uid}/settings", settings)

    def swap_indexes(self, pairs: list[tuple[str, str]]) -> dict:
        return self._request("POST", "/swap-indexes", [{"indexes": list(p)} for p in pairs])

    # --- Documentos
    def add_documents(self, uid: str, documents: list[dict]) -> dict:
        return self._request("POST", f"/indexes/{uid}/documents", documents, params={"primaryKey": "id"},
                             timeout=60)

    def delete_documents(self, uid: str, ids: list) -> dict:
        return self._request("POST", f"/indexes/{uid}/documents/delete-batch", list(ids), timeout=60)

    # --- Búsqueda
    def search(self, uid: str, query: dict, filter: Filter | None = None) -> dict:
        body = {**query}
        if filter is not None:
            body["filter"] = to_meili(filter)
        return self._request("POST", f"/indexes/{uid}/search", body)

    def multi_search(self, queries: list[tuple[str, dict, Filter | None]]) -> list[dict]:
        body = {"queries": [{"indexUid": uid, **q, **({"filter": to_meili(f)} if f is not None else {})}
                            for uid, q, f in queries]}
        return self._request("POST", "/multi-search", body)["results"]

    # --- Tareas
    def get_task(self, task_uid: int) -> dict:
        return self._request("GET", f"/tasks/{task_uid}")

    def wait(self, task: dict, timeout: float = 120.0, interval: float = 0.2) -> dict:
        """Espera a que termine una tarea. Lanza MeiliError si falla."""
        task_uid = task.get("taskUid", task.get("uid"))
        deadline = time.monotonic() + timeout
        while True:
            info = self.get_task(task_uid)
            if info.get("status") == "succeeded":
                return info
            if info.get("status") in ("failed", "canceled"):
                error = info.get("error") or {}
                raise MeiliError(error.get("message") or f"Tarea {task_uid} {info.get('status')}",
                                 code=error.get("code"))
            if time.monotonic() > deadline:
                raise MeiliError(f"La tarea {task_uid} no ha terminado a tiempo")
            time.sleep(interval)
            interval = min(interval * 1.5, 2.0)


def get_search_client() -> MeiliClient:
    client = current_app.extensions.get("search_client")
    if client is None:
        client = MeiliClient(current_app.config["MEILI_URL"], current_app.config["MEILI_MASTER_KEY"],
                             timeout=current_app.config.get("MEILI_TIMEOUT", 5.0))
        current_app.extensions["search_client"] = client
    return client
