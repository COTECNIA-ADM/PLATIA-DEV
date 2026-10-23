"""Datos iniciales de la plataforma (idempotentes).

Solo crea lo que falta: si alguien ya editó un valor (por ejemplo un precio
desde Admin), no se sobrescribe. No crea usuarios ni contraseñas: el primer
administrador se da de alta en la fase 3.
"""
from datetime import date
from decimal import Decimal

import structlog

from .extensions import db
from .models import App, AppRole, LLMModelPricing, LLMServiceConfig

log = structlog.get_logger(__name__)

APPS = [
    ("operations", "Operaciones", "Oportunidades, documentos y propuestas"),
    ("analytics", "Inteligencia de negocio", "Embudo, cuadros de mando y tendencias"),
    ("admin", "Administración", "Usuarios, roles, modelos de IA y prompts"),
    ("security", "Seguridad", "Auditoría y eventos de seguridad"),
]

# Permisos "recurso:acción" por rol. Se aplican en la fase 3.
ROLES = {
    "operations": {
        "viewer": ("Consulta", ["clients:read", "opportunities:read", "documents:read", "proposals:read"]),
        "editor": (
            "Gestor comercial",
            ["clients:read", "clients:write", "opportunities:read", "opportunities:write",
             "documents:read", "documents:write", "proposals:read", "proposals:write"],
        ),
        "admin": ("Responsable", ["operations:*"]),
    },
    "analytics": {
        "viewer": ("Consulta", ["dashboards:read"]),
        "admin": ("Responsable", ["analytics:*"]),
    },
    "admin": {
        "admin": ("Administrador", ["users:*", "roles:*", "llm:*", "prompts:*"]),
    },
    "security": {
        "auditor": ("Auditor", ["audit:read"]),
        "admin": ("Responsable de seguridad", ["security:*"]),
    },
}

# Modelo por tipo de tarea, con reserva (Cap. 11). Editable desde Admin más adelante.
LLM_SERVICES = [
    # service_type, modelo, reserva, max_tokens
    ("document_analysis", "claude-sonnet-5-5", "claude-haiku-5-5", 8000),
    ("opportunity_scoring", "claude-haiku-5-5", "claude-sonnet-5-5", 2000),
    ("proposal_generation", "claude-opus-5-5", "claude-sonnet-5-5", 16000),
    ("chat_rag", "claude-sonnet-5-5", "claude-haiku-5-5", 4000),
]

# USD por millón de tokens (precio estándar publicado por Anthropic en la fecha indicada)
PRICING_DATE = date(2026, 10, 23)
LLM_PRICING = [
    ("claude-opus-5-5", Decimal("4.00"), Decimal("20.00")),
    ("claude-sonnet-5-5", Decimal("2.00"), Decimal("10.00")),
    ("claude-haiku-5-5", Decimal("0.10"), Decimal("0.50")),
]


def run_seeds() -> dict[str, int]:
    created = {"apps": 0, "roles": 0, "llm_services": 0, "llm_pricing": 0}

    apps = {a.code: a for a in db.session.scalars(db.select(App))}
    for code, name, description in APPS:
        if code not in apps:
            apps[code] = App(code=code, name=name, description=description)
            db.session.add(apps[code])
            created["apps"] += 1
    db.session.flush()

    for app_code, roles in ROLES.items():
        app = apps[app_code]
        existing = {r.code for r in db.session.scalars(db.select(AppRole).filter_by(app_id=app.id))}
        for code, (name, permissions) in roles.items():
            if code not in existing:
                db.session.add(AppRole(app_id=app.id, code=code, name=name, permissions=permissions))
                created["roles"] += 1

    for service_type, model, fallback, max_tokens in LLM_SERVICES:
        if db.session.get(LLMServiceConfig, service_type) is None:
            db.session.add(
                LLMServiceConfig(
                    service_type=service_type,
                    provider="anthropic",
                    model_name=model,
                    fallback_provider="anthropic",
                    fallback_model=fallback,
                    max_tokens=max_tokens,
                )
            )
            created["llm_services"] += 1

    for model, input_price, output_price in LLM_PRICING:
        if db.session.get(LLMModelPricing, ("anthropic", model, PRICING_DATE)) is None:
            db.session.add(
                LLMModelPricing(
                    provider="anthropic",
                    model_name=model,
                    effective_date=PRICING_DATE,
                    input_usd_per_mtok=input_price,
                    output_usd_per_mtok=output_price,
                )
            )
            created["llm_pricing"] += 1

    db.session.commit()
    log.info("seeds_applied", **created)
    return created
