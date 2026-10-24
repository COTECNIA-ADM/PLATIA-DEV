"""Qué se indexa en Meilisearch y con qué configuración (Capítulo 13).

Cada índice declara por separado los atributos de búsqueda, de filtro y de
orden: Meilisearch solo filtra u ordena por lo que se declaró, y declarar de más
cuesta memoria. Las fechas van como segundos Unix (los filtros de rango son
numéricos) y los importes como número.

Los documentos guardan sus roles permitidos (``allowed_roles``) para filtrar en
la propia búsqueda; el backend vuelve a comprobar el permiso sobre MySQL antes
de devolver nada (la misma regla en dos sitios, como en el RAG).
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from flask import current_app
from sqlalchemy import select

from ..extensions import db
from ..models import Client, Document, Opportunity

OPEN_STATUSES = tuple(s for s in Opportunity.STATUSES if s not in ("won", "lost", "discarded"))

# Palabras sin valor para buscar. Lista corta y deliberada: Meilisearch ya da
# poco peso a las palabras muy frecuentes.
SPANISH_STOP_WORDS = ["de", "del", "la", "las", "el", "los", "y", "o", "en", "con", "para", "por", "a", "al",
                      "un", "una", "unos", "unas", "que", "se", "su", "sus", "lo"]

SYNONYMS = {
    "ciberseguridad": ["seguridad informatica", "seguridad de la informacion"],
    "seguridad informatica": ["ciberseguridad"],
    "ens": ["esquema nacional de seguridad"],
    "esquema nacional de seguridad": ["ens"],
    "ayuntamiento": ["consistorio"],
    "soc": ["centro de operaciones de seguridad"],
    "cloud": ["nube"],
    "nube": ["cloud"],
}

RANKING_RULES = ["words", "typo", "proximity", "attribute", "sort", "exactness"]


def ts(value: datetime | None) -> int | None:
    """Fecha guardada en UTC sin zona -> segundos Unix."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp())


def cpv_prefixes(codes: list | None) -> list[str]:
    """Prefijos de cada código CPV (2, 3, 4, 5 y 8 dígitos): filtrar por "72"
    encuentra todos los servicios TI sin que Meilisearch tenga que buscar por prefijo."""
    out: set[str] = set()
    for code in codes or []:
        digits = "".join(ch for ch in str(code) if ch.isdigit())[:8]
        for n in (2, 3, 4, 5, 8):
            if len(digits) >= n:
                out.add(digits[:n])
    return sorted(out)


# ---------------------------------------------------------------- Documentos de cada índice
def opportunity_doc(o: Opportunity) -> dict:
    return {
        "id": o.id, "code": o.code, "external_id": o.external_id, "title": o.title,
        "description": (o.description or "")[:4000], "contracting_entity": o.contracting_entity,
        "client_id": o.client_id, "client_name": o.client.name if o.client else None,
        "sector": o.sector, "service_line": o.service_line, "status": o.status, "phase": o.funnel_phase,
        "source": o.source, "cpv_codes": o.cpv_codes or [], "cpv_prefixes": cpv_prefixes(o.cpv_codes),
        "cpv_divisions": sorted({p for p in cpv_prefixes(o.cpv_codes) if len(p) == 2}),
        "estimated_value_eur": float(o.estimated_value_eur) if o.estimated_value_eur is not None else None,
        "deadline_ts": ts(o.deadline), "has_deadline": o.deadline is not None,
        "published_ts": ts(o.published_at), "created_ts": ts(o.created_at),
        "relevance_score": float(o.relevance_score) if o.relevance_score is not None else 0.0,
        "ai_score": o.ai_score, "owner_user_id": o.owner_user_id,
        "ai_summary": (o.ai_summary or "")[:2000],
    }


def document_doc(d: Document) -> dict:
    max_chars = current_app.config.get("MEILI_DOCUMENT_TEXT_CHARS", 20000)
    return {
        "id": d.id, "root_id": d.parent_version_id or d.id, "title": d.title,
        "original_filename": d.original_filename, "doc_type": d.doc_type, "mime_type": d.mime_type,
        "ai_summary": (d.ai_summary or "")[:2000], "ai_keywords": d.ai_keywords or [],
        "content": (d.extracted_text or "")[:max_chars], "created_by": d.created_by,
        "allowed_roles": list(d.allowed_roles) if d.allowed_roles else ["*"],
        "is_current": bool(d.is_current_version), "version_number": d.version_number,
        "processing_status": d.processing_status, "created_ts": ts(d.created_at),
    }


def client_doc(c: Client) -> dict:
    return {"id": c.id, "name": c.name, "tax_id": c.tax_id, "sector": c.sector, "segment": c.segment,
            "website": c.website, "owner_user_id": c.owner_user_id, "created_ts": ts(c.created_at)}


@dataclass(frozen=True)
class IndexSpec:
    name: str  # nombre lógico: opportunities, documents, clients
    model: type
    to_doc: Callable
    settings: dict
    # Campos que, si cambian en segundo plano (set_system_fields), obligan a reindexar
    system_fields: frozenset = frozenset()

    @property
    def uid(self) -> str:
        return f"{current_app.config.get('MEILI_INDEX_PREFIX', 'platia_')}{self.name}"

    def indexable(self, obj) -> bool:
        return bool(getattr(obj, "is_active", True))

    def base_query(self):
        return select(self.model).where(self.model.is_active.is_(True))


def _settings(searchable, filterable, sortable, displayed=None, no_typo=(), facet_sort=None) -> dict:
    return {
        "searchableAttributes": searchable,
        "filterableAttributes": filterable,
        "sortableAttributes": sortable,
        "displayedAttributes": displayed or ["*"],
        "rankingRules": RANKING_RULES,
        "stopWords": SPANISH_STOP_WORDS,
        "synonyms": SYNONYMS,
        # Los códigos (expediente, CPV, NIF) no admiten erratas: o coinciden o no
        "typoTolerance": {"enabled": True, "disableOnAttributes": list(no_typo), "disableOnNumbers": True},
        "pagination": {"maxTotalHits": 10000},
        "faceting": {"maxValuesPerFacet": 50, **({"sortFacetValuesBy": facet_sort} if facet_sort else {})},
    }


SPECS: dict[str, IndexSpec] = {
    "opportunities": IndexSpec(
        "opportunities", Opportunity, opportunity_doc,
        _settings(
            # El orden importa: una coincidencia en el código o el título pesa más
            searchable=["code", "external_id", "title", "contracting_entity", "client_name", "cpv_codes",
                        "ai_summary", "description"],
            filterable=["status", "phase", "sector", "service_line", "source", "cpv_prefixes", "cpv_divisions",
                        "estimated_value_eur", "deadline_ts", "has_deadline", "published_ts", "created_ts",
                        "relevance_score", "owner_user_id", "client_id"],
            sortable=["published_ts", "deadline_ts", "estimated_value_eur", "relevance_score", "created_ts"],
            no_typo=["code", "external_id", "cpv_codes"],
            facet_sort={"*": "count"},
        ),
        frozenset({"ai_summary", "relevance_score", "ai_score", "service_line", "status"}),
    ),
    "documents": IndexSpec(
        "documents", Document, document_doc,
        _settings(
            searchable=["title", "original_filename", "ai_keywords", "ai_summary", "content"],
            filterable=["doc_type", "allowed_roles", "created_by", "is_current", "root_id", "processing_status",
                        "created_ts"],
            sortable=["created_ts"],
            facet_sort={"*": "count"},
        ),
        frozenset({"ai_summary", "ai_keywords", "extracted_text", "processing_status", "allowed_roles",
                   "is_current_version", "doc_type", "title"}),
    ),
    "clients": IndexSpec(
        "clients", Client, client_doc,
        _settings(
            searchable=["name", "tax_id", "website", "sector"],
            filterable=["sector", "segment", "owner_user_id"],
            sortable=["created_ts"],
            no_typo=["tax_id"],
        ),
    ),
}

KIND_OF_MODEL = {spec.model: name for name, spec in SPECS.items()}


def spec_for(name: str) -> IndexSpec:
    try:
        return SPECS[name]
    except KeyError as exc:
        from ..errors import ValidationError

        raise ValidationError(f"Índice desconocido. Opciones: {', '.join(SPECS)}.") from exc


def mysql_count(spec: IndexSpec) -> int:
    return db.session.scalar(select(db.func.count()).select_from(spec.base_query().subquery())) or 0
