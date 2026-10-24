"""Datos iniciales de la plataforma (idempotentes).

Solo crea lo que falta: si alguien ya editó un valor (por ejemplo un precio
desde Admin), no se sobrescribe. No crea usuarios ni contraseñas: el primer
administrador se da de alta en la fase 3.
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

import structlog

from .extensions import db
from .models import (App, AppRole, BudgetConfig, HumanBaselineConfig, LLMModelPricing, LLMServiceConfig, Prompt,
                     ProposalTemplate, ServiceLine)

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
            "clients": ["read", "write", "delete"],
            "opportunities": ["read", "write", "delete", "manage", "export"],
            "documents": ["read", "write", "upload", "delete", "manage"],
            "proposals": ["read", "write", "delete", "manage", "approve", "send"],
            "templates": RW, "portfolio": RW, "talent": ["read", "write", "delete"],
            "alerts": RW, "notifications": R, "reports": ["read", "generate"],
            "ai_modules_access": AI_ALL,
        }),
        # El analista solo modifica lo que tiene asignado (autorización por objeto)
        "analyst": ("Analista", False, {
            "clients": R, "opportunities": RW, "documents": ["read", "upload", "write"],
            "proposals": RW, "templates": R, "portfolio": R, "talent": R, "alerts": R,
            "notifications": R, "reports": R, "ai_modules_access": ["document_analyzer", "copilot_chat"],
        }),
        "viewer": ("Consulta", False, {
            "clients": R, "opportunities": R, "documents": R, "proposals": R, "reports": R,
            "templates": R, "portfolio": R, "talent": R, "alerts": R, "notifications": R,
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
            "tasks": RW,
        }),
        "auditor": ("Auditor", False, {
            "users": R, "roles": R, "llm_config": R, "prompts": R, "audit": R, "health": R,
            "tasks": R,
        }),
    },
    "security": {
        "security_admin": ("Responsable de seguridad", True, {}),
        "security_analyst": ("Analista de seguridad", False, {"audit": R, "alerts": RW, "guardrails": R}),
        "viewer": ("Consulta", False, {"audit": R, "alerts": R}),
    },
}

# Portfolio de partida para puntuar oportunidades (Capítulo 9). Editable desde la API.
# Prefijos CPV de la UE: 72 servicios TI, 48 paquetes de software, 79411 consultoría de gestión.
SERVICE_LINES = [
    ("cloud", "Cloud e infraestructura", ["725", "723", "724"],
     ["cloud", "nube", "azure", "aws", "kubernetes", "devops", "hosting", "centro de datos",
      "infraestructura", "migracion"]),
    ("cyber", "Ciberseguridad", ["72212730", "726"],
     ["ciberseguridad", "seguridad", "soc", "pentest", "ens", "iso 27001", "siem", "vulnerabilidades"]),
    ("applications", "Desarrollo de aplicaciones", ["722", "48"],
     ["desarrollo", "aplicacion", "software", "portal", "web", "movil", "mantenimiento evolutivo"]),
    ("data", "Datos e IA", ["723", "72316"],
     ["datos", "analitica", "business intelligence", "inteligencia artificial", "machine learning",
      "big data", "cuadro de mando"]),
    ("integration", "Integración", ["7222", "48"],
     ["integracion", "api", "erp", "middleware", "interoperabilidad", "sap"]),
    ("consulting", "Consultoría TI", ["7222", "79411"],
     ["consultoria", "oficina tecnica", "pmo", "itil", "transformacion digital", "asistencia tecnica"]),
]

# Plantillas de propuesta por tipo: [(clave, título)]
_BASE = [("resumen_ejecutivo", "Resumen ejecutivo"), ("contexto", "Contexto y necesidades"),
         ("solucion", "Solución propuesta"), ("metodologia", "Metodología y plan de trabajo"),
         ("equipo", "Equipo"), ("presupuesto", "Presupuesto")]
PROPOSAL_TEMPLATES = [
    ("Propuesta base", "base", _BASE),
    ("Propuesta competitiva", "competitive",
     _BASE[:3] + [("diferenciales", "Diferenciales frente a la competencia")] + _BASE[3:]),
    ("Propuesta premium", "premium",
     _BASE[:1] + [("valor_estrategico", "Valor estratégico")] + _BASE[1:] +
     [("gobierno", "Gobierno del servicio y SLA")]),
    ("Propuesta a medida", "custom", _BASE),
    ("Propuesta ejecutiva", "executive",
     [("mensaje_direccion", "Mensaje para la dirección"), ("resumen_ejecutivo", "Resumen ejecutivo"),
      ("valor_estrategico", "Valor e impacto en el negocio"), ("solucion", "Solución en una página"),
      ("presupuesto", "Inversión")]),
]


# Modelo por tipo de tarea, con reserva (patrón LLM Factory, Cap. 11). Editable
# desde Admin. El modelo de cada tarea se elige por coste y dificultad: el rápido
# para catalogar y reescribir, el intermedio para analizar y responder, el más
# capaz para redactar propuestas. Los max_tokens incluyen el razonamiento interno.
LLM_SERVICES = [
    # service_type, modelo, reserva, max_tokens, esfuerzo, prompt, descripción
    ("document_analysis", "claude-sonnet-5-5", "claude-haiku-5-5", 12000, "medium", "analysis.go_no_go",
     "Análisis GO/NO-GO de documentos y oportunidades"),
    ("document_enrichment", "claude-haiku-5-5", "claude-sonnet-5-5", 3000, "low", "document.enrichment",
     "Resumen, palabras clave y entidades de cada documento"),
    ("opportunity_scoring", "claude-haiku-5-5", "claude-sonnet-5-5", 2000, "low", None,
     "Reservado: la puntuación usa embeddings, sin LLM"),
    ("proposal_generation", "claude-opus-5-5", "claude-sonnet-5-5", 16000, "medium", "proposal.section",
     "Redacción de secciones de propuestas"),
    ("chat_rag", "claude-sonnet-5-5", "claude-haiku-5-5", 4000, "low", "rag.answer",
     "Respuestas sobre los documentos, con citas"),
    ("rag_query_rewrite", "claude-haiku-5-5", None, 2000, "low", "rag.query_rewrite",
     "Reescritura de preguntas para la búsqueda"),
    ("rag_evaluation", "claude-haiku-5-5", "claude-sonnet-5-5", 3000, "low", "rag.evaluate",
     "Evaluación automática de una muestra de respuestas"),
]

# USD por millón de tokens (precio estándar publicado por Anthropic en la fecha
# indicada). Caché: lectura y escritura de 5 minutos. Haiku 5.5 cobra más por
# encima de 100.000 tokens de entrada; la tabla usa el precio base (ADR-011).
PRICING_DATE = date(2026, 10, 23)
LLM_PRICING = [
    # modelo, entrada, salida, lectura de caché, escritura de caché
    ("claude-opus-5-5", Decimal("4.00"), Decimal("20.00"), Decimal("0.20"), Decimal("5.00")),
    ("claude-sonnet-5-5", Decimal("2.00"), Decimal("10.00"), Decimal("0.20"), Decimal("2.50")),
    ("claude-haiku-5-5", Decimal("0.10"), Decimal("0.50"), Decimal("0.01"), Decimal("0.125")),
]

# Presupuestos de partida (USD). Prudentes para empezar: se ajustan desde Admin.
BUDGETS = [
    # scope, scope_id, diario, mensual
    ("global", "", Decimal("25"), Decimal("300")),
    ("user", "", Decimal("5"), None),  # cada persona
    ("service", "proposal_generation", Decimal("10"), Decimal("150")),
]

# Minutos que tardaría una persona en cada tarea (Capítulo 11, ROI). Estimaciones
# de partida para que el informe de ROI tenga sentido desde el primer día.
HUMAN_BASELINES = [
    ("document_analysis", "Analizar un pliego y decidir GO/NO-GO", 180),
    ("document_enrichment", "Leer y catalogar un documento", 10),
    ("proposal_generation", "Redactar el primer borrador de una propuesta", 480),
    ("chat_rag", "Buscar una respuesta en la documentación", 15),
]

PROMPT_SEEDS_DIR = Path(__file__).parent / "prompt_seeds"


def run_seeds() -> dict[str, int]:
    created = {"apps": 0, "roles": 0, "llm_services": 0, "llm_pricing": 0, "service_lines": 0,
               "proposal_templates": 0, "prompts": 0, "budgets": 0, "human_baselines": 0}

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

    for service_type, model, fallback, max_tokens, effort, prompt_name, description in LLM_SERVICES:
        config = db.session.get(LLMServiceConfig, service_type)
        if config is None:
            db.session.add(
                LLMServiceConfig(
                    service_type=service_type,
                    provider="anthropic",
                    model_name=model,
                    fallback_provider="anthropic" if fallback else None,
                    fallback_model=fallback,
                    max_tokens=max_tokens,
                    effort=effort,
                    prompt_name=prompt_name,
                    description=description,
                )
            )
            created["llm_services"] += 1
        else:
            # Filas creadas en fases anteriores: solo se rellenan los campos nuevos vacíos
            for field, value in (("effort", effort), ("prompt_name", prompt_name), ("description", description)):
                if getattr(config, field) is None:
                    setattr(config, field, value)

    for model, input_price, output_price, cache_read, cache_write in LLM_PRICING:
        price = db.session.get(LLMModelPricing, ("anthropic", model, PRICING_DATE))
        if price is None:
            db.session.add(
                LLMModelPricing(
                    provider="anthropic",
                    model_name=model,
                    effective_date=PRICING_DATE,
                    input_usd_per_mtok=input_price,
                    output_usd_per_mtok=output_price,
                    cache_read_usd_per_mtok=cache_read,
                    cache_write_usd_per_mtok=cache_write,
                )
            )
            created["llm_pricing"] += 1
        elif price.cache_read_usd_per_mtok is None and price.cache_write_usd_per_mtok is None:
            price.cache_read_usd_per_mtok, price.cache_write_usd_per_mtok = cache_read, cache_write

    created["prompts"] = _seed_prompts()

    for scope, scope_id, daily, monthly in BUDGETS:
        if db.session.scalar(db.select(BudgetConfig.id).filter_by(scope=scope, scope_id=scope_id)) is None:
            db.session.add(BudgetConfig(scope=scope, scope_id=scope_id, daily_limit_usd=daily,
                                        monthly_limit_usd=monthly))
            created["budgets"] += 1

    for service_type, task_name, minutes in HUMAN_BASELINES:
        if db.session.get(HumanBaselineConfig, service_type) is None:
            db.session.add(HumanBaselineConfig(service_type=service_type, task_name=task_name,
                                               human_time_minutes=minutes))
            created["human_baselines"] += 1

    existing_lines = set(db.session.scalars(db.select(ServiceLine.code)))
    for code, name, cpv_prefixes, keywords in SERVICE_LINES:
        if code not in existing_lines:
            db.session.add(ServiceLine(code=code, name=name, cpv_prefixes=cpv_prefixes, keywords=keywords))
            created["service_lines"] += 1

    existing_templates = set(db.session.scalars(db.select(ProposalTemplate.name)))
    for name, proposal_type, sections in PROPOSAL_TEMPLATES:
        if name not in existing_templates:
            db.session.add(ProposalTemplate(
                name=name, proposal_type=proposal_type,
                sections=[{"key": k, "title": t, "order": i} for i, (k, t) in enumerate(sections)],
            ))
            created["proposal_templates"] += 1

    db.session.commit()
    log.info("seeds_applied", **created)
    return created


def _seed_prompts() -> int:
    """Primera versión de cada prompt. Si ya hay alguna versión, no se toca."""
    from .ai import prompts

    services = {prompt: service for service, *_, prompt, _desc in LLM_SERVICES if prompt}
    created = 0
    for system_file in sorted(PROMPT_SEEDS_DIR.glob("*.system.md")):
        name = system_file.name.removesuffix(".system.md")
        if db.session.scalar(db.select(Prompt.id).filter_by(name=name).limit(1)) is not None:
            continue
        user_file = PROMPT_SEEDS_DIR / f"{name}.user.md"
        prompts.publish(name, system_file.read_text(encoding="utf-8").strip(),
                        user_file.read_text(encoding="utf-8").strip() if user_file.exists() else None,
                        author_id=None, notes="Versión inicial", service_type=services.get(name))
        created += 1
    return created
