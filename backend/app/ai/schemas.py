"""Esquemas JSON de las respuestas estructuradas (salidas estructuradas de Claude).

El servicio de IA los envía como ``output_config.format``: el modelo devuelve
JSON que cumple el esquema y el backend no tiene que adivinar el formato. Se
evitan las restricciones que las salidas estructuradas no admiten (mínimos,
máximos, longitudes): los rangos se piden en la descripción y se validan aquí.
"""


def _obj(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties,
            "required": required if required is not None else list(properties), "additionalProperties": False}


def _str(description: str = "") -> dict:
    return {"type": "string", "description": description} if description else {"type": "string"}


def _list(items: dict, description: str = "") -> dict:
    out = {"type": "array", "items": items}
    if description:
        out["description"] = description
    return out


def _enum(values: list[str], description: str = "") -> dict:
    out = {"type": "string", "enum": values}
    if description:
        out["description"] = description
    return out


def _num(description: str) -> dict:
    return {"type": "number", "description": description}


ENRICHMENT = _obj({
    "summary": _str("Resumen de 3 a 5 frases en español"),
    "keywords": _list(_str(), "Entre 5 y 12 palabras clave"),
    "doc_type": _enum(["pliego", "contrato", "propuesta", "cv", "acta", "normativa", "certificacion",
                       "presupuesto", "informe", "otro"], "Tipo de documento más probable"),
    "entities": _obj({
        "organizations": _list(_str()),
        "amounts": _list(_str(), "Importes con su moneda, tal como aparecen"),
        "dates": _list(_str(), "Fechas o plazos relevantes"),
        "requirements": _list(_str(), "Requisitos o exigencias explícitas, si las hay"),
    }),
    "language": _str("Código ISO 639-1 del idioma principal"),
})

_SCORE = "Puntuación de 0 a 10"
GO_NO_GO = _obj({
    "verdict": _enum(["GO", "NO_GO", "CONDITIONAL"]),
    "confidence": _num("Confianza en el veredicto, de 0 a 1"),
    "summary": _str("Resumen ejecutivo del análisis, 4 a 6 frases"),
    "scores": _obj({
        "strategic_fit": _num(_SCORE),
        "technical_capability": _num(_SCORE),
        "economic_viability": _num(_SCORE),
        "risk": _num("Nivel de riesgo de 0 (ninguno) a 10 (muy alto)"),
        "competition": _num("Intensidad competitiva esperada de 0 (baja) a 10 (muy alta)"),
    }),
    "requirements": _list(_obj({
        "requirement": _str(),
        "kind": _enum(["mandatory", "desirable"]),
        "meets": _enum(["yes", "partial", "no", "unknown"]),
        "evidence": _str("Por qué se cumple o no, citando el texto si es posible"),
    })),
    "risks": _list(_obj({
        "description": _str(),
        "severity": _enum(["low", "medium", "high"]),
        "mitigation": _str(),
    })),
    "conditions": _list(_str(), "Condiciones para que sea GO (solo si CONDITIONAL)"),
    "next_steps": _list(_str()),
    "missing_information": _list(_str(), "Información que falta para decidir con seguridad"),
})

RAG_ANSWER = _obj({
    "answer": _str("Respuesta en español, en Markdown, con referencias [n] a las fuentes"),
    "sufficient_context": {"type": "boolean",
                           "description": "false si las fuentes no bastan para responder con seguridad"},
    "citations": _list(_obj({
        "source": {"type": "integer", "description": "Número de la fuente citada"},
        "quote": _str("Frase literal y breve de la fuente que respalda la respuesta"),
    })),
})

QUERY_REWRITE = _obj({
    "queries": _list(_str(), "Entre 1 y 3 consultas de búsqueda autónomas"),
})

RAG_EVALUATION = _obj({
    "faithfulness": _num("De 0 a 1: cuánto de la respuesta está respaldado por las fuentes"),
    "relevance": _num("De 0 a 1: cuánto responde a la pregunta"),
    "completeness": _num("De 0 a 1: si cubre todo lo que las fuentes permiten responder"),
    "hallucination": _num("De 0 a 1: proporción de afirmaciones sin respaldo"),
    "issues": _list(_str()),
})

PROPOSAL_SECTION = _obj({
    "content": _str("Texto de la sección en Markdown, en español"),
    "assumptions": _list(_str(), "Supuestos hechos por falta de información"),
    "sources": _list({"type": "integer"}, "Números de las fuentes usadas"),
})


def clamp(value, low: float = 0.0, high: float = 1.0) -> float | None:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return None
