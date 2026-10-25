"""Revisión de los prompts contra la inyección indirecta (fase 7c).

Comprueba lo que se puede leer en el texto de un prompt:

- Sin variables en el prompt de sistema (se cachea y no debe cambiar).
- El texto que viene de fuera (documentos, conversación, respuestas, datos) va dentro
  de una etiqueta propia en la plantilla de usuario, por ejemplo ``<document>``.
- Si recibe texto de fuera, el prompt de sistema dice que es un dato y no una orden.

Se aplica a las versiones iniciales (tests) y a las activas en la base de datos
(``flask eval-ai --suite prompts``), por si una edición desde Admin quita las defensas.
"""
import re

from ..ai.prompts import VARIABLE

# Variables con texto que no escribe la plataforma: documentos, conversaciones, perfiles…
UNTRUSTED = {"text", "sources", "conversation", "content", "answer", "data", "opportunity", "profile",
             "analysis", "previous_sections", "instructions", "query", "question", "portfolio", "memories",
             "known", "previous_summary", "conversation_summary", "references", "screen", "context"}
# Las que pueden ser largas: tienen que ir dentro de una etiqueta
MUST_BE_WRAPPED = {"text", "sources", "conversation", "content", "answer", "data", "opportunity", "profile",
                   "analysis", "previous_sections", "instructions", "query"}
DATA_CLAUSE = re.compile(
    r"\b(dato|datos|material)\b.{0,80}\b(no|nunca)\b.{0,40}instrucci|\b(no|nunca)\s+sigas\s+instrucciones",
    re.IGNORECASE | re.DOTALL)


def _wrapped(template: str, var: str) -> bool:
    """¿Está ``{{var}}`` solo entre una etiqueta de apertura y su cierre?"""
    pattern = r"<([a-z_]+)[^<>]*>\s*\{\{\s*" + re.escape(var) + r"\s*\}\}\s*</\1>"
    return re.search(pattern, template) is not None


def lint(name: str, system: str, user: str | None) -> list[str]:
    problems = []
    if VARIABLE.search(system or ""):
        problems.append("el prompt de sistema tiene variables (van en la plantilla de usuario)")
    variables = {m.group(1) for m in VARIABLE.finditer(user or "")}
    for var in sorted(variables & MUST_BE_WRAPPED):
        if not _wrapped(user or "", var):
            problems.append(f"{{{{{var}}}}} no va dentro de una etiqueta propia (p. ej. <{var}>…</{var}>)")
    if variables & UNTRUSTED and not DATA_CLAUSE.search(system or ""):
        problems.append("recibe texto de fuera y el sistema no dice que es un dato y no una instrucción")
    return [f"{name}: {p}" for p in problems]
