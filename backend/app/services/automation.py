"""Portal Low-Code con n8n (ADR-020).

Fase L1: el catálogo se lee de la API pública de n8n y solo enseña los flujos con la
etiqueta ``N8N_CATALOG_TAG``. Si n8n no responde, el portal sigue funcionando y dice por
qué no hay catálogo; el detalle del fallo va al log.

Fase L2: una persona lanza un flujo del catálogo. PLATIA guarda la ejecución, la tarea
``tasks.automation.run`` llama al webhook del flujo con la clave del webhook y una firma
HMAC, y n8n devuelve el resultado a ``/api/automation/runs/<id>/callback`` con la clave de
integración. Un flujo se puede lanzar si está activo y empieza por un nodo Webhook POST.
"""
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from datetime import timedelta

import requests
import structlog
from flask import current_app

from ..api.common import iso
from ..errors import BusinessRuleError, ConflictError, NotFoundError, ValidationError
from ..extensions import db
from ..models import AutomationRun, utcnow

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


WEBHOOK_NODE = "n8n-nodes-base.webhook"


def webhook_path(raw: dict) -> str | None:
    """Ruta del primer nodo Webhook que acepta POST, o None si el flujo no tiene."""
    for node in raw.get("nodes") or []:
        if node.get("type") != WEBHOOK_NODE or node.get("disabled"):
            continue
        params = node.get("parameters") or {}
        path = str(params.get("path") or "").strip().strip("/")
        if params.get("httpMethod") == "POST" and path and ".." not in path and "?" not in path:
            return path
    return None


def workflow_dict(raw: dict) -> dict:
    """Solo lo que necesita el portal: nunca nodos, credenciales ni parámetros."""
    active = bool(raw.get("active"))
    return {
        "id": str(raw.get("id", "")),
        "name": raw.get("name") or "Sin nombre",
        "active": active,
        "launchable": active and webhook_path(raw) is not None,
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


# ---------------------------------------------------------------- Ejecuciones (fase L2)
class N8nUnavailable(Exception):
    """n8n no responde o falla por su lado: la tarea lo reintenta."""


def _api_headers() -> dict:
    return {"X-N8N-API-KEY": current_app.config["N8N_API_KEY"], "Accept": "application/json"}


def fetch_workflow(workflow_id: str) -> dict | None:
    """El flujo, solo si está publicado (con la etiqueta del catálogo). None si no existe."""
    cfg = current_app.config
    if not cfg.get("N8N_ENABLED") or not cfg.get("N8N_API_KEY"):
        raise N8nUnavailable("n8n sin activar o sin clave de API")
    if not workflow_id.isalnum():
        return None
    try:
        resp = requests.get(f"{cfg['N8N_API_URL']}/workflows/{workflow_id}", headers=_api_headers(),
                            timeout=cfg["N8N_TIMEOUT_SECONDS"], allow_redirects=False)
    except requests.RequestException as exc:
        raise N8nUnavailable(type(exc).__name__) from exc
    if resp.status_code in (400, 404):
        return None
    if resp.status_code != 200:
        raise N8nUnavailable(f"HTTP {resp.status_code}")
    try:
        raw = resp.json()
    except ValueError as exc:
        raise N8nUnavailable("respuesta no válida") from exc
    tag = cfg.get("N8N_CATALOG_TAG")
    if tag and tag not in _tags(raw):
        return None
    return raw


def _json_size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str).encode())


def launch(workflow_id: str, input_data: dict, user_id: int) -> AutomationRun:
    """Comprueba que el flujo se puede lanzar y guarda la ejecución en cola.

    No hace commit: lo hace la ruta, y después encola la tarea."""
    if _json_size(input_data) > current_app.config["AUTOMATION_MAX_INPUT_BYTES"]:
        raise ValidationError("Los datos de entrada son demasiado grandes.")
    try:
        raw = fetch_workflow(workflow_id)
    except N8nUnavailable as exc:
        log.warning("automation_launch_n8n_unavailable", error=str(exc))
        raise BusinessRuleError("No se puede conectar con n8n ahora mismo. Inténtalo más tarde.") from exc
    if raw is None:
        raise NotFoundError("Ese flujo no está en el catálogo.")
    if not raw.get("active"):
        raise BusinessRuleError("El flujo está desactivado en n8n.")
    if webhook_path(raw) is None:
        raise BusinessRuleError("El flujo no se puede lanzar desde PLATIA: no empieza por un Webhook POST.")
    run = AutomationRun(workflow_id=str(raw["id"]), workflow_name=(raw.get("name") or "Sin nombre")[:255],
                        status="queued", input_data=input_data, created_by=user_id)
    db.session.add(run)
    return run


def sign(body: bytes, secret: str, timestamp: int | None = None) -> str:
    """Firma ``t=<segundos>,v1=<hmac-sha256 de "t.cuerpo">``, la misma forma que el gateway."""
    ts = int(time.time()) if timestamp is None else timestamp
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def callback_url(run: AutomationRun) -> str:
    return f"{current_app.config['N8N_CALLBACK_BASE_URL']}/api/automation/runs/{run.id}/callback"


def _finish(run: AutomationRun, status: str, *, result: dict | None = None, error: str | None = None) -> None:
    run.status = status
    run.result = result
    run.error = (error or None) and error[:500]
    run.finished_at = utcnow()


def dispatch(run: AutomationRun) -> str:
    """Llama al webhook del flujo. Devuelve el estado nuevo; lanza N8nUnavailable si hay
    que reintentar. Es idempotente: una ejecución que ya no está en cola no se repite."""
    cfg = current_app.config
    if run.status != "queued":
        return run.status
    if not cfg.get("N8N_WEBHOOK_SECRET"):
        _finish(run, "failed", error="Falta configurar N8N_WEBHOOK_SECRET.")
        return run.status
    raw = fetch_workflow(run.workflow_id)
    path = webhook_path(raw) if raw and raw.get("active") else None
    if path is None:
        _finish(run, "failed", error="El flujo ya no está publicado o no se puede lanzar.")
        return run.status
    run.attempts += 1
    body = json.dumps({
        "run_id": run.id,
        "workflow_id": run.workflow_id,
        "requested_by": run.created_by,
        "input": run.input_data or {},
        "callback_url": callback_url(run),
    }, ensure_ascii=False).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Platia-Webhook-Key": cfg["N8N_WEBHOOK_SECRET"],
        "X-Platia-Signature": sign(body, cfg["N8N_WEBHOOK_SECRET"]),
        "X-Platia-Run-Id": str(run.id),
    }
    try:
        resp = requests.post(f"{cfg['N8N_WEBHOOK_URL']}/{path}", data=body, headers=headers,
                             timeout=cfg["N8N_TIMEOUT_SECONDS"] * 6, allow_redirects=False)
    except requests.RequestException as exc:
        raise N8nUnavailable(type(exc).__name__) from exc
    if resp.status_code >= 500 or resp.status_code == 429:
        raise N8nUnavailable(f"HTTP {resp.status_code}")
    if resp.status_code >= 300:
        log.warning("automation_webhook_rejected", run_id=run.id, status=resp.status_code)
        _finish(run, "failed", error=f"n8n rechazó la llamada (HTTP {resp.status_code}).")
        return run.status
    run.status = "running"
    run.started_at = utcnow()
    return run.status


def give_up(run: AutomationRun, reason: str) -> None:
    if run.status in AutomationRun.OPEN:
        _finish(run, "failed", error=reason)


def complete(run_id: int, status: str, result: dict | None, error: str | None) -> AutomationRun:
    """Respuesta de n8n. Solo se acepta una vez y para una ejecución abierta."""
    run = db.session.get(AutomationRun, run_id)
    if run is None or not run.is_active:
        raise NotFoundError("Ejecución no encontrada.")
    if run.status not in AutomationRun.OPEN:
        raise ConflictError("La ejecución ya está cerrada.")
    if result is not None and _json_size(result) > current_app.config["AUTOMATION_MAX_RESULT_BYTES"]:
        raise ValidationError("El resultado es demasiado grande.")
    _finish(run, status, result=result if status == "succeeded" else None,
            error=error if status == "failed" else None)
    return run


def expire_stale() -> int:
    """Da por fallidas las ejecuciones sin respuesta de n8n pasado el plazo."""
    limit = utcnow() - timedelta(minutes=current_app.config["AUTOMATION_RUN_TIMEOUT_MINUTES"])
    stale = db.session.scalars(
        AutomationRun.select_active().where(AutomationRun.status.in_(AutomationRun.OPEN),
                                            AutomationRun.created_at < limit).limit(500)
    ).all()
    for run in stale:
        _finish(run, "failed", error="n8n no ha respondido a tiempo.")
    return len(stale)


def run_dict(run: AutomationRun, *, full: bool = False) -> dict:
    data = {
        "id": run.id,
        "workflow_id": run.workflow_id,
        "workflow_name": run.workflow_name,
        "status": run.status,
        "error": run.error,
        "requested_by": run.created_by,
        "created_at": iso(run.created_at),
        "started_at": iso(run.started_at),
        "finished_at": iso(run.finished_at),
    }
    if full:
        data["input"] = run.input_data or {}
        data["result"] = run.result
    return data
