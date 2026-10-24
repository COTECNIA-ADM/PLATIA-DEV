"""Propuestas: cinco tipos y flujo de aprobación (Apéndice B, blueprint ``proposals``).

La lógica de estados vive en services/proposals.py; aquí solo hay HTTP,
permisos y serialización.
"""
from flask import Blueprint, g, jsonify, request, send_file
from sqlalchemy.orm import selectinload

from ..api.common import (apply_changes, check_version, ensure_can_modify, get_active, iso, money,
                          paginate, parse_body, record_audit)
from ..api.schemas import (GenerateProposalIn, ProposalIn, ProposalPatch, ReviewIn, SectionIn, SectionPatch,
                           StatusChange, TailorCVIn)
from ..errors import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError, ValidationError
from ..extensions import db
from ..models import (AuditAction, CVProfile, Opportunity, Proposal, ProposalAttachment, ProposalSection,
                      ProposalTemplate)
from ..queue import PRIORITY_USER, enqueue
from ..security.audit import audit
from ..security.context import platform_guard, require_ai_module, require_permission
from ..security.ratelimit import rate_limit
from ..services import proposals as service
from ..services import storage

proposals_bp = Blueprint("proposals", __name__, url_prefix="/api/proposals")


def summary(p: Proposal) -> dict:
    return {"id": p.id, "title": p.title, "proposal_type": p.proposal_type, "status": p.status,
            "opportunity_id": p.opportunity_id,
            "opportunity_title": p.opportunity.title if p.opportunity else None,
            "version_number": p.version_number, "total_amount_eur": money(p.total_amount_eur),
            "owner_user_id": p.owner_user_id, "sent_at": iso(p.sent_at),
            "generation_status": p.generation_status,
            "updated_at": iso(p.updated_at), "version": p.row_version}


def section_dict(s: ProposalSection) -> dict:
    return {"id": s.id, "key": s.key, "title": s.title, "position": s.position,
            "ai_content": s.ai_content, "edited_content": s.edited_content,
            "final_content": s.final_content, "version": s.row_version}


def attachment_dict(a: ProposalAttachment) -> dict:
    return {"id": a.id, "kind": a.kind, "filename": a.filename, "mime_type": a.mime_type,
            "file_size_bytes": a.file_size_bytes, "created_at": iso(a.created_at)}


def detail(p: Proposal) -> dict:
    round_reviews = [r for r in p.reviews if r.review_round == p.review_round and r.is_active]
    return {
        **summary(p), "template_id": p.template_id, "review_round": p.review_round,
        "generation_error": p.generation_error, "generated_at": iso(p.generated_at),
        "reviewed_by": p.reviewed_by, "reviewed_at": iso(p.reviewed_at),
        "allowed_transitions": [t for t in service.allowed_transitions(p) if t != "approved"],
        "required_reviews": sorted(service.required_reviews(p)),
        "reviews": [{"id": r.id, "kind": r.kind, "decision": r.decision, "comment": r.comment,
                     "reviewer_user_id": r.reviewer_user_id, "created_at": iso(r.created_at)}
                    for r in round_reviews],
        "sections": [section_dict(s) for s in p.sections if s.is_active],
        "attachments": [attachment_dict(a) for a in p.attachments if a.is_active],
        "created_at": iso(p.created_at),
    }


def _get(proposal_id: int) -> Proposal:
    return get_active(Proposal, proposal_id, "Propuesta")


@proposals_bp.get("")
@platform_guard
@require_permission("proposals", "read")
@rate_limit("RATE_LIMIT_READ")
def list_proposals():
    stmt = Proposal.select_active().options(selectinload(Proposal.opportunity))
    if status := request.args.get("status"):
        stmt = stmt.where(Proposal.status.in_(status.split(",")))
    if ptype := request.args.get("proposal_type"):
        stmt = stmt.where(Proposal.proposal_type == ptype)
    if opp := request.args.get("opportunity_id"):
        if not opp.isdigit():
            raise ValidationError("opportunity_id debe ser un número.")
        stmt = stmt.where(Proposal.opportunity_id == int(opp))
    if request.args.get("mine") == "true":
        stmt = stmt.where(Proposal.owner_user_id == g.security.user_id)
    if request.args.get("to_review") == "true":
        stmt = stmt.where(Proposal.status == "in_review")
    return jsonify(paginate(stmt.order_by(Proposal.updated_at.desc(), Proposal.id.desc()), summary))


@proposals_bp.post("")
@platform_guard
@require_permission("proposals", "write")
@rate_limit("RATE_LIMIT_WRITE")
def create_proposal():
    data = parse_body(ProposalIn)
    opp = get_active(Opportunity, data.opportunity_id, "Oportunidad")
    template = get_active(ProposalTemplate, data.template_id, "Plantilla") if data.template_id is not None else None
    proposal = service.create(opp, proposal_type=data.proposal_type, template=template, title=data.title,
                              total_amount_eur=data.total_amount_eur, user_id=g.security.user_id)
    record_audit(AuditAction.RECORD_CREATED, proposal, opportunity_id=opp.id)
    return jsonify(detail(proposal)), 201


@proposals_bp.get("/<int:proposal_id>")
@platform_guard
@require_permission("proposals", "read")
@rate_limit("RATE_LIMIT_READ")
def get_proposal(proposal_id: int):
    return jsonify(detail(_get(proposal_id)))


@proposals_bp.patch("/<int:proposal_id>")
@platform_guard
@require_permission("proposals", "write")
@rate_limit("RATE_LIMIT_WRITE")
def update_proposal(proposal_id: int):
    proposal = _get(proposal_id)
    ensure_can_modify("proposals", proposal)
    data = parse_body(ProposalPatch)
    check_version(proposal, data.version)
    values = data.model_dump(exclude_unset=True, exclude={"version"})
    if "owner_user_id" in values and values["owner_user_id"] != proposal.owner_user_id and \
            not g.security.can("proposals", "manage"):
        raise ForbiddenError("Solo un gestor puede reasignar propuestas.")
    if set(values) - {"owner_user_id"}:
        service.ensure_editable(proposal)
    changed = apply_changes(proposal, values, required=("title",))
    db.session.commit()
    if changed:
        record_audit(AuditAction.RECORD_UPDATED, proposal, fields=changed)
    return jsonify(detail(proposal))


@proposals_bp.delete("/<int:proposal_id>")
@platform_guard
@require_permission("proposals", "delete")
@rate_limit("RATE_LIMIT_WRITE")
def delete_proposal(proposal_id: int):
    proposal = _get(proposal_id)
    ensure_can_modify("proposals", proposal)
    if proposal.status not in ("draft", "archived"):
        raise BusinessRuleError("Solo se pueden borrar propuestas en borrador o archivadas.")
    proposal.soft_delete()
    db.session.commit()
    record_audit(AuditAction.RECORD_DELETED, proposal)
    return "", 204


@proposals_bp.post("/<int:proposal_id>/status")
@platform_guard
@require_permission("proposals", "write")
@rate_limit("RATE_LIMIT_WRITE")
def change_status(proposal_id: int):
    proposal = _get(proposal_id)
    ensure_can_modify("proposals", proposal)
    data = parse_body(StatusChange)
    check_version(proposal, data.version)
    result = service.change_status(proposal, data.status, g.security.can("proposals", "send"),
                                   data.comment, g.security.user_id)
    db.session.commit()
    audit(AuditAction.PROPOSAL_STATUS_CHANGED, user_id=g.security.user_id, resource_type="proposals",
          resource_id=proposal.id, details={**result, "comment": data.comment,
                                            "proposal_type": proposal.proposal_type})
    return jsonify(detail(proposal))


@proposals_bp.post("/<int:proposal_id>/reviews")
@platform_guard
@require_permission("proposals", "approve")
@rate_limit("RATE_LIMIT_WRITE")
def add_review(proposal_id: int):
    proposal = _get(proposal_id)
    data = parse_body(ReviewIn)
    result = service.add_review(proposal, g.security.user_id, g.security.is_admin, data.kind,
                                data.decision, data.comment)
    db.session.commit()
    audit(AuditAction.PROPOSAL_REVIEWED, user_id=g.security.user_id, resource_type="proposals",
          resource_id=proposal.id, details={"kind": data.kind, "decision": data.decision,
                                            "status": result["status"], "round": proposal.review_round})
    if result["status"] == "approved":
        _enqueue_package(proposal)
    return jsonify({**detail(proposal), "pending_reviews": result["pending"]}), 201


def _enqueue_package(proposal: Proposal) -> None:
    from ..tasks.proposals import generate_package

    enqueue(generate_package, proposal.id, priority=PRIORITY_USER)


@proposals_bp.post("/<int:proposal_id>/package")
@platform_guard
@require_permission("proposals", "write")
@rate_limit("RATE_LIMIT_UPLOAD")
def regenerate_package(proposal_id: int):
    proposal = _get(proposal_id)
    if proposal.status not in ("approved", "sent", "won", "lost"):
        raise BusinessRuleError("El paquete se genera cuando la propuesta está aprobada.")
    _enqueue_package(proposal)
    return jsonify({"id": proposal.id, "status": "queued"}), 202


# ------------------------------------------------------------------ Secciones
def _section(proposal: Proposal, section_id: int) -> ProposalSection:
    section = db.session.get(ProposalSection, section_id)
    if section is None or not section.is_active or section.proposal_id != proposal.id:
        raise NotFoundError("Sección no encontrada.")
    return section


@proposals_bp.post("/<int:proposal_id>/sections")
@platform_guard
@require_permission("proposals", "write")
@rate_limit("RATE_LIMIT_WRITE")
def add_section(proposal_id: int):
    proposal = _get(proposal_id)
    ensure_can_modify("proposals", proposal)
    service.ensure_editable(proposal)
    data = parse_body(SectionIn)
    if any(s.key == data.key and s.is_active for s in proposal.sections):
        raise ConflictError("Ya hay una sección con esa clave.")
    position = data.position if data.position is not None else len(proposal.sections)
    section = ProposalSection(key=data.key, title=data.title, position=position,
                              edited_content=data.edited_content, created_by=g.security.user_id)
    proposal.sections.append(section)
    db.session.commit()
    return jsonify(section_dict(section)), 201


@proposals_bp.patch("/<int:proposal_id>/sections/<int:section_id>")
@platform_guard
@require_permission("proposals", "write")
@rate_limit("RATE_LIMIT_WRITE")
def update_section(proposal_id: int, section_id: int):
    proposal = _get(proposal_id)
    ensure_can_modify("proposals", proposal)
    service.ensure_editable(proposal)
    section = _section(proposal, section_id)
    data = parse_body(SectionPatch)
    check_version(section, data.version)
    apply_changes(section, data.model_dump(exclude_unset=True, exclude={"version"}),
                  required=("title", "position"))
    db.session.commit()
    return jsonify(section_dict(section))


@proposals_bp.delete("/<int:proposal_id>/sections/<int:section_id>")
@platform_guard
@require_permission("proposals", "write")
@rate_limit("RATE_LIMIT_WRITE")
def delete_section(proposal_id: int, section_id: int):
    proposal = _get(proposal_id)
    ensure_can_modify("proposals", proposal)
    service.ensure_editable(proposal)
    _section(proposal, section_id).soft_delete()
    db.session.commit()
    return "", 204


# ------------------------------------------------------------------ Adjuntos
@proposals_bp.post("/<int:proposal_id>/attachments")
@platform_guard
@require_permission("proposals", "write")
@rate_limit("RATE_LIMIT_UPLOAD")
def add_attachment(proposal_id: int):
    """multipart/form-data: file y kind (competitive_analysis | other)."""
    proposal = _get(proposal_id)
    ensure_can_modify("proposals", proposal)
    kind = request.form.get("kind", "other")
    if kind not in ("competitive_analysis", "other"):
        raise ValidationError("kind debe ser competitive_analysis u other.")
    stored = storage.save_upload(request.files.get("file"), subdir="proposals")
    attachment = ProposalAttachment(kind=kind, filename=stored.original_filename,
                                    mime_type=stored.mime_type, storage_path=stored.storage_path,
                                    file_size_bytes=stored.size, file_hash=stored.sha256,
                                    created_by=g.security.user_id)
    proposal.attachments.append(attachment)
    db.session.commit()
    record_audit(AuditAction.RECORD_CREATED, attachment, proposal_id=proposal.id, kind=kind)
    return jsonify(attachment_dict(attachment)), 201


def _attachment(proposal: Proposal, attachment_id: int) -> ProposalAttachment:
    attachment = db.session.get(ProposalAttachment, attachment_id)
    if attachment is None or not attachment.is_active or attachment.proposal_id != proposal.id:
        raise NotFoundError("Adjunto no encontrado.")
    return attachment


@proposals_bp.get("/<int:proposal_id>/attachments/<int:attachment_id>")
@platform_guard
@require_permission("proposals", "read")
@rate_limit("RATE_LIMIT_READ")
def download_attachment(proposal_id: int, attachment_id: int):
    attachment = _attachment(_get(proposal_id), attachment_id)
    path = storage.absolute_path(attachment.storage_path)
    if not path.is_file():
        raise NotFoundError("El fichero no está disponible.")
    audit(AuditAction.DOCUMENT_DOWNLOADED, user_id=g.security.user_id,
          resource_type="proposal_attachments", resource_id=attachment.id)
    return send_file(path, mimetype=attachment.mime_type or "application/octet-stream",
                     as_attachment=True, download_name=attachment.filename)


@proposals_bp.delete("/<int:proposal_id>/attachments/<int:attachment_id>")
@platform_guard
@require_permission("proposals", "write")
@rate_limit("RATE_LIMIT_WRITE")
def delete_attachment(proposal_id: int, attachment_id: int):
    proposal = _get(proposal_id)
    ensure_can_modify("proposals", proposal)
    service.ensure_editable(proposal)
    _attachment(proposal, attachment_id).soft_delete()
    db.session.commit()
    return "", 204


# ------------------------------------------------------------------ IA (fase 5)
@proposals_bp.post("/<int:proposal_id>/generate")
@platform_guard
@require_permission("proposals", "write")
@require_ai_module("proposal_generator")
@rate_limit("RATE_LIMIT_AI")
def generate(proposal_id: int):
    """Redacta con IA las secciones (por defecto, las que nadie ha editado a mano).

    Va en segundo plano: el avance se ve en ``generation_status`` y en cada sección."""
    proposal = _get(proposal_id)
    ensure_can_modify("proposals", proposal)
    data = parse_body(GenerateProposalIn)
    targets = service.start_generation(proposal, g.security.user_id, data.sections, data.instructions)
    return jsonify({"id": proposal.id, "generation_status": proposal.generation_status,
                    "sections": [s.key for s in targets]}), 202


@proposals_bp.post("/<int:proposal_id>/cv")
@platform_guard
@require_permission("proposals", "write")
@require_ai_module("proposal_generator")
@rate_limit("RATE_LIMIT_AI")
def tailor_cv(proposal_id: int):
    """CV a medida de un perfil para esta propuesta (DOCX y PDF, adjuntos ``kind=cv``).

    Va en segundo plano y avisa con una notificación al terminar."""
    from ..ai import cv_tailoring

    proposal = _get(proposal_id)
    ensure_can_modify("proposals", proposal)
    if not g.security.can("talent", "read"):
        raise ForbiddenError("Necesitas acceso a los perfiles de talento.")
    data = parse_body(TailorCVIn)
    profile = get_active(CVProfile, data.profile_id, "Perfil")
    cv_tailoring.request(proposal, profile, g.security.user_id)
    return jsonify({"id": proposal.id, "profile_id": profile.id, "status": "queued"}), 202
