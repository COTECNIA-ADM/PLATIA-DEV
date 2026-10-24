"""Oportunidades: embudo de 12 estados en 5 fases (Apéndice B, blueprint ``opportunities``)."""
import csv
import io
from datetime import datetime

from flask import Blueprint, Response, g, jsonify, request, stream_with_context
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from ..api.common import (apply_changes, check_version, ensure_can_modify, get_active, iso,
                          like_pattern, money, paginate, parse_body, record_audit, to_utc_naive)
from ..api.schemas import LinkDocument, OpportunityIn, OpportunityPatch, StatusChange
from ..errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from ..extensions import db
from ..models import (AuditAction, Client, Document, Opportunity, OpportunityDocument, ServiceLine)
from ..security.audit import audit
from ..ai import analysis as analysis_service
from ..ai import similar as similar_service
from ..ai.access import Viewer
from ..errors import BusinessRuleError
from ..queue import PRIORITY_SCHEDULED, PRIORITY_USER, enqueue
from ..security.context import platform_guard, require_ai_module, require_permission
from ..security.ratelimit import rate_limit
from ..services import opportunities as service

opportunities_bp = Blueprint("opportunities", __name__, url_prefix="/api/opportunities")

PHASES = {phase: [s for s, p in Opportunity.STATUS_PHASE.items() if p == phase]
          for phase in ("F1", "F2", "F3", "F4", "F5")}
SORTS = {
    "deadline": Opportunity.deadline.asc(),
    "-deadline": Opportunity.deadline.desc(),
    "-created": Opportunity.created_at.desc(),
    "-score": Opportunity.relevance_score.desc(),
    "-value": Opportunity.estimated_value_eur.desc(),
}


def _maybe_index(opp: Opportunity) -> None:
    """Las oportunidades con relevancia alta se vectorizan para buscar parecidas."""
    if similar_service.should_index(opp):
        from ..tasks.ai import index_opportunity

        enqueue(index_opportunity, opp.id, priority=PRIORITY_SCHEDULED)


def summary(o: Opportunity) -> dict:
    return {
        "id": o.id, "code": o.code, "title": o.title, "status": o.status, "phase": o.funnel_phase,
        "client_id": o.client_id, "client_name": o.client.name if o.client else None,
        "source": o.source, "service_line": o.service_line,
        "estimated_value_eur": money(o.estimated_value_eur), "probability": o.probability,
        "deadline": iso(o.deadline), "owner_user_id": o.owner_user_id,
        "relevance_score": float(o.relevance_score) if o.relevance_score is not None else None,
        "version": o.row_version, "updated_at": iso(o.updated_at),
    }


def detail(o: Opportunity) -> dict:
    viewer = Viewer.current()
    docs = [
        {"document_id": link.document_id, "role": link.role, "title": link.document.title,
         "processing_status": link.document.processing_status}
        for link in o.documents if link.is_active and link.document.is_active and viewer.can_view(link.document)
    ]
    proposals = [
        {"id": p.id, "title": p.title, "proposal_type": p.proposal_type, "status": p.status,
         "version_number": p.version_number}
        for p in o.proposals if p.is_active
    ]
    return {
        **summary(o), "description": o.description, "sector": o.sector,
        "contracting_entity": o.contracting_entity, "cpv_codes": o.cpv_codes or [],
        "external_id": o.external_id, "published_at": iso(o.published_at),
        "link": (o.extra_data or {}).get("link"),
        "score_breakdown": (o.extra_data or {}).get("score_breakdown"),
        "ai_summary": o.ai_summary, "go_no_go": (o.extra_data or {}).get("go_no_go"),
        "allowed_transitions": service.allowed_transitions(o.status),
        "documents": docs, "proposals": proposals, "created_at": iso(o.created_at),
    }


def _validate_refs(values: dict) -> None:
    if values.get("client_id") is not None:
        get_active(Client, values["client_id"], "Cliente")
    if "deadline" in values:
        values["deadline"] = to_utc_naive(values["deadline"])
    if values.get("service_line"):
        exists = db.session.scalar(db.select(ServiceLine.id).filter_by(code=values["service_line"],
                                                                       is_active=True))
        if not exists:
            raise ValidationError("La línea de servicio no existe.")


def _filtered_query():
    stmt = Opportunity.select_active()
    args = request.args
    if status := args.get("status"):
        stmt = stmt.where(Opportunity.status.in_(status.split(",")))
    if phase := args.get("phase"):
        if phase not in PHASES:
            raise ValidationError("Fase no válida (F1-F5).")
        stmt = stmt.where(Opportunity.status.in_(PHASES[phase]))
    if owner := args.get("owner"):
        stmt = stmt.where(Opportunity.owner_user_id == (g.security.user_id if owner == "me" else
                                                        _int_arg("owner")))
    if args.get("client_id"):
        stmt = stmt.where(Opportunity.client_id == _int_arg("client_id"))
    if line := args.get("service_line"):
        stmt = stmt.where(Opportunity.service_line == line)
    if args.get("min_score"):
        stmt = stmt.where(Opportunity.relevance_score >= _float_arg("min_score"))
    for arg, op in (("deadline_from", "__ge__"), ("deadline_to", "__le__")):
        if args.get(arg):
            try:
                value = to_utc_naive(datetime.fromisoformat(args[arg].replace("Z", "+00:00")))
            except ValueError as exc:
                raise ValidationError(f"{arg} debe ser una fecha ISO.") from exc
            stmt = stmt.where(getattr(Opportunity.deadline, op)(value))
    if pattern := like_pattern(args.get("q")):
        stmt = stmt.where(or_(Opportunity.title.like(pattern, escape="\\"),
                              Opportunity.code.like(pattern, escape="\\"),
                              Opportunity.contracting_entity.like(pattern, escape="\\")))
    sort = args.get("sort", "-created")
    if sort not in SORTS:
        raise ValidationError(f"Orden no válido. Opciones: {', '.join(SORTS)}.")
    # selectinload evita una consulta por fila para el nombre del cliente (N+1)
    return stmt.options(selectinload(Opportunity.client)).order_by(SORTS[sort], Opportunity.id.desc())


def _int_arg(name: str) -> int:
    try:
        return int(request.args[name])
    except ValueError as exc:
        raise ValidationError(f"{name} debe ser un número.") from exc


def _float_arg(name: str) -> float:
    try:
        return float(request.args[name])
    except ValueError as exc:
        raise ValidationError(f"{name} debe ser un número.") from exc


@opportunities_bp.get("")
@platform_guard
@require_permission("opportunities", "read")
@rate_limit("RATE_LIMIT_READ")
def list_opportunities():
    return jsonify(paginate(_filtered_query(), summary))


@opportunities_bp.post("")
@platform_guard
@require_permission("opportunities", "write")
@rate_limit("RATE_LIMIT_WRITE")
def create_opportunity():
    values = parse_body(OpportunityIn).model_dump()
    _validate_refs(values)
    if values.get("owner_user_id") not in (None, g.security.user_id) and \
            not g.security.can("opportunities", "manage"):
        raise ForbiddenError("Solo un gestor puede asignar oportunidades a otra persona.")
    values["owner_user_id"] = values.get("owner_user_id") or g.security.user_id
    opp = Opportunity(**values, created_by=g.security.user_id)
    try:
        # Sin autoflush: el INSERT lleva ya la puntuación (un solo INSERT, versión 1)
        with db.session.no_autoflush:
            db.session.add(opp)
            service.score_opportunity(opp)
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ConflictError("Ya existe una oportunidad con ese código.") from exc
    record_audit(AuditAction.RECORD_CREATED, opp)
    _maybe_index(opp)
    return jsonify(detail(opp)), 201


@opportunities_bp.get("/<int:opp_id>")
@platform_guard
@require_permission("opportunities", "read")
@rate_limit("RATE_LIMIT_READ")
def get_opportunity(opp_id: int):
    return jsonify(detail(get_active(Opportunity, opp_id, "Oportunidad")))


@opportunities_bp.patch("/<int:opp_id>")
@platform_guard
@require_permission("opportunities", "write")
@rate_limit("RATE_LIMIT_WRITE")
def update_opportunity(opp_id: int):
    opp = get_active(Opportunity, opp_id, "Oportunidad")
    ensure_can_modify("opportunities", opp)
    data = parse_body(OpportunityPatch)
    check_version(opp, data.version)
    values = data.model_dump(exclude_unset=True, exclude={"version"})
    if "owner_user_id" in values and values["owner_user_id"] != opp.owner_user_id and \
            not g.security.can("opportunities", "manage"):
        raise ForbiddenError("Solo un gestor puede reasignar oportunidades.")
    _validate_refs(values)
    changed = apply_changes(opp, values, required=("title",))
    try:
        with db.session.no_autoflush:
            if {"title", "description", "cpv_codes"} & set(changed):
                service.score_opportunity(opp)
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ConflictError("Ya existe una oportunidad con ese código.") from exc
    if changed:
        record_audit(AuditAction.RECORD_UPDATED, opp, fields=changed)
        _maybe_index(opp)
    return jsonify(detail(opp))


@opportunities_bp.delete("/<int:opp_id>")
@platform_guard
@require_permission("opportunities", "delete")
@rate_limit("RATE_LIMIT_WRITE")
def delete_opportunity(opp_id: int):
    opp = get_active(Opportunity, opp_id, "Oportunidad")
    ensure_can_modify("opportunities", opp)
    if any(p.is_active and p.status in ("in_review", "approved", "sent") for p in opp.proposals):
        raise ConflictError("La oportunidad tiene propuestas en curso.")
    opp.soft_delete()
    db.session.commit()
    record_audit(AuditAction.RECORD_DELETED, opp)
    return "", 204


@opportunities_bp.post("/<int:opp_id>/status")
@platform_guard
@require_permission("opportunities", "write")
@rate_limit("RATE_LIMIT_WRITE")
def change_status(opp_id: int):
    opp = get_active(Opportunity, opp_id, "Oportunidad")
    ensure_can_modify("opportunities", opp)
    data = parse_body(StatusChange)
    check_version(opp, data.version)
    previous = service.change_status(opp, data.status, data.comment)
    db.session.commit()
    audit(AuditAction.OPPORTUNITY_STATUS_CHANGED, user_id=g.security.user_id,
          resource_type="opportunities", resource_id=opp.id,
          details={"from": previous, "to": opp.status, "comment": data.comment})
    return jsonify(detail(opp))


@opportunities_bp.post("/<int:opp_id>/score")
@platform_guard
@require_permission("opportunities", "write")
@rate_limit("RATE_LIMIT_WRITE")
def rescore(opp_id: int):
    opp = get_active(Opportunity, opp_id, "Oportunidad")
    result = service.score_opportunity(opp)
    if result is None:
        raise ValidationError("No hay líneas de servicio en el portfolio para puntuar.")
    db.session.commit()
    _maybe_index(opp)
    return jsonify(result)


# ------------------------------------------------------------------ IA (fase 5)
@opportunities_bp.post("/<int:opp_id>/analysis")
@platform_guard
@require_permission("opportunities", "write")
@require_ai_module("document_analyzer")
@rate_limit("RATE_LIMIT_AI")
def request_analysis(opp_id: int):
    """Análisis GO/NO-GO de la oportunidad y sus documentos vinculados, en segundo plano."""
    opp = get_active(Opportunity, opp_id, "Oportunidad")
    if not (opp.description or "").strip() and not any(link.is_active for link in opp.documents):
        raise BusinessRuleError("Añade una descripción o vincula el pliego antes de analizar.")
    from ..tasks.ai import analyze

    a = analysis_service.create("opportunity", opp.id, g.security.user_id)
    enqueue(analyze, a.id, priority=PRIORITY_USER)
    db.session.refresh(a)
    return jsonify(analysis_service.to_dict(a)), 202


@opportunities_bp.get("/<int:opp_id>/analysis")
@platform_guard
@require_permission("opportunities", "read")
@rate_limit("RATE_LIMIT_READ")
def latest_analysis(opp_id: int):
    opp = get_active(Opportunity, opp_id, "Oportunidad")
    a = analysis_service.latest("opportunity", opp.id)
    if a is None:
        raise NotFoundError("Esta oportunidad no tiene análisis.")
    return jsonify(analysis_service.to_dict(a))


@opportunities_bp.get("/<int:opp_id>/similar")
@platform_guard
@require_permission("opportunities", "read")
@rate_limit("RATE_LIMIT_READ")
def similar_opportunities(opp_id: int):
    opp = get_active(Opportunity, opp_id, "Oportunidad")
    only_open = request.args.get("only_open") == "true"
    return jsonify(items=similar_service.similar(opp, limit=5, only_open=only_open))


# ------------------------------------------------------------------ Documentos vinculados
@opportunities_bp.post("/<int:opp_id>/documents")
@platform_guard
@require_permission("opportunities", "write")
@rate_limit("RATE_LIMIT_WRITE")
def link_document(opp_id: int):
    opp = get_active(Opportunity, opp_id, "Oportunidad")
    ensure_can_modify("opportunities", opp)
    data = parse_body(LinkDocument)
    document = get_active(Document, data.document_id, "Documento")
    link = db.session.scalar(db.select(OpportunityDocument).filter_by(opportunity_id=opp.id,
                                                                      document_id=document.id))
    if link is not None and link.is_active:
        raise ConflictError("El documento ya está vinculado a la oportunidad.")
    if link is None:
        link = OpportunityDocument(opportunity_id=opp.id, document_id=document.id,
                                   created_by=g.security.user_id)
        db.session.add(link)
    link.restore()
    link.role = data.role
    db.session.commit()
    record_audit(AuditAction.RECORD_CREATED, link, opportunity_id=opp.id, document_id=document.id)
    db.session.refresh(opp)
    return jsonify(detail(opp)), 201


@opportunities_bp.delete("/<int:opp_id>/documents/<int:document_id>")
@platform_guard
@require_permission("opportunities", "write")
@rate_limit("RATE_LIMIT_WRITE")
def unlink_document(opp_id: int, document_id: int):
    opp = get_active(Opportunity, opp_id, "Oportunidad")
    ensure_can_modify("opportunities", opp)
    link = db.session.scalar(db.select(OpportunityDocument).filter_by(
        opportunity_id=opp.id, document_id=document_id, is_active=True))
    if link is None:
        raise NotFoundError("El documento no está vinculado a la oportunidad.")
    link.soft_delete()
    db.session.commit()
    record_audit(AuditAction.RECORD_DELETED, link, opportunity_id=opp.id, document_id=document_id)
    return "", 204


# ------------------------------------------------------------------ Exportación
EXPORT_FIELDS = ["id", "code", "title", "status", "phase", "client_name", "source", "service_line",
                 "estimated_value_eur", "probability", "deadline", "relevance_score", "updated_at"]


def _csv_safe(value) -> str:
    """Evita la inyección de fórmulas al abrir el CSV en Excel (=, +, -, @)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@opportunities_bp.get("/export")
@platform_guard
@require_permission("opportunities", "export")
@rate_limit("RATE_LIMIT_EXPORT")
def export_csv():
    """CSV en streaming: no carga todas las filas en memoria (Capítulo 7)."""
    stmt = _filtered_query()
    audit(AuditAction.DATA_EXPORTED, user_id=g.security.user_id, resource_type="opportunities",
          details={"filters": dict(request.args)})

    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        buffer.write("﻿")  # BOM para que Excel detecte UTF-8
        writer.writerow(EXPORT_FIELDS)
        for opp in db.session.scalars(stmt.execution_options(yield_per=500)):
            row = summary(opp)
            writer.writerow([_csv_safe(row[f]) for f in EXPORT_FIELDS])
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
        yield buffer.getvalue()

    return Response(stream_with_context(generate()), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=oportunidades.csv"})
