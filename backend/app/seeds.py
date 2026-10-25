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
from .models import (AgentDefinition, App, AppRole, BudgetConfig, HumanBaselineConfig, IntentPattern,
                     LLMModelPricing, LLMServiceConfig, Prompt, ProposalTemplate, ServiceLine)

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
COMPETITORS_RW = ["read", "write", "delete"]
ROLES = {
    "operations": {
        "admin": ("Administrador de operaciones", True, {}),
        "manager": ("Responsable comercial", False, {
            "clients": ["read", "write", "delete"],
            "opportunities": ["read", "write", "delete", "manage", "export"],
            "documents": ["read", "write", "upload", "delete", "manage"],
            "proposals": ["read", "write", "delete", "manage", "approve", "send"],
            "templates": RW, "portfolio": RW, "talent": ["read", "write", "delete"],
            "alerts": RW, "notifications": R, "reports": ["read", "generate"], "copilot": RW,
            "ai_modules_access": AI_ALL,
        }),
        # El analista solo modifica lo que tiene asignado (autorización por objeto)
        "analyst": ("Analista", False, {
            "clients": R, "opportunities": RW, "documents": ["read", "upload", "write"],
            "proposals": RW, "templates": R, "portfolio": R, "talent": R, "alerts": R,
            "notifications": R, "reports": R, "copilot": RW,
            "ai_modules_access": ["document_analyzer", "copilot_chat"],
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
                                                   "copilot": RW, "competitors": COMPETITORS_RW,
                                                   "ai_modules_access": ["copilot_chat", "analytics_assistant"]}),
        "viewer": ("Consulta", False, {"dashboards": R, "reports": R, "competitors": R, "ai_modules_access": []}),
    },
    "admin": {
        "superadmin": ("Superadministrador", True, {}),
        "admin": ("Administrador", False, {
            "users": RW, "roles": RW, "llm_config": RW, "prompts": RW, "audit": R, "health": R,
            "tasks": RW, "search": RW, "agents": RW,
        }),
        "auditor": ("Auditor", False, {
            "users": R, "roles": R, "llm_config": R, "prompts": R, "audit": R, "health": R,
            "tasks": R, "search": R, "agents": R,
        }),
    },
    "security": {
        "security_admin": ("Responsable de seguridad", True, {}),
        "security_analyst": ("Analista de seguridad", False, {"audit": R, "alerts": RW, "guardrails": R}),
        "viewer": ("Consulta", False, {"audit": R, "alerts": R}),
    },
}

# Módulos de permiso que llegaron en fases posteriores: se añaden a los roles de
# serie que ya existían en la BD (solo si el rol no tiene ese módulo; no se
# tocan los permisos que un administrador haya cambiado).
LATER_MODULES = {"search", "copilot", "agents", "competitors"}

# Patrones de la primera capa del clasificador (Capítulo 13). Redacción propia.
# Se aplican sobre el texto en minúsculas y sin tildes. Editables desde Admin.
_SEARCH_NOUNS = r"(oportunidad|oportunidades|contrato|contratos|licitacion|licitaciones|concurso|concursos|expediente|expedientes)"
INTENT_PATTERNS = [
    # intención, subtipo, prioridad, patrón, descripción
    ("OFF_TOPIC", "", 10, r"\b(tiempo|clima|lluvia|temperatura)\b.{0,30}\b(hoy|manana|hace|hara|fin de semana)\b",
     "El tiempo"),
    ("OFF_TOPIC", "", 10, r"\b(futbol|liga|partido|deportes?|pelicula|series?|receta|chiste|horoscopo|loteria)\b",
     "Ocio y temas generales"),
    ("OFF_TOPIC", "", 10, r"^(hola|buenas|buenos dias|buenas tardes|gracias|adios|hasta luego)[\s!.,]*$",
     "Saludos sin petición"),
    ("WORKFLOW", "generate_proposal", 20,
     r"\b(genera|generame|crea|creame|elabora|redacta|redactame|prepara|preparame|escribe|escribeme)\b.{0,60}\b(propuesta|oferta|memoria tecnica|borrador)\b",
     "Redactar una propuesta"),
    ("WORKFLOW", "analyze_opportunity", 20,
     r"\b(nos conviene|merece la pena|deberiamos presentarnos|nos presentamos|encaja con nuestro|go.?no.?go)\b",
     "Decidir si presentarse"),
    ("WORKFLOW", "analyze_opportunity", 25,
     r"\b(analiza|evalua|valora|estudia)\b.{0,40}\b(esta|este|la|el)\b.{0,20}\b(oportunidad|licitacion|concurso|expediente)\b",
     "Analizar una oportunidad concreta"),
    ("WORKFLOW", "analyze_document", 25, r"\b(analiza|revisa|evalua)\b.{0,40}\b(este|el|ese)\b.{0,15}\b(pliego|documento)\b",
     "Analizar un documento concreto"),
    ("WORKFLOW", "summarize", 30, r"\b(resumen ejecutivo|informe ejecutivo)\b", "Resumen ejecutivo"),
    ("AGENT_TOOLS", "search_opportunities", 40,
     r"\b(busca|buscame|encuentra|encuentrame|muestra|muestrame|lista|listame|dame|ensename|filtra|hay)\b.{0,50}\b" + _SEARCH_NOUNS + r"\b",
     "Orden de buscar + oportunidades"),
    ("AGENT_TOOLS", "search_opportunities", 40,
     r"\b" + _SEARCH_NOUNS + r"\b.{0,50}\b(presupuesto|importe|valor|plazo|publicad|abiert|vigente|cpv|cierr|venc|mas de|menos de|entre)",
     "Oportunidades + atributo filtrable"),
    ("AGENT_TOOLS", "search_opportunities", 45,
     r"\b(mas de|menos de|superior(es)? a|inferior(es)? a|entre|hasta)\s+[\d.,]+\s*(k|mil|millones?|euros|eur|€)",
     "Importe con cifra"),
    ("AGENT_TOOLS", "search_opportunities", 45, r"\bcpv\b|\b\d{8}(-\d)?\b", "Código CPV"),
    ("AGENT_TOOLS", "search_opportunities", 45,
     r"\b(publicad[oa]s|que (cierran|vencen|caducan)|fecha limite)\b", "Fechas de publicación o plazo"),
    ("AGENT_TOOLS", "search_documents", 50,
     r"\b(busca|encuentra|localiza|donde esta|donde estan)\b.{0,40}\b(documento|documentos|pliego|pliegos|fichero|archivo|anexo)\b",
     "Localizar un documento"),
    ("AGENT_TOOLS", "search_clients", 50,
     r"\b(busca|encuentra|localiza|datos de|ficha de)\b.{0,30}\b(cliente|clientes|empresa)\b", "Localizar un cliente"),
    ("CHAT_RAG", "rag_query", 60,
     r"\b(explica|explicame|que dice|que establece|que exige|que requisitos|cuales son|cual es|por que|resume|resumeme|compara|diferencias?)\b",
     "Pregunta o explicación"),
    ("CHAT_RAG", "rag_query", 60, r"\b(segun|en el|del|de la)\s+(pliego|documento|contrato|propuesta|acta)\b",
     "Referencia a un documento"),
    ("CHAT_RAG", "rag_query", 60,
     r"\b(hemos (ganado|presentado|hecho|trabajado|perdido)|nuestr[oa]s? (propuestas?|experiencia|proyectos?|clientes)|historico|casos similares|antecedentes|que hicimos)\b",
     "Experiencia propia"),
]

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
    ("intent_classification", "claude-haiku-5-5", "claude-sonnet-5-5", 1000, "low", "intent.classify",
     "Segunda capa del clasificador de intención del asistente"),
    # Copiloto y agentes (fase 5c). Cada agente indica su prompt; aquí va el del copiloto.
    ("agent_copilot", "claude-sonnet-5-5", "claude-haiku-5-5", 8000, "low", "agent.copiloto",
     "Copiloto y agentes con herramientas (un turno del bucle)"),
    ("chat_summary", "claude-haiku-5-5", "claude-sonnet-5-5", 2000, "low", "chat.summary",
     "Resumen de los turnos antiguos de una conversación"),
    ("memory_extraction", "claude-haiku-5-5", None, 1500, "low", "memory.extract",
     "Qué recordar de cada persona entre conversaciones"),
    ("cv_tailoring", "claude-sonnet-5-5", "claude-haiku-5-5", 6000, "low", "cv.tailor",
     "CV adaptado a una oportunidad"),
    ("proposal_deck", "claude-haiku-5-5", "claude-sonnet-5-5", 4000, "low", "proposal.deck",
     "Guion de la presentación PPTX de una propuesta"),
    # Inteligencia comercial (fase 9a)
    ("analytics_qa", "claude-sonnet-5-5", "claude-haiku-5-5", 6000, "low", "analytics.qa",
     "Preguntas en lenguaje natural sobre el cuadro de mando"),
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
    ("cv_tailoring", "Adaptar un CV a una propuesta", 45),
    ("analytics_qa", "Sacar una cifra del cuadro de mando y explicarla", 20),
]

# Agentes de partida (Capítulo 15). Se editan y prueban en Admin -> Agentes.
# slug, nombre, descripción, tipo, máx. iteraciones, máx. herramientas, herramientas [(nombre, nivel)]
_READ = ["search_opportunities", "get_opportunity", "search_documents", "get_document", "search_clients",
         "search_profiles", "get_proposal"]
AGENTS = [
    ("copiloto", "Copiloto", "Asistente general: busca, responde con los datos de la plataforma y propone acciones.",
     "conversational", 10, 15,
     [(t, "auto") for t in _READ] + [(t, "approve") for t in ("analyze_opportunity", "create_proposal",
                                                               "generate_proposal", "generate_cv",
                                                               "export_proposal")],
     [{"input": "¿Qué oportunidades abiertas de ciberseguridad tenemos?", "expect_tools": ["search_opportunities"]}]),
    ("analista_documental", "Analista documental",
     "Estudia pliegos y oportunidades: requisitos, riesgos y decisión GO/NO-GO.", "specialist", 8, 12,
     [("search_documents", "auto"), ("get_document", "auto"), ("get_opportunity", "auto"),
      ("search_opportunities", "auto"), ("analyze_opportunity", "approve"), ("analyze_document", "approve")],
     [{"input": "¿Qué solvencia técnica pide el pliego @doc:1?", "expect_tools": ["search_documents"]}]),
    ("preparador_propuestas", "Preparador de propuestas",
     "Monta la propuesta de una oportunidad: plantilla, redacción, equipo con CV a medida y paquete final.",
     "specialist", 10, 15,
     [("get_opportunity", "auto"), ("search_documents", "auto"), ("search_profiles", "auto"),
      ("get_proposal", "auto"), ("list_proposal_templates", "auto"), ("create_proposal", "approve"),
      ("generate_proposal", "approve"), ("generate_cv", "approve"), ("export_proposal", "approve")],
     [{"input": "Prepara la propuesta para la oportunidad 1", "expect_tools": ["get_opportunity"]}]),
]

PROMPT_SEEDS_DIR = Path(__file__).parent / "prompt_seeds"


def run_seeds() -> dict[str, int]:
    created = {"apps": 0, "roles": 0, "llm_services": 0, "llm_pricing": 0, "service_lines": 0,
               "proposal_templates": 0, "prompts": 0, "budgets": 0, "human_baselines": 0, "intent_patterns": 0,
               "agents": 0}

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
            else:
                _add_later_modules(app.id, code, permissions)

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
    created["intent_patterns"] = _seed_intent_patterns()
    created["agents"] = _seed_agents()

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


def _add_later_modules(app_id: int, code: str, permissions: dict) -> None:
    role = db.session.scalar(db.select(AppRole).filter_by(app_id=app_id, code=code))
    current = dict(role.permissions or {})
    missing = {m: a for m, a in permissions.items() if m in LATER_MODULES and m not in current}
    if missing:
        role.permissions = {**current, **missing}


def _seed_intent_patterns() -> int:
    existing = {(p.intent, p.pattern) for p in db.session.scalars(db.select(IntentPattern))}
    created = 0
    for intent, subtype, priority, pattern, description in INTENT_PATTERNS:
        if (intent, pattern) not in existing:
            db.session.add(IntentPattern(intent=intent, subtype=subtype, priority=priority, pattern=pattern,
                                         description=description))
            created += 1
    return created


def _seed_agents() -> int:
    from .agents import definitions

    existing = set(db.session.scalars(db.select(AgentDefinition.slug)))
    created = 0
    for slug, name, description, agent_type, max_iterations, max_tool_calls, tools, test_cases in AGENTS:
        if slug in existing:
            continue
        agent = AgentDefinition(slug=slug, name=name, description=description, status="active",
                                agent_type=agent_type, llm_service_type="agent_copilot", prompt_name=f"agent.{slug}",
                                max_iterations=max_iterations, max_tool_calls=max_tool_calls, test_cases=test_cases)
        db.session.add(agent)
        db.session.flush()
        definitions.set_tools(agent, [{"tool_name": t, "approval_level": level} for t, level in tools])
        definitions.save_version(agent, None, notes="Versión inicial")
        created += 1
    return created


# Versiones iniciales que se han mejorado después. Si la activa de una instalación es
# exactamente una de estas (nadie la ha editado), se publica la versión nueva del fichero.
# Una versión editada desde Admin no se toca nunca.
SUPERSEDED_SEED_HASHES = {
    # Fase 7c: la conversación y la pregunta van en etiquetas y se declaran como datos
    "rag.query_rewrite": {"75224525ccec0e1d7138caea0bc272fd9d58b6071cdd0bff14f426fb1a11e9bc"},
}


def _seed_prompts() -> int:
    """Primera versión de cada prompt. Si ya hay alguna versión, no se toca, salvo que la
    activa sea una versión inicial superada y sin editar (``SUPERSEDED_SEED_HASHES``)."""
    from .ai import prompts

    services = {prompt: service for service, *_, prompt, _desc in LLM_SERVICES if prompt}
    created = 0
    for system_file in sorted(PROMPT_SEEDS_DIR.glob("*.system.md")):
        name = system_file.name.removesuffix(".system.md")
        user_file = PROMPT_SEEDS_DIR / f"{name}.user.md"
        system = system_file.read_text(encoding="utf-8").strip()
        user = user_file.read_text(encoding="utf-8").strip() if user_file.exists() else None
        if db.session.scalar(db.select(Prompt.id).filter_by(name=name).limit(1)) is not None:
            active = db.session.scalar(db.select(Prompt).filter_by(name=name, is_active=True))
            if active is not None and active.content_hash in SUPERSEDED_SEED_HASHES.get(name, set()):
                prompts.publish(name, system, user, author_id=None,
                                notes="Actualización de la versión inicial (refuerzo contra la inyección)")
                created += 1
            continue
        prompts.publish(name, system, user, author_id=None, notes="Versión inicial",
                        service_type=services.get(name) or ("agent_copilot" if name.startswith("agent.") else None))
        created += 1
    return created
