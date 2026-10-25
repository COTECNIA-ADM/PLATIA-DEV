"""Paquete de documentos de una propuesta aprobada (cola ``documents``, Capítulos 9 y 15).

Tres formatos: DOCX editable, PDF para enviar y una presentación PPTX. Las
diapositivas las resume Haiku (``proposal_deck``) a partir de las secciones; si
la IA no está disponible, se hacen sin IA con el primer párrafo de cada sección.
"""
import structlog

from ..extensions import db
from ..models import Proposal, ProposalAttachment
from ..queue import PlatformTask, celery
from ..services import rendering, storage
from ..services.notifications import notify

log = structlog.get_logger(__name__)
FORMATS = ("docx", "pdf", "pptx")
DECK_SCHEMA = {
    "type": "object",
    "properties": {
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "bullets": {"type": "array", "items": {"type": "string"}},
                               "notes": {"type": "string"}},
                "required": ["title", "bullets", "notes"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["slides"],
    "additionalProperties": False,
}


def render_docx(proposal: Proposal) -> bytes:  # compatibilidad con la fase 4
    return rendering.proposal_docx(proposal)


def deck_slides(proposal: Proposal) -> tuple[list[dict], bool]:
    """Diapositivas con IA (y si falla, sin ella). Devuelve (diapositivas, con_ia)."""
    from ..ai import gateway

    content = "\n\n".join(f"## {title}\n{text[:4000]}" for title, text in rendering.sections(proposal) if text)
    if not content:
        return rendering.default_slides(proposal), False
    try:
        result = gateway.run("proposal_deck", variables={"title": proposal.title, "content": content},
                             user_id=proposal.owner_user_id or proposal.created_by, json_schema=DECK_SCHEMA)
        slides = [s for s in (result.data or {}).get("slides") or [] if s.get("title") and s.get("bullets")]
        if slides:
            return slides, True
    except Exception as exc:  # noqa: BLE001 - la presentación sale igualmente, sin IA
        log.info("proposal_deck_without_ai", proposal_id=proposal.id, error=type(exc).__name__)
    return rendering.default_slides(proposal), False


@celery.task(name="tasks.proposals.generate_package", base=PlatformTask, bind=True, max_retries=3)
def generate_package(self, proposal_id: int) -> dict:
    proposal = db.session.get(Proposal, proposal_id)
    if proposal is None or not proposal.is_active:
        return {"proposal_id": proposal_id, "status": "missing"}
    slides, with_ai = deck_slides(proposal)
    try:
        files = {"docx": rendering.proposal_docx(proposal), "pdf": rendering.proposal_pdf(proposal),
                 "pptx": rendering.proposal_pptx(proposal, slides)}
    except Exception as exc:  # noqa: BLE001
        raise self.retry_later(exc) from exc
    # Solo se conserva el paquete generado más reciente
    for old in proposal.attachments:
        if old.kind == "generated" and old.is_active:
            old.soft_delete()
    ids = []
    for ext in FORMATS:
        filename = f"propuesta-{proposal.id}-v{proposal.version_number}.{ext}"
        stored = storage.save_bytes(files[ext], filename, "proposals")
        attachment = ProposalAttachment(kind="generated", filename=filename, mime_type=stored.mime_type,
                                        storage_path=stored.storage_path, file_size_bytes=stored.size,
                                        file_hash=stored.sha256)
        proposal.attachments.append(attachment)
        db.session.flush()
        ids.append(attachment.id)
    db.session.commit()
    recipient = proposal.owner_user_id or proposal.created_by
    if recipient:
        notify(recipient, "REPORT_READY", "Paquete de propuesta disponible",
               f"Los documentos de «{proposal.title[:200]}» están listos para descargar (Word, PDF y PowerPoint).",
               link=f"/proposals/{proposal.id}", extra_data={"formats": list(FORMATS)})
    log.info("proposal_package_generated", proposal_id=proposal.id, attachments=ids, deck_ai=with_ai)
    return {"proposal_id": proposal.id, "attachment_ids": ids, "formats": list(FORMATS), "deck_ai": with_ai}
