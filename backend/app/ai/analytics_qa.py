"""«Pregunta a tus datos»: preguntas en lenguaje natural sobre el cuadro de mando (Cap. 23).

El modelo no consulta la base de datos ni ejecuta SQL: recibe un resumen ya
calculado (KPI, comparación con el periodo anterior, embudo, desgloses, mapa de
oportunidad, objetivos y competidores) y responde solo con eso. Son datos
agregados de negocio; no van datos personales (de contactos ni de usuarios).

Pasa por la pasarela (presupuestos, prompt versionado, registro de coste) y por
los guardarraíles de entrada y salida, como el resto de la IA.
"""
import json
import time
import uuid

from ..extensions import db
from ..models import AuditAction, CompetitorProfile
from ..security.audit import audit
from ..services import analytics, market
from . import gateway, guardrails, prompts, roi
from .errors import GuardrailBlockedError
from .rag import check_question

SERVICE_TYPE = "analytics_qa"
MAX_CONTEXT_CHARS = 30000
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "sufficient_data": {"type": "boolean"},
    },
    "required": ["answer", "sufficient_data"],
    "additionalProperties": False,
}


def build_context(months: int, service_line: str | None, sector: str | None) -> str:
    data = analytics.overview(months, service_line=service_line, sector=sector)
    competitors = [
        {"nombre": c.name, "tipo": c.competitor_type, "lineas": c.service_lines, "sectores": c.sectors,
         "precio": c.price_positioning, "fortalezas": c.strengths[:5], "debilidades": c.weaknesses[:5]}
        for c in db.session.scalars(CompetitorProfile.select_active().order_by(CompetitorProfile.name).limit(30))
    ]
    context = {
        "periodo": data["period"], "filtros": data["filters"], "kpis": data["kpis"],
        "periodo_anterior": data["previous"], "objetivos": data["targets"], "embudo": data["funnel"],
        "mensual": data["monthly"], "por_linea": data["by_service_line"], "por_sector": data["by_sector"],
        "clientes_principales": [{"nombre": c["name"], "abiertas": c["open_count"],
                                  "cartera_eur": c["pipeline_eur"], "ganado_eur": c["won_eur"]}
                                 for c in data["top_clients"]],
        "propuestas": data["proposals"],
        "mapa_de_oportunidad": [
            {"sector": c["sector"], "linea": c["service_line_label"], "puntuacion": c["total_score"],
             "subpuntuaciones": c["scores"], "datos": c["data"]} for c in market.top_cells(15)],
        "competidores": competitors,
    }
    text = json.dumps(context, ensure_ascii=False, default=str)
    return text[:MAX_CONTEXT_CHARS]


def ask(question: str, *, user_id: int, months: int = 12, service_line: str | None = None,
        sector: str | None = None) -> dict:
    started = time.monotonic()
    question = check_question(question, user_id)
    correlation_id = str(uuid.uuid4())
    context = build_context(months, service_line, sector)
    result = gateway.run(SERVICE_TYPE, variables={"question": question, "data": context}, user_id=user_id,
                         json_schema=ANSWER_SCHEMA, correlation_id=correlation_id)
    data = result.data if isinstance(result.data, dict) else {"answer": result.text, "sufficient_data": True}
    checked = guardrails.check_output(data.get("answer") or "", prompts.get_active(result.prompt_name).system_prompt)
    if checked.blocked:
        audit(AuditAction.AI_OUTPUT_BLOCKED, "WARNING", user_id=user_id,
              details={"reasons": checked.reasons, "usage_log_id": result.usage_log_id})
        raise GuardrailBlockedError("La respuesta generada no se puede mostrar por seguridad.")
    roi.record(SERVICE_TYPE, subject_type="question", subject_id=None, user_id=user_id,
               correlation_id=correlation_id, duration_seconds=time.monotonic() - started,
               cost_usd=gateway.correlation_cost(correlation_id))
    db.session.commit()
    return {"answer": checked.text, "sufficient_data": bool(data.get("sufficient_data", True)),
            "usage_log_id": result.usage_log_id, "model": result.model, "is_fallback": result.is_fallback,
            "correlation_id": correlation_id}
