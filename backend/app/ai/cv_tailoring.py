"""CV a medida para una propuesta (Capítulo 15).

El modelo no inventa nada: recibe los datos reales del perfil y la oportunidad y
solo puede elegir, ordenar y redactar. Después se comprueba: las competencias
tienen que estar en el perfil y las experiencias, en su historial (empresa y
fechas salen de la base de datos, no del modelo). El resultado se adjunta a la
propuesta en DOCX y PDF.
"""
import unicodedata

import structlog

from ..extensions import db
from ..models import CVProfile, Proposal, ProposalAttachment
from ..services import rendering, storage
from . import gateway, guardrails

log = structlog.get_logger(__name__)

CV_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "skills": {"type": "array", "items": {"type": "string"}},
        "experiences": {
            "type": "array",
            "items": {"type": "object",
                      "properties": {"index": {"type": "integer"}, "description": {"type": "string"}},
                      "required": ["index", "description"], "additionalProperties": False},
        },
        "fit_notes": {"type": "string"},
    },
    "required": ["headline", "summary", "skills", "experiences", "fit_notes"],
    "additionalProperties": False,
}


def _norm(text: str) -> str:
    flat = unicodedata.normalize("NFKD", (text or "").lower().strip())
    return "".join(ch for ch in flat if not unicodedata.combining(ch))


def _period(exp) -> str:
    start = exp.start_date.strftime("%Y") if exp.start_date else ""
    end = exp.end_date.strftime("%Y") if exp.end_date else ("actualidad" if exp.start_date else "")
    return f"{start}–{end}" if start else ""


def request(proposal: Proposal, profile: CVProfile, user_id: int | None) -> None:
    from ..queue import PRIORITY_USER, enqueue
    from ..tasks.ai import tailor_cv

    enqueue(tailor_cv, proposal.id, profile.id, user_id, priority=PRIORITY_USER)


def profile_facts(profile: CVProfile) -> tuple[str, list]:
    experiences = sorted((e for e in profile.experiences if e.is_active),
                         key=lambda e: e.start_date.toordinal() if e.start_date else 0, reverse=True)
    lines = [f"Nombre: {profile.full_name}", f"Titular: {profile.headline or '-'}",
             f"Seniority: {profile.seniority or '-'} · Años de experiencia: {profile.years_experience or '-'}",
             f"Resumen: {(profile.summary or '-')[:2000]}", "Competencias:"]
    lines += [f"- {s.name} (nivel {s.level or '-'}, {s.years or '-'} años)" for s in profile.skills if s.is_active]
    lines.append("Experiencias (índice: puesto en empresa, periodo, descripción, tecnologías):")
    for i, e in enumerate(experiences):
        lines.append(f"[{i}] {e.role or '-'} en {e.company}, {_period(e) or '-'}: {(e.description or '')[:800]} "
                     f"({', '.join(e.technologies or [])})")
    return "\n".join(lines), experiences


def opportunity_facts(proposal: Proposal) -> str:
    o = proposal.opportunity
    go = (o.extra_data or {}).get("go_no_go") or {}
    reqs = [r.get("requirement") for r in go.get("requirements") or [] if isinstance(r, dict)][:15]
    return "\n".join([f"Oportunidad: {o.title}", f"Entidad: {o.contracting_entity or '-'}",
                      f"CPV: {', '.join(o.cpv_codes or []) or '-'}",
                      f"Descripción: {(o.description or '-')[:4000]}",
                      "Requisitos detectados: " + ("; ".join(filter(None, reqs)) or "-")])


def tailor(proposal: Proposal, profile: CVProfile, user_id: int | None) -> dict:
    facts, experiences = profile_facts(profile)
    result = gateway.run("cv_tailoring", variables={"opportunity": opportunity_facts(proposal), "profile": facts},
                         user_id=user_id, json_schema=CV_SCHEMA)
    data = result.data or {}
    known_skills = {_norm(s.name): s.name for s in profile.skills if s.is_active}
    skills = list(dict.fromkeys(known_skills[_norm(s)] for s in data.get("skills") or [] if _norm(s) in known_skills))
    chosen = []
    for item in data.get("experiences") or []:
        idx = item.get("index")
        if isinstance(idx, int) and 0 <= idx < len(experiences) and idx not in {c[0] for c in chosen}:
            chosen.append((idx, item.get("description") or ""))
    cv = {
        "name": profile.full_name,
        "headline": (data.get("headline") or profile.headline or "")[:200],
        "summary": data.get("summary") or profile.summary or "",
        "skills": skills[:15] or [s.name for s in profile.skills if s.is_active][:10],
        "experiences": [{"company": experiences[i].company, "role": experiences[i].role,
                         "period": _period(experiences[i]), "description": desc[:1200]} for i, desc in chosen[:8]],
    }
    for field in ("headline", "summary"):
        checked = guardrails.check_output(cv[field])
        cv[field] = "" if checked.blocked else checked.text
    files = {"docx": rendering.cv_docx(cv), "pdf": rendering.cv_pdf(cv)}
    prefix = f"cv-{profile.id}-propuesta-{proposal.id}"
    for old in proposal.attachments:  # se sustituye el CV anterior de esta persona
        if old.kind == "cv" and old.is_active and old.filename.startswith(prefix + "."):
            old.soft_delete()
    ids = []
    for ext, content in files.items():
        stored = storage.save_bytes(content, f"{prefix}.{ext}", "proposals")
        att = ProposalAttachment(kind="cv", filename=f"{prefix}.{ext}", mime_type=stored.mime_type,
                                 storage_path=stored.storage_path, file_size_bytes=stored.size,
                                 file_hash=stored.sha256, created_by=user_id)
        proposal.attachments.append(att)
        db.session.flush()
        ids.append(att.id)
    db.session.commit()
    log.info("cv_tailored", proposal_id=proposal.id, profile_id=profile.id, skills=len(cv["skills"]),
             experiences=len(cv["experiences"]))
    return {"attachment_ids": ids, "fit_notes": (data.get("fit_notes") or "")[:1000],
            "dropped_skills": len(data.get("skills") or []) - len(skills)}
