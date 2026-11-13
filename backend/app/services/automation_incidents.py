"""Incidencias y salud de las automatizaciones (portal Low-Code, fase L4, ADR-020).

El flujo de errores común de n8n (``automations/errores/``) avisa a PLATIA cada vez que
falla un flujo que lo tiene puesto en sus ajustes. PLATIA:

- guarda la incidencia (flujo, ejecución de n8n, nodo y mensaje acotado; nunca los datos);
- si la ejecución de n8n venía de PLATIA, la busca con la API de n8n y cierra como fallida
  la ejecución de PLATIA, para que la persona no espere al plazo de seis horas;
- avisa a quien administra las automatizaciones, una vez por flujo hasta que lo lea.

La salud resume, por flujo, las ejecuciones lanzadas desde PLATIA y las incidencias abiertas.
"""
from datetime import timedelta

import requests
import structlog
from flask import current_app
from sqlalchemy import case, func

from ..api.common import iso
from ..errors import ConflictError
from ..extensions import db
from ..models import AutomationIncident, AutomationRun, utcnow
from . import notifications
from .automation import N8nUnavailable, _api_headers, _finish

log = structlog.get_logger(__name__)

MAX_MESSAGE = 500


def incident_dict(i: AutomationIncident) -> dict:
    return {
        "id": i.id, "workflow_id": i.workflow_id, "workflow_name": i.workflow_name,
        "execution_id": i.execution_id, "mode": i.mode, "node": i.node, "message": i.message,
        "run_id": i.run_id, "status": i.status, "created_at": iso(i.created_at),
        "resolved_by": i.resolved_by, "resolved_at": iso(i.resolved_at),
        "resolution_note": i.resolution_note, "version": i.row_version,
    }


def _find_run_id(value, depth: int = 0) -> int | None:
    """Busca, en la salida de los nodos, el cuerpo del Webhook que envió PLATIA
    (``run_id`` junto a ``callback_url``). No guarda nada de lo que lee."""
    if depth > 8:
        return None
    if isinstance(value, dict):
        body = value.get("body")
        if isinstance(body, dict) and isinstance(body.get("run_id"), int) and "callback_url" in body:
            return body["run_id"]
        for v in value.values():
            if (found := _find_run_id(v, depth + 1)) is not None:
                return found
    elif isinstance(value, list):
        for v in value[:20]:
            if (found := _find_run_id(v, depth + 1)) is not None:
                return found
    return None


def run_for_execution(execution_id: str, workflow_id: str) -> int | None:
    """La ejecución de PLATIA detrás de una ejecución de n8n, o None."""
    cfg = current_app.config
    if not cfg.get("N8N_ENABLED") or not cfg.get("N8N_API_KEY") or not execution_id.isdigit():
        return None
    try:
        resp = requests.get(f"{cfg['N8N_API_URL']}/executions/{execution_id}", params={"includeData": "true"},
                            headers=_api_headers(), timeout=cfg["N8N_TIMEOUT_SECONDS"], allow_redirects=False)
        if resp.status_code != 200:
            raise N8nUnavailable(f"HTTP {resp.status_code}")
        raw = resp.json()
    except (requests.RequestException, ValueError, N8nUnavailable) as exc:
        log.warning("automation_incident_execution_unreadable", execution_id=execution_id, error=type(exc).__name__)
        return None
    if str(raw.get("workflowId")) != workflow_id:
        return None
    run_data = (((raw.get("data") or {}).get("resultData") or {}).get("runData")) or {}
    return _find_run_id(run_data)


def record(data: dict) -> tuple[AutomationIncident, bool]:
    """Guarda la incidencia; si n8n la repite (mismo flujo y ejecución), devuelve la que había."""
    if data.get("execution_id"):
        existing = db.session.scalar(db.select(AutomationIncident).where(
            AutomationIncident.workflow_id == data["workflow_id"],
            AutomationIncident.execution_id == data["execution_id"]))
        if existing is not None:
            return existing, False
    if data.get("message"):
        data["message"] = data["message"][:MAX_MESSAGE]
    incident = AutomationIncident(**data)
    db.session.add(incident)
    if data.get("execution_id"):
        run_id = run_for_execution(data["execution_id"], data["workflow_id"])
        run = db.session.get(AutomationRun, run_id) if run_id else None
        if run is not None and run.workflow_id == data["workflow_id"]:
            incident.run_id = run.id
            if run.status in AutomationRun.OPEN:
                where = f" en el paso «{data['node']}»" if data.get("node") else ""
                _finish(run, "failed", error=f"El flujo ha fallado{where}. Quien administra ya está avisado.")
    db.session.flush()
    name = data.get("workflow_name") or data["workflow_id"]
    notifications.notify_many(
        notifications.holders_of("automation", "automations", "manage"), "AUTOMATION_FAILED",
        f"Ha fallado la automatización «{name}»"[:255], data.get("node") and f"Paso: {data['node']}",
        # Un aviso por flujo hasta que se lea: un flujo que falla en bucle no inunda el buzón
        link=f"/automation/monitor?workflow_id={data['workflow_id']}",
        extra_data={"incident_id": incident.id, "workflow_id": data["workflow_id"]},
    )
    log.info("automation_incident_recorded", incident_id=incident.id, workflow_id=incident.workflow_id,
             run_id=incident.run_id)
    return incident, True


def resolve(incident: AutomationIncident, user_id: int, note: str | None) -> None:
    if incident.status != "open":
        raise ConflictError("La incidencia ya está resuelta.")
    incident.status, incident.resolved_by, incident.resolved_at = "resolved", user_id, utcnow()
    incident.resolution_note = note


def health(days: int) -> list[dict]:
    """Por flujo: ejecuciones del periodo por estado, duración media, última ejecución e
    incidencias abiertas. Los flujos sin ejecuciones pero con incidencias también salen."""
    since = utcnow() - timedelta(days=days)
    rows = db.session.execute(
        db.select(
            AutomationRun.workflow_id,
            func.max(AutomationRun.workflow_name),
            func.count(),
            func.sum(case((AutomationRun.status == "succeeded", 1), else_=0)),
            func.sum(case((AutomationRun.status == "failed", 1), else_=0)),
            func.sum(case((AutomationRun.status.in_(AutomationRun.OPEN), 1), else_=0)),
            func.max(AutomationRun.created_at),
        ).where(AutomationRun.is_active.is_(True), AutomationRun.created_at >= since)
        .group_by(AutomationRun.workflow_id)
    ).all()
    durations: dict[str, list[float]] = {}
    for wid, started, finished in db.session.execute(
        db.select(AutomationRun.workflow_id, AutomationRun.started_at, AutomationRun.finished_at).where(
            AutomationRun.is_active.is_(True), AutomationRun.created_at >= since,
            AutomationRun.status == "succeeded", AutomationRun.started_at.is_not(None),
            AutomationRun.finished_at.is_not(None))
    ):
        durations.setdefault(wid, []).append((finished - started).total_seconds())
    open_incidents = dict(db.session.execute(
        db.select(AutomationIncident.workflow_id, func.count()).where(
            AutomationIncident.is_active.is_(True), AutomationIncident.status == "open")
        .group_by(AutomationIncident.workflow_id)
    ).all())
    names = dict(db.session.execute(
        db.select(AutomationIncident.workflow_id, func.max(AutomationIncident.workflow_name))
        .group_by(AutomationIncident.workflow_id)
    ).all())
    items = {}
    for wid, name, total, ok, failed, running, last in rows:
        spent = durations.get(wid) or []
        items[wid] = {
            "workflow_id": wid, "workflow_name": name, "runs": total, "succeeded": int(ok or 0),
            "failed": int(failed or 0), "open": int(running or 0),
            "success_rate": round(100 * int(ok or 0) / total) if total else None,
            "avg_seconds": round(sum(spent) / len(spent), 1) if spent else None,
            "last_run_at": iso(last), "open_incidents": open_incidents.get(wid, 0),
        }
    for wid, count in open_incidents.items():
        items.setdefault(wid, {
            "workflow_id": wid, "workflow_name": names.get(wid), "runs": 0, "succeeded": 0, "failed": 0,
            "open": 0, "success_rate": None, "avg_seconds": None, "last_run_at": None, "open_incidents": count,
        })
    return sorted(items.values(), key=lambda i: (-i["open_incidents"], -i["failed"], i["workflow_name"] or ""))
