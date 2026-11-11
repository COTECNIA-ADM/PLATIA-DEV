"""Catálogo del portal Low-Code leído de n8n (ADR-020, fase L1).

PLATIA no guarda todavía el catálogo: lo lee de la API pública de n8n y solo enseña
los flujos con la etiqueta ``N8N_CATALOG_TAG``. Si n8n no responde, el portal sigue
funcionando y dice por qué no hay catálogo; el detalle del fallo va al log.
"""
from dataclasses import dataclass, field

import requests
import structlog
from flask import current_app

log = structlog.get_logger(__name__)

MAX_PAGES = 10  # 10 páginas de 100 flujos: de sobra para un catálogo interno


@dataclass
class Catalog:
    enabled: bool
    reachable: bool
    workflows: list[dict] = field(default_factory=list)
    problem: str | None = None


def _tags(raw: dict) -> list[str]:
    return sorted(t.get("name", "") for t in raw.get("tags") or [] if t.get("name"))


def workflow_dict(raw: dict) -> dict:
    """Solo lo que necesita el portal: nunca nodos, credenciales ni parámetros."""
    return {
        "id": str(raw.get("id", "")),
        "name": raw.get("name") or "Sin nombre",
        "active": bool(raw.get("active")),
        "tags": _tags(raw),
        "updated_at": raw.get("updatedAt"),
    }


def fetch_catalog() -> Catalog:
    cfg = current_app.config
    if not cfg.get("N8N_ENABLED"):
        return Catalog(enabled=False, reachable=False, problem="n8n no está activado en esta instalación.")
    if not cfg.get("N8N_API_KEY"):
        return Catalog(enabled=True, reachable=False, problem="Falta la clave de la API de n8n (N8N_API_KEY).")
    url = f"{cfg['N8N_API_URL']}/workflows"
    params = {"limit": 100, "excludePinnedData": "true"}
    if cfg.get("N8N_CATALOG_TAG"):
        params["tags"] = cfg["N8N_CATALOG_TAG"]
    headers = {"X-N8N-API-KEY": cfg["N8N_API_KEY"], "Accept": "application/json"}
    workflows: list[dict] = []
    try:
        for _ in range(MAX_PAGES):
            resp = requests.get(url, params=params, headers=headers, timeout=cfg["N8N_TIMEOUT_SECONDS"],
                                allow_redirects=False)
            if resp.status_code in (401, 403):
                log.warning("n8n_api_rejected_key", status=resp.status_code)
                return Catalog(enabled=True, reachable=False, problem="n8n rechaza la clave de su API.")
            resp.raise_for_status()
            body = resp.json()
            workflows += [workflow_dict(w) for w in body.get("data") or []]
            cursor = body.get("nextCursor")
            if not cursor:
                break
            params["cursor"] = cursor
    except (requests.RequestException, ValueError) as exc:
        log.warning("n8n_api_unreachable", error=type(exc).__name__)
        return Catalog(enabled=True, reachable=False, problem="No se puede conectar con n8n.")
    workflows.sort(key=lambda w: w["name"].lower())
    return Catalog(enabled=True, reachable=True, workflows=workflows)


def editor_url() -> str | None:
    return current_app.config.get("N8N_PUBLIC_URL") or None
