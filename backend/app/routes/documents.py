"""Documentos: subida, versiones y procesado asíncrono (Apéndice B, blueprint ``documents``).

Flujo (Capítulo 9, paso 1): se sube el fichero, se valida y se guarda con su
SHA-256, y una tarea de la cola ``documents`` extrae el texto. El cliente
consulta el estado con polling (``processing_status``). El análisis con IA llega
en la fase 5.
"""
from flask import Blueprint, g, jsonify, request, send_file
from sqlalchemy import or_

from ..api.common import (apply_changes, check_version, ensure_can_modify, get_active, iso,
                          like_pattern, paginate, parse_body, record_audit)
from ..api.schemas import DocumentPatch
from ..errors import BusinessRuleError, ConflictError, NotFoundError, ValidationError
from ..extensions import db
from ..models import AuditAction, Document, OpportunityDocument
from ..queue import PRIORITY_USER, enqueue
from ..security.audit import audit
from ..security.context import platform_guard, require_permission
from ..security.ratelimit import rate_limit
from ..services import storage

documents_bp = Blueprint("documents", __name__, url_prefix="/api/documents")


def summary(d: Document) -> dict:
    return {"id": d.id, "title": d.title, "doc_type": d.doc_type,
            "original_filename": d.original_filename, "mime_type": d.mime_type,
            "file_size_bytes": d.file_size_bytes, "version_number": d.version_number,
            "is_current_version": d.is_current_version, "processing_status": d.processing_status,
            "created_by": d.created_by, "created_at": iso(d.created_at), "version": d.row_version}


def detail(d: Document) -> dict:
    links = db.session.scalars(db.select(OpportunityDocument).filter_by(document_id=d.id, is_active=True))
    root_id = d.parent_version_id or d.id
    versions = db.session.scalars(
        db.select(Document).where(or_(Document.id == root_id, Document.parent_version_id == root_id),
                                  Document.is_active.is_(True))
        .order_by(Document.version_number)
    )
    return {
        **summary(d), "file_hash": d.file_hash, "processing_error": d.processing_error,
        "processed_at": iso(d.processed_at),
        "text_preview": (d.extracted_text or "")[:2000] or None,
        "text_length": len(d.extracted_text or ""),
        "ai_summary": d.ai_summary, "ai_keywords": d.ai_keywords,
        "opportunities": [{"opportunity_id": link.opportunity_id, "role": link.role} for link in links],
        "versions": [{"id": v.id, "version_number": v.version_number,
                      "is_current_version": v.is_current_version, "created_at": iso(v.created_at)}
                     for v in versions],
    }


def _enqueue_processing(document: Document) -> None:
    from ..tasks.documents import process_upload

    document.celery_task_id = enqueue(process_upload, document.id, priority=PRIORITY_USER)
    db.session.commit()


def _duplicate_of(file_hash: str) -> Document | None:
    return db.session.scalar(db.select(Document).filter_by(file_hash=file_hash, is_active=True,
                                                           is_current_version=True))


@documents_bp.get("")
@platform_guard
@require_permission("documents", "read")
@rate_limit("RATE_LIMIT_READ")
def list_documents():
    stmt = Document.select_active().order_by(Document.created_at.desc(), Document.id.desc())
    if request.args.get("all_versions") != "true":
        stmt = stmt.where(Document.is_current_version.is_(True))
    if pattern := like_pattern(request.args.get("q")):
        stmt = stmt.where(or_(Document.title.like(pattern, escape="\\"),
                              Document.original_filename.like(pattern, escape="\\")))
    for field in ("doc_type", "processing_status"):
        if value := request.args.get(field):
            stmt = stmt.where(getattr(Document, field) == value)
    if request.args.get("mine") == "true":
        stmt = stmt.where(Document.created_by == g.security.user_id)
    return jsonify(paginate(stmt, summary))


@documents_bp.post("")
@platform_guard
@require_permission("documents", "upload")
@rate_limit("RATE_LIMIT_UPLOAD")
def upload_document():
    """multipart/form-data: file, title (opcional), doc_type (opcional)."""
    stored = storage.save_upload(request.files.get("file"))
    duplicate = _duplicate_of(stored.sha256)
    if duplicate is not None:
        storage.delete_file(stored.storage_path)
        raise ConflictError("Este fichero ya está subido.", existing_document_id=duplicate.id)
    title = (request.form.get("title") or stored.original_filename)[:500]
    document = Document(
        title=title, doc_type=(request.form.get("doc_type") or None),
        original_filename=stored.original_filename, mime_type=stored.mime_type,
        storage_path=stored.storage_path, file_hash=stored.sha256, file_size_bytes=stored.size,
        processing_status="pending", created_by=g.security.user_id,
    )
    db.session.add(document)
    db.session.commit()
    audit(AuditAction.DOCUMENT_UPLOADED, user_id=g.security.user_id, resource_type="documents",
          resource_id=document.id, details={"size": stored.size, "sha256": stored.sha256})
    _enqueue_processing(document)
    return jsonify(detail(document)), 201


@documents_bp.get("/<int:doc_id>")
@platform_guard
@require_permission("documents", "read")
@rate_limit("RATE_LIMIT_READ")
def get_document(doc_id: int):
    return jsonify(detail(get_active(Document, doc_id, "Documento")))


@documents_bp.get("/<int:doc_id>/status")
@platform_guard
@require_permission("documents", "read")
@rate_limit("RATE_LIMIT_READ")
def processing_status(doc_id: int):
    d = get_active(Document, doc_id, "Documento")
    return jsonify({"id": d.id, "processing_status": d.processing_status,
                    "processing_error": d.processing_error, "processed_at": iso(d.processed_at)})


@documents_bp.get("/<int:doc_id>/download")
@platform_guard
@require_permission("documents", "read")
@rate_limit("RATE_LIMIT_READ")
def download_document(doc_id: int):
    d = get_active(Document, doc_id, "Documento")
    path = storage.absolute_path(d.storage_path or "")
    if not path.is_file():
        raise NotFoundError("El fichero no está disponible.")
    audit(AuditAction.DOCUMENT_DOWNLOADED, user_id=g.security.user_id, resource_type="documents",
          resource_id=d.id)
    return send_file(path, mimetype=d.mime_type or "application/octet-stream", as_attachment=True,
                     download_name=d.original_filename or f"documento-{d.id}")


@documents_bp.patch("/<int:doc_id>")
@platform_guard
@require_permission("documents", "write")
@rate_limit("RATE_LIMIT_WRITE")
def update_document(doc_id: int):
    d = get_active(Document, doc_id, "Documento")
    ensure_can_modify("documents", d)
    data = parse_body(DocumentPatch)
    check_version(d, data.version)
    changed = apply_changes(d, data.model_dump(exclude_unset=True, exclude={"version"}),
                            required=("title",))
    db.session.commit()
    if changed:
        record_audit(AuditAction.RECORD_UPDATED, d, fields=changed)
    return jsonify(detail(d))


@documents_bp.post("/<int:doc_id>/versions")
@platform_guard
@require_permission("documents", "upload")
@rate_limit("RATE_LIMIT_UPLOAD")
def upload_version(doc_id: int):
    """Sube una versión nueva. La anterior deja de ser la actual pero se conserva."""
    current = get_active(Document, doc_id, "Documento")
    ensure_can_modify("documents", current)
    if not current.is_current_version:
        raise BusinessRuleError("Solo se puede versionar la versión actual del documento.")
    stored = storage.save_upload(request.files.get("file"))
    if stored.sha256 == current.file_hash:
        storage.delete_file(stored.storage_path)
        raise ConflictError("El fichero es idéntico a la versión actual.")
    root_id = current.parent_version_id or current.id
    current.is_current_version = False
    new = Document(
        title=request.form.get("title") or current.title, doc_type=current.doc_type,
        original_filename=stored.original_filename, mime_type=stored.mime_type,
        storage_path=stored.storage_path, file_hash=stored.sha256, file_size_bytes=stored.size,
        parent_version_id=root_id, version_number=current.version_number + 1,
        processing_status="pending", created_by=g.security.user_id,
    )
    db.session.add(new)
    db.session.flush()
    # Los vínculos con oportunidades pasan a la versión nueva
    for link in db.session.scalars(db.select(OpportunityDocument).filter_by(document_id=current.id,
                                                                             is_active=True)):
        link.document_id = new.id
    db.session.commit()
    audit(AuditAction.DOCUMENT_UPLOADED, user_id=g.security.user_id, resource_type="documents",
          resource_id=new.id, details={"version_of": root_id, "version_number": new.version_number})
    _enqueue_processing(new)
    return jsonify(detail(new)), 201


@documents_bp.post("/<int:doc_id>/reprocess")
@platform_guard
@require_permission("documents", "write")
@rate_limit("RATE_LIMIT_UPLOAD")
def reprocess(doc_id: int):
    d = get_active(Document, doc_id, "Documento")
    ensure_can_modify("documents", d)
    if d.processing_status == "processing":
        raise ConflictError("El documento se está procesando ahora mismo.")
    d.processing_status = "pending"
    d.processing_error = None
    db.session.commit()
    _enqueue_processing(d)
    return jsonify({"id": d.id, "processing_status": d.processing_status}), 202


@documents_bp.delete("/<int:doc_id>")
@platform_guard
@require_permission("documents", "delete")
@rate_limit("RATE_LIMIT_WRITE")
def delete_document(doc_id: int):
    d = get_active(Document, doc_id, "Documento")
    ensure_can_modify("documents", d)
    if not d.is_current_version:
        raise ValidationError("Borra el documento desde su versión actual.")
    root_id = d.parent_version_id or d.id
    # Borrado lógico de todas las versiones y sus vínculos; el fichero se conserva
    # hasta la limpieza programada (permite deshacer)
    for version in db.session.scalars(db.select(Document).where(
            or_(Document.id == root_id, Document.parent_version_id == root_id))):
        version.soft_delete()
        for link in db.session.scalars(db.select(OpportunityDocument).filter_by(document_id=version.id)):
            link.soft_delete()
    db.session.commit()
    record_audit(AuditAction.RECORD_DELETED, d)
    return "", 204
