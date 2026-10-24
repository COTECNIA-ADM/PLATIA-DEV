"""Documentos: subida, versiones y procesado asíncrono (Apéndice B, blueprint ``documents``).

Flujo (Capítulo 9, paso 1): se sube el fichero, se valida y se guarda con su
SHA-256, y una tarea de la cola ``documents`` extrae el texto. El cliente
consulta el estado con polling (``processing_status``). Después se vectoriza para
la búsqueda semántica (``index_status``) y se enriquece con IA (fase 5).

Control de acceso por objeto: un documento con ``allowed_roles`` solo lo ven su
propietario, esos roles y quien tenga ``documents.manage``. Para el resto no
existe (404), tampoco en las búsquedas ni en las respuestas de la IA.
"""
from flask import Blueprint, g, jsonify, request, send_file
from sqlalchemy import or_

from ..api.common import (apply_changes, check_version, ensure_can_modify, get_active, iso,
                          like_pattern, paginate, parse_body, record_audit)
from ..ai import analysis as analysis_service
from ..ai.access import Viewer
from ..api.schemas import DocumentPatch
from ..errors import BusinessRuleError, ConflictError, NotFoundError, ValidationError
from ..extensions import db
from ..models import App, AppRole, AuditAction, Document, OpportunityDocument
from ..queue import PRIORITY_USER, enqueue
from ..security.audit import audit
from ..security.context import platform_guard, require_ai_module, require_permission
from ..security.ratelimit import rate_limit
from ..services import storage

documents_bp = Blueprint("documents", __name__, url_prefix="/api/documents")


def summary(d: Document) -> dict:
    return {"id": d.id, "title": d.title, "doc_type": d.doc_type,
            "original_filename": d.original_filename, "mime_type": d.mime_type,
            "file_size_bytes": d.file_size_bytes, "version_number": d.version_number,
            "is_current_version": d.is_current_version, "processing_status": d.processing_status,
            "index_status": d.index_status, "is_restricted": d.is_restricted,
            "ai_summary": (d.ai_summary or "")[:300] or None,
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
        "ai_summary": d.ai_summary, "ai_keywords": d.ai_keywords, "ai_entities": d.ai_entities,
        "ai_enriched_at": iso(d.ai_enriched_at), "allowed_roles": d.allowed_roles,
        "vector_count": d.vector_count, "embedding_model": d.embedding_model, "indexed_at": iso(d.indexed_at),
        "opportunities": [{"opportunity_id": link.opportunity_id, "role": link.role} for link in links],
        "versions": [{"id": v.id, "version_number": v.version_number,
                      "is_current_version": v.is_current_version, "created_at": iso(v.created_at)}
                     for v in versions],
    }


def _get_visible(doc_id: int) -> Document:
    """Como get_active, pero un documento restringido que no puedes ver no existe."""
    d = get_active(Document, doc_id, "Documento")
    if not Viewer.current().can_view(d):
        raise NotFoundError("Documento no encontrado.")
    return d


def _validate_roles(roles: list[str]) -> list[str] | None:
    roles = sorted(set(roles or []))
    if not roles:
        return None
    known = set(db.session.scalars(db.select(AppRole.code).join(App, App.id == AppRole.app_id)
                                   .where(App.code == "operations")))
    unknown = [r for r in roles if r not in known]
    if unknown:
        raise ValidationError(f"Roles desconocidos en operaciones: {', '.join(unknown)}.")
    return roles


def _sync_access(document: Document) -> None:
    from ..tasks.ai import sync_document_access

    enqueue(sync_document_access, document.id, priority=PRIORITY_USER)


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
    for field in ("index_status",):
        if value := request.args.get(field):
            stmt = stmt.where(getattr(Document, field) == value)
    if request.args.get("mine") == "true":
        stmt = stmt.where(Document.created_by == g.security.user_id)
    visible = Viewer.current().sql_filter()
    if visible is not None:
        stmt = stmt.where(visible)
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
        if not Viewer.current().can_view(duplicate):
            raise ConflictError("Este fichero ya está subido.")
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
    return jsonify(detail(_get_visible(doc_id)))


@documents_bp.get("/<int:doc_id>/status")
@platform_guard
@require_permission("documents", "read")
@rate_limit("RATE_LIMIT_READ")
def processing_status(doc_id: int):
    d = _get_visible(doc_id)
    return jsonify({"id": d.id, "processing_status": d.processing_status,
                    "processing_error": d.processing_error, "processed_at": iso(d.processed_at)})


@documents_bp.get("/<int:doc_id>/download")
@platform_guard
@require_permission("documents", "read")
@rate_limit("RATE_LIMIT_READ")
def download_document(doc_id: int):
    d = _get_visible(doc_id)
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
    d = _get_visible(doc_id)
    ensure_can_modify("documents", d)
    data = parse_body(DocumentPatch)
    check_version(d, data.version)
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    if "allowed_roles" in changes:
        changes["allowed_roles"] = _validate_roles(changes["allowed_roles"])
    changed = apply_changes(d, changes, required=("title",))
    if "allowed_roles" in changed:
        # Todas las versiones comparten los permisos
        root_id = d.parent_version_id or d.id
        for version in db.session.scalars(db.select(Document).where(
                or_(Document.id == root_id, Document.parent_version_id == root_id))):
            version.allowed_roles = d.allowed_roles
    db.session.commit()
    if changed:
        record_audit(AuditAction.RECORD_UPDATED, d, fields=changed)
    if {"allowed_roles", "title", "doc_type"} & set(changed):
        if "allowed_roles" in changed:
            _sync_access(d)
        else:
            from ..tasks.ai import index_document

            enqueue(index_document, d.id, priority=PRIORITY_USER)
    return jsonify(detail(d))


@documents_bp.post("/<int:doc_id>/versions")
@platform_guard
@require_permission("documents", "upload")
@rate_limit("RATE_LIMIT_UPLOAD")
def upload_version(doc_id: int):
    """Sube una versión nueva. La anterior deja de ser la actual pero se conserva."""
    current = _get_visible(doc_id)
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
        processing_status="pending", created_by=g.security.user_id, allowed_roles=current.allowed_roles,
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
    d = _get_visible(doc_id)
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
    d = _get_visible(doc_id)
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
    _sync_access(d)  # quita sus vectores de Qdrant
    return "", 204


# ------------------------------------------------------------------ IA (fase 5)
@documents_bp.post("/<int:doc_id>/analysis")
@platform_guard
@require_permission("documents", "read")
@require_ai_module("document_analyzer")
@rate_limit("RATE_LIMIT_AI")
def request_analysis(doc_id: int):
    """Análisis GO/NO-GO en segundo plano. Se consulta en GET /api/ai/analyses/<id>."""
    d = _get_visible(doc_id)
    if d.processing_status != "processed" or not d.extracted_text:
        raise BusinessRuleError("El documento todavía no tiene texto extraído.")
    from ..tasks.ai import analyze

    a = analysis_service.create("document", d.id, g.security.user_id)
    enqueue(analyze, a.id, priority=PRIORITY_USER)
    db.session.refresh(a)
    return jsonify(analysis_service.to_dict(a)), 202


@documents_bp.get("/<int:doc_id>/analysis")
@platform_guard
@require_permission("documents", "read")
@rate_limit("RATE_LIMIT_READ")
def latest_analysis(doc_id: int):
    d = _get_visible(doc_id)
    a = analysis_service.latest("document", d.id)
    if a is None:
        raise NotFoundError("Este documento no tiene análisis.")
    return jsonify(analysis_service.to_dict(a))


@documents_bp.post("/<int:doc_id>/reindex")
@platform_guard
@require_permission("documents", "write")
@rate_limit("RATE_LIMIT_WRITE")
def reindex(doc_id: int):
    d = _get_visible(doc_id)
    ensure_can_modify("documents", d)
    if not d.extracted_text:
        raise BusinessRuleError("El documento no tiene texto que indexar.")
    from ..tasks.ai import index_document

    d.set_system_fields(index_status="pending")
    db.session.commit()
    enqueue(index_document, d.id, priority=PRIORITY_USER)
    return jsonify({"id": d.id, "index_status": d.index_status}), 202
