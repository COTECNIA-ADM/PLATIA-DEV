"""Tareas de IA (cola ``ai``, Capítulos 10-12).

Todas son idempotentes: repetir una tarea reescribe el mismo resultado (los
puntos de Qdrant tienen identificadores deterministas, el análisis se guarda
en su propia fila). Los fallos pasajeros del servicio de IA se reintentan con
backoff; un presupuesto agotado, la IA desactivada o un rechazo del modelo no se
reintentan: se marca el fallo y se avisa a quien lo pidió.
"""
from datetime import timedelta

import structlog
from flask import current_app

from ..ai import analysis as analysis_service
from ..ai import pii, prompts, rag, similar
from ..ai.client import AIServiceError, get_ai_client
from ..ai.errors import AIDisabledError, AIRejectedError, AIUnavailableError, BudgetExceededError
from ..extensions import db
from ..models import (AIAnalysis, AuditAction, Document, LLMQualityScore, LLMUsageLog, Opportunity, Proposal,
                      utcnow)
from ..queue import PRIORITY_MAINTENANCE, PlatformTask, TaskAlreadyRunning, celery, enqueue, task_lock
from ..security.audit import audit
from ..services.notifications import notify, notify_many, superadmins

log = structlog.get_logger(__name__)
# Errores que no se arreglan reintentando
FINAL_ERRORS = (AIDisabledError, AIRejectedError, BudgetExceededError)


def _ai_ready() -> bool:
    return bool(current_app.config.get("AI_ENABLED", True))


# ------------------------------------------------------------------ Documentos
@celery.task(name="tasks.ai.index_document", base=PlatformTask, bind=True, max_retries=5)
def index_document(self, document_id: int) -> dict:
    doc = db.session.get(Document, document_id)
    if doc is None:
        return {"document_id": document_id, "status": "missing"}
    try:
        with task_lock(f"index:{document_id}", expire=900):
            result = rag.index_document(doc)
            db.session.commit()
            return {"document_id": document_id, **result}
    except TaskAlreadyRunning:
        return {"document_id": document_id, "status": "already_running"}
    except AIServiceError as exc:
        db.session.rollback()
        doc = db.session.get(Document, document_id)
        doc.set_system_fields(index_status="failed" if self.request.retries >= self.max_retries else "pending")
        db.session.commit()
        raise self.retry_later(exc)


@celery.task(name="tasks.ai.enrich_document", base=PlatformTask, bind=True, max_retries=3)
def enrich_document(self, document_id: int) -> dict:
    doc = db.session.get(Document, document_id)
    if doc is None or not doc.is_active or not _ai_ready():
        return {"document_id": document_id, "status": "skipped"}
    if doc.ai_enriched_at is not None and doc.processed_at and doc.ai_enriched_at >= doc.processed_at:
        return {"document_id": document_id, "status": "enriched", "skipped": True}
    try:
        result = analysis_service.enrich_document(doc)
        db.session.commit()
        return {"document_id": document_id, **result}
    except FINAL_ERRORS as exc:
        db.session.rollback()
        log.info("document_enrichment_skipped", document_id=document_id, reason=type(exc).__name__)
        return {"document_id": document_id, "status": "skipped", "reason": exc.error_type}
    except AIUnavailableError as exc:
        db.session.rollback()
        raise self.retry_later(exc)


@celery.task(name="tasks.ai.sync_document_access", base=PlatformTask, bind=True, max_retries=8)
def sync_document_access(self, document_id: int) -> dict:
    """Copia a Qdrant un cambio de roles permitidos (si falla, el backend ya filtra)."""
    doc = db.session.get(Document, document_id)
    if doc is None:
        return {"document_id": document_id, "status": "missing"}
    try:
        if not doc.is_active:
            for version in rag._versions(doc):
                rag.deindex_document(version)
        else:
            rag.sync_access(doc)
        db.session.commit()
    except AIServiceError as exc:
        db.session.rollback()
        raise self.retry_later(exc)
    return {"document_id": document_id, "status": "synced"}


def after_document_processed(document_id: int) -> None:
    """Se llama al terminar la extracción de texto: indexa y enriquece."""
    enqueue(index_document, document_id)
    if current_app.config.get("AI_AUTO_ENRICH", True):
        enqueue(enrich_document, document_id)


# ------------------------------------------------------------------ Análisis
def _fail_analysis(analysis: AIAnalysis, message: str) -> None:
    analysis.status, analysis.error = "failed", message[:500]
    db.session.commit()
    if analysis.created_by:
        notify(analysis.created_by, "SYSTEM", "No se ha podido completar el análisis", message[:500],
               link=f"/{'documents' if analysis.subject_type == 'document' else 'opportunities'}/{analysis.subject_id}")


@celery.task(name="tasks.ai.analyze", base=PlatformTask, bind=True, max_retries=3)
def analyze(self, analysis_id: int) -> dict:
    analysis = db.session.get(AIAnalysis, analysis_id)
    if analysis is None or analysis.status in ("done", "failed"):
        return {"analysis_id": analysis_id, "status": "skipped"}
    try:
        with task_lock(f"analysis:{analysis_id}", expire=1800):
            analysis = analysis_service.run(analysis)
    except TaskAlreadyRunning:
        return {"analysis_id": analysis_id, "status": "already_running"}
    except FINAL_ERRORS as exc:
        db.session.rollback()
        _fail_analysis(db.session.get(AIAnalysis, analysis_id), exc.message)
        return {"analysis_id": analysis_id, "status": "failed"}
    except AIUnavailableError as exc:
        db.session.rollback()
        analysis = db.session.get(AIAnalysis, analysis_id)
        if self.request.retries >= self.max_retries:
            _fail_analysis(analysis, exc.message)
            return {"analysis_id": analysis_id, "status": "failed"}
        analysis.status = "queued"
        db.session.commit()
        raise self.retry_later(exc)
    if analysis.status == "done" and analysis.created_by:
        notify(analysis.created_by, "REPORT_READY", f"Análisis GO/NO-GO listo: {analysis.verdict}",
               (analysis.result or {}).get("summary", "")[:500],
               link=f"/{'documents' if analysis.subject_type == 'document' else 'opportunities'}/{analysis.subject_id}")
    return {"analysis_id": analysis_id, "status": analysis.status, "verdict": analysis.verdict}


# ------------------------------------------------------------------ Propuestas
@celery.task(name="tasks.ai.generate_proposal", base=PlatformTask, bind=True, max_retries=2)
def generate_proposal(self, proposal_id: int, user_id: int | None, keys: list[str] | None = None,
                      instructions: str | None = None) -> dict:
    from ..ai import proposal_writer

    proposal = db.session.get(Proposal, proposal_id)
    if proposal is None or not proposal.is_active or proposal.generation_status not in ("queued", "running"):
        return {"proposal_id": proposal_id, "status": "skipped"}
    try:
        with task_lock(f"proposal_ai:{proposal_id}", expire=3600):
            proposal.set_system_fields(generation_status="running")
            db.session.commit()
            result = proposal_writer.generate(proposal, user_id, keys, instructions)
    except TaskAlreadyRunning:
        return {"proposal_id": proposal_id, "status": "already_running"}
    except (*FINAL_ERRORS, AIUnavailableError) as exc:
        db.session.rollback()
        retry = isinstance(exc, AIUnavailableError) and self.request.retries < self.max_retries
        proposal = db.session.get(Proposal, proposal_id)
        proposal.set_system_fields(generation_status="queued" if retry else "failed",
                                   generation_error=None if retry else exc.message[:500])
        db.session.commit()
        if retry:
            raise self.retry_later(exc)
        if user_id:
            notify(user_id, "SYSTEM", "No se ha podido redactar la propuesta", exc.message[:500],
                   link=f"/proposals/{proposal_id}")
        return {"proposal_id": proposal_id, "status": "failed"}
    if user_id:
        notify(user_id, "REPORT_READY", "Borrador de propuesta listo",
               f"Se han redactado {len(result['sections'])} secciones de «{proposal.title[:200]}». Revísalas antes "
               "de enviarlas a revisión.", link=f"/proposals/{proposal_id}")
    return {**result, "status": "done"}


# ------------------------------------------------------------------ Oportunidades
@celery.task(name="tasks.ai.index_opportunity", base=PlatformTask, bind=True, max_retries=3)
def index_opportunity(self, opportunity_id: int) -> dict:
    opp = db.session.get(Opportunity, opportunity_id)
    if opp is None:
        return {"opportunity_id": opportunity_id, "status": "missing"}
    try:
        return {"opportunity_id": opportunity_id, **similar.index_opportunity(opp)}
    except AIServiceError as exc:
        raise self.retry_later(exc)


# ------------------------------------------------------------------ Calidad
@celery.task(name="tasks.ai.evaluate_rag", base=PlatformTask, bind=True, max_retries=2)
def evaluate_rag(self, usage_log_id: int, question: str, context: str, answer: str) -> dict:
    """Evaluación automática de una muestra de respuestas (Capítulo 11: LLM como juez)."""
    from ..ai import gateway
    from ..ai.schemas import RAG_EVALUATION, clamp

    if db.session.scalar(db.select(LLMQualityScore.id).filter_by(usage_log_id=usage_log_id, reviewer_type="automated")):
        return {"usage_log_id": usage_log_id, "status": "already_evaluated"}
    try:
        result = gateway.run("rag_evaluation", variables={"question": question, "sources": context, "answer": answer},
                             json_schema=RAG_EVALUATION)
    except FINAL_ERRORS as exc:
        return {"usage_log_id": usage_log_id, "status": "skipped", "reason": exc.error_type}
    except AIUnavailableError as exc:
        raise self.retry_later(exc)
    data = result.data if isinstance(result.data, dict) else {}
    scores = {k: clamp(data.get(k)) for k in ("faithfulness", "relevance", "completeness", "hallucination")}
    present = [v for k, v in scores.items() if v is not None and k != "hallucination"]
    composite = round(sum(present) / len(present), 3) if present else None
    db.session.add(LLMQualityScore(
        usage_log_id=usage_log_id, service_type="chat_rag", faithfulness_score=scores["faithfulness"],
        groundedness_score=scores["faithfulness"], relevance_score=scores["relevance"],
        completeness_score=scores["completeness"], hallucination_score=scores["hallucination"],
        composite_score=composite, pii_detected=bool(pii.scan(answer)), reviewer_type="automated",
        notes="; ".join(data.get("issues") or [])[:1000] or None))
    db.session.commit()
    return {"usage_log_id": usage_log_id, "status": "evaluated", "composite": composite}


# ------------------------------------------------------------------ Programadas
@celery.task(name="tasks.ai.verify_prompt_integrity", base=PlatformTask)
def verify_prompt_integrity() -> dict:
    violations = prompts.verify_integrity()
    for v in violations:
        audit(AuditAction.PROMPT_INTEGRITY_VIOLATION, "CRITICAL", resource_type="prompts", details=v)
    if violations:
        notify_many(superadmins(), "SYSTEM", "Prompts modificados fuera del versionado",
                    body=", ".join(f"{v['name']} v{v['version']}" for v in violations)[:500], priority="high",
                    link="/admin/ia/prompts")
    return {"violations": len(violations)}


@celery.task(name="tasks.ai.scan_pii_outputs", base=PlatformTask)
def scan_pii_outputs(batch: int = 500) -> dict:
    """Busca datos personales en las respuestas recientes (muestra de 500 caracteres)."""
    rows = db.session.scalars(db.select(LLMUsageLog).where(LLMUsageLog.output_sample.is_not(None),
                                                           LLMUsageLog.contained_pii.is_(None)).limit(batch)).all()
    found = 0
    for row in rows:
        types = pii.scan(row.output_sample)
        row.contained_pii = bool(types)
        row.pii_types = types or None
        if types:
            found += 1
            audit(AuditAction.PII_DETECTED_IN_OUTPUT, "WARNING", user_id=row.user_id, resource_type="llm_usage_log",
                  resource_id=row.id, details={"service_type": row.service_type, "types": types})
    db.session.commit()
    return {"scanned": len(rows), "with_pii": found}


@celery.task(name="tasks.ai.check_budgets", base=PlatformTask)
def check_budgets() -> dict:
    """Revisión horaria: avisa de presupuestos cerca del límite aunque no haya llamadas."""
    from ..ai import budget

    alerts = budget.scan()
    if alerts:
        log.warning("ai_budgets_near_limit", count=alerts)
    return {"near_limit": alerts}


@celery.task(name="tasks.ai.rag_consistency", base=PlatformTask, bind=True, max_retries=1)
def rag_consistency(self) -> dict:
    """Compara MySQL con Qdrant: reindexa lo que falta y borra vectores huérfanos."""
    try:
        refs = get_ai_client().refs(rag.COLLECTION)
    except AIServiceError as exc:
        raise self.retry_later(exc)
    docs = {d.id: d for d in db.session.scalars(db.select(Document).where(Document.index_status == "indexed"))}
    reindex = [d.id for d in docs.values() if d.is_active and refs.get(d.id, 0) != (d.vector_count or 0)]
    orphans = [ref for ref in refs if ref not in docs or not docs[ref].is_active]
    for ref in orphans:
        get_ai_client().delete(rag.COLLECTION, ref)
    for doc_id in reindex[:500]:
        enqueue(index_document, doc_id, priority=PRIORITY_MAINTENANCE)
    log.info("rag_consistency_checked", reindex=len(reindex), orphans=len(orphans))
    return {"reindex": len(reindex), "orphans_deleted": len(orphans)}


@celery.task(name="tasks.ai.recover_index", base=PlatformTask)
def recover_index(older_than_minutes: int = 15) -> dict:
    """Documentos procesados que se quedaron sin indexar (broker o IA caídos)."""
    cutoff = utcnow() - timedelta(minutes=older_than_minutes)
    ids = db.session.scalars(db.select(Document.id).where(
        Document.is_active.is_(True), Document.processing_status == "processed",
        Document.index_status.in_(("none", "pending")), Document.updated_at < cutoff).limit(200)).all()
    for doc_id in ids:
        enqueue(index_document, doc_id, priority=PRIORITY_MAINTENANCE)
    return {"requeued": len(ids)}


@celery.task(name="tasks.ai.cleanup_usage_samples", base=PlatformTask)
def cleanup_usage_samples() -> dict:
    """Borra las muestras de respuesta pasada la retención (minimización de datos)."""
    days = current_app.config.get("AI_SAMPLE_RETENTION_DAYS", 30)
    cutoff = utcnow() - timedelta(days=days)
    result = db.session.execute(db.update(LLMUsageLog).where(LLMUsageLog.created_at < cutoff,
                                                             LLMUsageLog.output_sample.is_not(None))
                                .values(output_sample=None))
    db.session.commit()
    return {"cleared": result.rowcount or 0}
