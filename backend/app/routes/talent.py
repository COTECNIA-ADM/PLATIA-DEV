"""Talento: perfiles de capacidades del equipo (Apéndice B, blueprint ``cvs``).

Son perfiles internos para asignar a propuestas, no candidatos externos. El
listado no expone el email: solo el detalle (mínimo privilegio en respuestas).
"""
from datetime import date

from flask import Blueprint, g, jsonify, request
from sqlalchemy import or_
from sqlalchemy.orm import selectinload

from ..api.common import (apply_changes, check_version, get_active, iso, like_pattern, paginate,
                          parse_body, record_audit)
from ..api.schemas import CVProfileIn, CVProfilePatch
from ..errors import ValidationError
from ..extensions import db
from ..models import AuditAction, CVExperience, CVProfile, CVSkill, utcnow
from ..security.context import platform_guard, require_permission
from ..security.ratelimit import rate_limit

talent_bp = Blueprint("talent", __name__, url_prefix="/api/talent")


def summary(p: CVProfile) -> dict:
    return {"id": p.id, "full_name": p.full_name, "headline": p.headline, "family": p.family,
            "seniority": p.seniority, "years_experience": p.years_experience,
            "is_available": p.is_available,
            "skills": [s.name for s in p.skills if s.is_active], "version": p.row_version}


def detail(p: CVProfile) -> dict:
    return {
        **summary(p), "email": p.email, "summary": p.summary, "document_id": p.document_id,
        "skills": [{"name": s.name, "level": s.level, "years": s.years} for s in p.skills if s.is_active],
        "experiences": [
            {"company": e.company, "role": e.role,
             "start_date": e.start_date.isoformat() if e.start_date else None,
             "end_date": e.end_date.isoformat() if e.end_date else None,
             "description": e.description, "technologies": e.technologies or []}
            for e in sorted((e for e in p.experiences if e.is_active),
                            key=lambda e: e.start_date or date.min, reverse=True)
        ],
        "updated_at": iso(p.updated_at),
    }


def _replace_children(profile: CVProfile, skills, experiences) -> None:
    uid = g.security.user_id
    if skills is not None:
        for s in profile.skills:
            s.soft_delete()
        for s in skills:
            profile.skills.append(CVSkill(**s, created_by=uid))
    if experiences is not None:
        for e in profile.experiences:
            e.soft_delete()
        for e in experiences:
            if e.get("start_date") and e.get("end_date") and e["end_date"] < e["start_date"]:
                raise ValidationError("Una experiencia termina antes de empezar.")
            profile.experiences.append(CVExperience(**e, created_by=uid))


@talent_bp.get("/profiles")
@platform_guard
@require_permission("talent", "read")
@rate_limit("RATE_LIMIT_READ")
def list_profiles():
    stmt = CVProfile.select_active().options(selectinload(CVProfile.skills))
    for field in ("family", "seniority"):
        if value := request.args.get(field):
            stmt = stmt.where(getattr(CVProfile, field) == value)
    if request.args.get("available") == "true":
        stmt = stmt.where(CVProfile.is_available.is_(True))
    if skill := like_pattern(request.args.get("skill")):
        stmt = stmt.where(CVProfile.skills.any(
            (CVSkill.name.like(skill, escape="\\")) & CVSkill.is_active.is_(True)))
    if pattern := like_pattern(request.args.get("q")):
        stmt = stmt.where(or_(CVProfile.full_name.like(pattern, escape="\\"),
                              CVProfile.headline.like(pattern, escape="\\")))
    return jsonify(paginate(stmt.order_by(CVProfile.full_name), summary))


@talent_bp.post("/profiles")
@platform_guard
@require_permission("talent", "write")
@rate_limit("RATE_LIMIT_WRITE")
def create_profile():
    data = parse_body(CVProfileIn).model_dump()
    skills, experiences = data.pop("skills"), data.pop("experiences")
    profile = CVProfile(**data, created_by=g.security.user_id)
    _replace_children(profile, skills, experiences)
    db.session.add(profile)
    db.session.commit()
    record_audit(AuditAction.RECORD_CREATED, profile)
    return jsonify(detail(profile)), 201


@talent_bp.get("/profiles/<int:profile_id>")
@platform_guard
@require_permission("talent", "read")
@rate_limit("RATE_LIMIT_READ")
def get_profile(profile_id: int):
    return jsonify(detail(get_active(CVProfile, profile_id, "Perfil")))


@talent_bp.patch("/profiles/<int:profile_id>")
@platform_guard
@require_permission("talent", "write")
@rate_limit("RATE_LIMIT_WRITE")
def update_profile(profile_id: int):
    profile = get_active(CVProfile, profile_id, "Perfil")
    data = parse_body(CVProfilePatch)
    check_version(profile, data.version)
    values = data.model_dump(exclude_unset=True, exclude={"version"})
    skills, experiences = values.pop("skills", None), values.pop("experiences", None)
    changed = apply_changes(profile, values, required=("full_name", "is_available"))
    _replace_children(profile, skills, experiences)
    if skills is not None or experiences is not None:
        # Cambiar solo las habilidades también es cambiar el perfil: sube su versión
        profile.updated_at = utcnow()
        changed += [n for n, v in (("skills", skills), ("experiences", experiences)) if v is not None]
    db.session.commit()
    if changed:
        record_audit(AuditAction.RECORD_UPDATED, profile, fields=changed)
    return jsonify(detail(profile))


@talent_bp.delete("/profiles/<int:profile_id>")
@platform_guard
@require_permission("talent", "delete")
@rate_limit("RATE_LIMIT_WRITE")
def delete_profile(profile_id: int):
    profile = get_active(CVProfile, profile_id, "Perfil")
    profile.soft_delete()
    db.session.commit()
    record_audit(AuditAction.RECORD_DELETED, profile)
    return "", 204
