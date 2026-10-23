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

# Roles por aplicación (Capítulo 6). Permisos: {módulo: [acciones]}. Lo que no
# aparece está denegado. Los roles con is_admin=True tienen todo, solo en su app.
R, RW = ["read"], ["read", "write"]
AI_ALL = ["document_analyzer", "proposal_generator", "cv_analyzer", "copilot_chat"]
ROLES = {
    "operations": {
        "admin": ("Administrador de operaciones", True, {}),
        "manager": ("Responsable comercial", False, {
            "clients": RW, "opportunities": RW, "documents": ["read", "write", "upload"],
            "proposals": ["read", "write", "delete"], "reports": ["read", "generate"],
            "ai_modules_access": AI_ALL,
        }),
        "analyst": ("Analista", False, {
            "clients": R, "opportunities": RW, "documents": ["read", "upload"], "proposals": RW,
            "reports": R, "ai_modules_access": ["document_analyzer", "copilot_chat"],
        }),
        "viewer": ("Consulta", False, {
            "clients": R, "opportunities": R, "documents": R, "proposals": R, "reports": R,
            "ai_modules_access": [],
        }),
    },
    "analytics": {
        "admin": ("Administrador de analítica", True, {}),
        "analyst": ("Analista de negocio", False, {"dashboards": RW, "reports": ["read", "generate"],
                                                   "ai_modules_access": ["copilot_chat"]}),
        "viewer": ("Consulta", False, {"dashboards": R, "reports": R, "ai_modules_access": []}),
    },
    "admin": {
        "superadmin": ("Superadministrador", True, {}),
        "admin": ("Administrador", False, {
            "users": RW, "roles": RW, "llm_config": RW, "prompts": RW, "audit": R, "health": R,
        }),
        "auditor": ("Auditor", False, {
            "users": R, "roles": R, "llm_config": R, "prompts": R, "audit": R, "health": R,
        }),
    },
    "security": {
        "security_admin": ("Responsable de seguridad", True, {}),
        "security_analyst": ("Analista de seguridad", False, {"audit": R, "alerts": RW, "guardrails": R}),
        "viewer": ("Consulta", False, {"audit": R, "alerts": R}),
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
        for code, (name, is_admin, permissions) in roles.items():
            if code not in existing:
                db.session.add(AppRole(app_id=app.id, code=code, name=name, is_admin=is_admin,
                                       permissions=permissions))
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
