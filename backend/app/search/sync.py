"""Sincronización MySQL -> Meilisearch (Capítulo 13).

MySQL es la fuente de verdad; Meilisearch es un índice que se puede reconstruir
en cualquier momento sin perder nada.

1. **Cambios en caliente.** Cada vez que se confirma una transacción que crea,
   modifica o borra una oportunidad, un documento o un cliente, su id se apunta
   en un conjunto de Redis (``search:dirty:<índice>``). No se llama a
   Meilisearch dentro de la petición: si está caído, la API sigue funcionando.
   La tarea ``tasks.search.sync_pending`` vacía esos conjuntos en lotes (se
   lanza a los pocos segundos de un cambio y, por si acaso, cada minuto).
2. **Reconstrucción sin cortes.** ``rebuild`` llena un índice temporal, lo
   intercambia con el bueno (``swap-indexes``) y borra el viejo: mientras tanto
   las búsquedas siguen respondiendo con el índice anterior.
3. **Revisión periódica.** ``check_consistency`` compara cuántos registros hay
   en MySQL y en cada índice, y reconstruye el que no cuadra (también sirve para
   llenar los índices la primera vez).
"""
import hashlib
import json
import time

import structlog
from flask import current_app, has_app_context
from sqlalchemy import event, or_, select
from sqlalchemy.orm import Session, selectinload

from ..extensions import db
from ..models import Document, Opportunity, utcnow
from .client import MeiliError, get_search_client
from .indexes import KIND_OF_MODEL, SPECS, IndexSpec, mysql_count

log = structlog.get_logger(__name__)
DIRTY_KEY = "search:dirty:{}"
SETTINGS_KEY = "search:settings:{}"
LAST_SYNC_KEY = "search:last_sync"
LAST_REBUILD_KEY = "search:last_rebuild:{}"
SOON_KEY = "search:sync_soon"
BATCH = 1000


def _redis():
    from ..security.redis_store import get_redis

    return get_redis()


def enabled() -> bool:
    return has_app_context() and current_app.config.get("SEARCH_ENABLED", True)


# ------------------------------------------------------------------ Cambios en caliente
def _pending(session: Session) -> set:
    return session.info.setdefault("search_dirty", set())


def mark_dirty(session: Session, obj, fields=None) -> None:
    """Apunta un registro para reindexarlo cuando se confirme la transacción.
    ``fields``: campos cambiados por un proceso en segundo plano; si ninguno
    se indexa, no hace falta reindexar."""
    kind = KIND_OF_MODEL.get(type(obj))
    if kind is None or obj.id is None:
        return
    if fields is not None and not (set(fields) & SPECS[kind].system_fields):
        return
    _pending(session).add((kind, obj.id))


@event.listens_for(Session, "after_flush")
def _collect(session: Session, _ctx) -> None:
    for obj in (*session.new, *session.dirty, *session.deleted):
        if type(obj) in KIND_OF_MODEL:
            mark_dirty(session, obj)


@event.listens_for(Session, "after_commit")
def _publish(session: Session) -> None:
    pending = session.info.pop("search_dirty", None)
    if not pending or not enabled():
        return
    by_kind: dict[str, list[int]] = {}
    for kind, obj_id in pending:
        by_kind.setdefault(kind, []).append(obj_id)
    try:
        r = _redis()
        pipe = r.pipeline()
        for kind, ids in by_kind.items():
            pipe.sadd(DIRTY_KEY.format(kind), *ids)
        pipe.execute()
    except Exception as exc:  # noqa: BLE001 - la revisión periódica lo arreglará
        log.warning("search_mark_failed", error=str(exc), pending=len(pending))
        return
    _sync_soon()


@event.listens_for(Session, "after_rollback")
def _discard(session: Session) -> None:
    session.info.pop("search_dirty", None)


def _sync_soon() -> None:
    """Lanza la sincronización en unos segundos (una sola vez aunque haya muchos cambios)."""
    if current_app.config.get("CELERY_ALWAYS_EAGER"):
        return  # en los tests se sincroniza a mano
    try:
        if not _redis().set(SOON_KEY, "1", nx=True, ex=3):
            return
        from ..tasks.search import sync_pending

        sync_pending.apply_async(countdown=2, priority=3)
    except Exception as exc:  # noqa: BLE001 - la tarea programada lo recogerá
        log.info("search_sync_soon_skipped", error=str(exc))


# ------------------------------------------------------------------ Configuración de índices
def _settings_hash(spec: IndexSpec) -> str:
    return hashlib.sha256(json.dumps(spec.settings, sort_keys=True).encode()).hexdigest()[:16]


def ensure_index(spec: IndexSpec, uid: str | None = None, wait: bool = False) -> None:
    """Crea el índice si no existe y aplica la configuración si ha cambiado."""
    uid = uid or spec.uid
    client = get_search_client()
    key, wanted = SETTINGS_KEY.format(uid), _settings_hash(spec)
    r = _redis()
    if r.get(key) == wanted.encode() and client.index_stats(uid) is not None:
        return
    if client.index_stats(uid) is None:
        task = client.create_index(uid)
        if wait:
            client.wait(task)
    task = client.update_settings(uid, spec.settings)
    if wait:
        client.wait(task)
    r.set(key, wanted, ex=86400)
    log.info("search_index_configured", index=uid)


# ------------------------------------------------------------------ Sincronización de pendientes
def _load(spec: IndexSpec, ids: list[int]) -> list:
    stmt = select(spec.model).where(spec.model.id.in_(ids))
    if spec.model is Opportunity:
        stmt = stmt.options(selectinload(Opportunity.client))
    return list(db.session.scalars(stmt))


def push(spec: IndexSpec, ids: list[int], uid: str | None = None) -> dict:
    """Envía a Meilisearch el estado actual de esos registros (o los borra)."""
    uid = uid or spec.uid
    objs = {o.id: o for o in _load(spec, ids)}
    docs = [spec.to_doc(o) for o in objs.values() if spec.indexable(o)]
    gone = [i for i in ids if i not in objs or not spec.indexable(objs[i])]
    client = get_search_client()
    if docs:
        client.add_documents(uid, docs)
    if gone:
        client.delete_documents(uid, gone)
    return {"indexed": len(docs), "deleted": len(gone)}


def _expand(kind: str, ids: list[int]) -> None:
    """Un cliente cambia de nombre: sus oportunidades llevan ese nombre en el índice."""
    if kind == "clients" and ids:
        opp_ids = list(db.session.scalars(select(Opportunity.id).where(Opportunity.client_id.in_(ids))))
        if opp_ids:
            _redis().sadd(DIRTY_KEY.format("opportunities"), *opp_ids)


def sync_pending() -> dict:
    """Vacía los conjuntos de pendientes. Si Meilisearch falla, los ids vuelven a Redis."""
    r = _redis()
    totals = {}
    for kind in ("clients", "documents", "opportunities"):  # clientes antes: amplían oportunidades
        spec = SPECS[kind]
        key = DIRTY_KEY.format(kind)
        done = {"indexed": 0, "deleted": 0}
        while True:
            raw = r.spop(key, BATCH)
            if not raw:
                break
            ids = sorted({int(x) for x in raw})
            try:
                ensure_index(spec)
                result = push(spec, ids)
            except MeiliError:
                r.sadd(key, *ids)
                raise
            _expand(kind, ids)
            done = {k: done[k] + result[k] for k in done}
        totals[kind] = done
    r.set(LAST_SYNC_KEY, utcnow().isoformat())
    if any(v["indexed"] or v["deleted"] for v in totals.values()):
        log.info("search_synced", **{k: v for k, v in totals.items() if v["indexed"] or v["deleted"]})
    return totals


def pending_counts() -> dict[str, int]:
    r = _redis()
    return {kind: int(r.scard(DIRTY_KEY.format(kind))) for kind in SPECS}


# ------------------------------------------------------------------ Reconstrucción
def rebuild(kind: str) -> dict:
    """Reconstruye un índice completo sin dejar de dar servicio."""
    spec = SPECS[kind]
    client = get_search_client()
    started_at, t0 = utcnow(), time.monotonic()
    tmp = f"{spec.uid}__rebuild"
    if client.index_stats(tmp) is not None:  # restos de una reconstrucción interrumpida
        client.wait(client.delete_index(tmp))
    ensure_index(spec, tmp, wait=True)
    last_task, total, last_id = None, 0, 0
    while True:
        stmt = spec.base_query().where(spec.model.id > last_id).order_by(spec.model.id).limit(BATCH)
        if spec.model is Opportunity:
            stmt = stmt.options(selectinload(Opportunity.client))
        rows = list(db.session.scalars(stmt))
        if not rows:
            break
        last_task = client.add_documents(tmp, [spec.to_doc(o) for o in rows])
        total += len(rows)
        last_id = rows[-1].id
        db.session.expunge_all()  # memoria acotada con millones de filas
    if last_task:
        client.wait(last_task, timeout=1800)
    ensure_index(spec, wait=True)
    client.wait(client.swap_indexes([(spec.uid, tmp)]))
    client.delete_index(tmp)
    _redis().delete(SETTINGS_KEY.format(tmp))
    # Lo que cambió mientras se llenaba el temporal se vuelve a enviar
    changed = _changed_since(spec, started_at)
    if changed:
        _redis().sadd(DIRTY_KEY.format(kind), *changed)
    _redis().set(LAST_REBUILD_KEY.format(kind), utcnow().isoformat())
    seconds = round(time.monotonic() - t0, 1)
    log.info("search_index_rebuilt", index=kind, documents=total, seconds=seconds, resynced=len(changed))
    return {"index": kind, "documents": total, "seconds": seconds}


def _changed_since(spec: IndexSpec, since) -> list[int]:
    model = spec.model
    conditions = [model.updated_at >= since]
    if model is Document:
        conditions += [Document.processed_at >= since, Document.ai_enriched_at >= since]
    if model is Opportunity:
        conditions.append(Opportunity.scored_at >= since)
    return list(db.session.scalars(select(model.id).where(or_(*conditions))))


# ------------------------------------------------------------------ Estado y revisión
def status() -> list[dict]:
    client = get_search_client()
    pending = pending_counts()
    r = _redis()
    out = []
    for kind, spec in SPECS.items():
        try:
            stats = client.index_stats(spec.uid)
            error = None
        except MeiliError as exc:
            stats, error = None, str(exc)
        expected = mysql_count(spec)
        last = r.get(LAST_REBUILD_KEY.format(kind))
        out.append({
            "index": kind, "uid": spec.uid, "mysql_count": expected,
            "documents": stats.get("numberOfDocuments") if stats else None,
            "is_indexing": stats.get("isIndexing") if stats else None,
            "pending": pending[kind], "last_rebuild": last.decode() if last else None,
            "in_sync": bool(stats) and stats.get("numberOfDocuments") == expected and not pending[kind],
            **({"error": error} if error else {}),
        })
    return out


def check_consistency() -> list[str]:
    """Índices que no cuadran con MySQL (y no están a medio indexar). Devuelve sus nombres."""
    stale = []
    for row in status():
        if row.get("error"):
            raise MeiliError(row["error"])
        if row["pending"] or row["is_indexing"]:
            continue
        if row["documents"] != row["mysql_count"]:
            stale.append(row["index"])
    return stale
