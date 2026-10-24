"""Procesado de documentos (cola ``documents``)."""
from datetime import timedelta

import structlog

from ..extensions import db
from ..models import Document, utcnow
from ..queue import PRIORITY_MAINTENANCE, PlatformTask, TaskAlreadyRunning, celery, enqueue, task_lock
from ..services import storage
from ..services.extraction import UnsupportedFormat, extract_text

log = structlog.get_logger(__name__)


@celery.task(name="tasks.documents.process_upload", base=PlatformTask, bind=True, max_retries=3)
def process_upload(self, document_id: int) -> dict:
    """Extrae el texto. Idempotente: si ya está procesado o lo procesa otro worker, no hace nada."""
    try:
        with task_lock(f"document:{document_id}", expire=900):
            document = db.session.get(Document, document_id)
            if document is None or not document.is_active:
                return {"document_id": document_id, "status": "missing"}
            if document.processing_status == "processed":
                return {"document_id": document_id, "status": "processed", "skipped": True}
            document.processing_status = "processing"
            db.session.commit()
            try:
                text = extract_text(storage.absolute_path(document.storage_path))
                document.extracted_text = text or None
                document.processing_error = None if text else "No se ha encontrado texto (¿PDF escaneado?)."
            except UnsupportedFormat:
                document.extracted_text = None
                document.processing_error = "Formato sin extracción de texto; se guarda el fichero."
            except FileNotFoundError:
                document.processing_status = "failed"
                document.processing_error = "El fichero no está en el almacenamiento."
                db.session.commit()
                return {"document_id": document_id, "status": "failed"}
            except Exception as exc:  # noqa: BLE001 - fichero corrupto: fallo definitivo, sin reintento
                log.warning("document_extraction_failed", document_id=document_id, error=str(exc))
                document.processing_status = "failed"
                document.processing_error = "No se ha podido leer el fichero (¿está dañado o cifrado?)."
                db.session.commit()
                return {"document_id": document_id, "status": "failed"}
            document.processing_status = "processed"
            document.processed_at = utcnow()
            if document.extracted_text:
                document.index_status = "pending"
            db.session.commit()
            log.info("document_processed", document_id=document_id, chars=len(text or "") if
                     document.extracted_text else 0)
        if document.extracted_text:
            # Fase 5: vectorizar para RAG y enriquecer con IA (cola ai)
            from .ai import after_document_processed

            after_document_processed(document_id)
        return {"document_id": document_id, "status": "processed"}
    except TaskAlreadyRunning:
        return {"document_id": document_id, "status": "already_running"}
    except Exception as exc:
        db.session.rollback()
        # Fallo de infraestructura (BD, Redis): se reintenta con backoff
        doc = db.session.get(Document, document_id)
        if doc is not None and doc.processing_status == "processing":
            doc.processing_status = "pending"
            db.session.commit()
        raise self.retry_later(exc)


@celery.task(name="tasks.documents.recover_pending", base=PlatformTask)
def recover_pending(older_than_minutes: int = 10) -> dict:
    """Reencola documentos que se quedaron en pending o processing (broker caído,
    worker reiniciado). Se apoya en que process_upload es idempotente."""
    cutoff = utcnow() - timedelta(minutes=older_than_minutes)
    stuck = db.session.scalars(
        db.select(Document.id).where(Document.is_active.is_(True),
                                     Document.processing_status.in_(("pending", "processing")),
                                     Document.updated_at < cutoff).limit(200)
    ).all()
    for doc_id in stuck:
        enqueue(process_upload, doc_id, priority=PRIORITY_MAINTENANCE)
    if stuck:
        log.info("documents_requeued", count=len(stuck))
    return {"requeued": len(stuck)}
