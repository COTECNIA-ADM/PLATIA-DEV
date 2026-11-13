"""Comprobaciones de un flujo de n8n antes de publicarlo en el portal (ADR-020, fase L3).

Se leen los nodos del flujo y se devuelve una lista de avisos. Los de nivel ``error``
impiden enviar la ficha a revisión y publicarla; los ``warning`` se enseñan, pero no
bloquean. Las mismas reglas se aplican en los tests a las plantillas de ``automations/``.

Nunca se devuelve el texto encontrado (podría ser un secreto): solo el nodo y la regla.

Hay dos clases de flujo:
- ``launch``: se lanza desde el catálogo; empieza por un Webhook y responde a ``callback_url``.
- ``inbound``: recoge algo de fuera (por ejemplo, el formulario web del caso P2) y lo entrega en
  ``/api/leads/inbound`` con la clave de integración. No pasa por el catálogo.
- ``error``: el flujo de errores común (fase L4). Empieza por un Error Trigger y entrega el
  fallo en ``/api/automation/incidents/inbound`` con la clave de integración.
"""
import re

WEBHOOK = "n8n-nodes-base.webhook"
HTTP_REQUEST = "n8n-nodes-base.httpRequest"

# Ya excluidos con NODES_EXCLUDE en la capa de Docker; se comprueban por si un flujo viene
# de otra instalación.
FORBIDDEN_NODES = {
    "n8n-nodes-base.executeCommand": "ejecuta órdenes en el servidor",
    "n8n-nodes-base.localFileTrigger": "lee ficheros del servidor",
    "n8n-nodes-base.readWriteFile": "lee o escribe ficheros del servidor",
    "n8n-nodes-base.ssh": "abre conexiones SSH",
    "n8n-nodes-base.git": "maneja repositorios en el servidor",
}
# La IA de un flujo pasa por PLATIA o por el gateway corporativo (ADR-019), nunca directa
AI_NODE_PREFIXES = ("@n8n/n8n-nodes-langchain.lmChat", "@n8n/n8n-nodes-langchain.lm",
                    "@n8n/n8n-nodes-langchain.openAi", "@n8n/n8n-nodes-langchain.anthropic",
                    "@n8n/n8n-nodes-langchain.googleGemini", "@n8n/n8n-nodes-langchain.mistral",
                    "@n8n/n8n-nodes-langchain.embeddings")
AI_NODES_ALLOWED = set()  # el nodo del gateway llegará con L4
AI_HOSTS = ("api.anthropic.com", "api.openai.com", "generativelanguage.googleapis.com",
            "api.mistral.ai", "api.cohere.ai", "openai.azure.com")
SECRET_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"\bplgw-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abpr]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}"),
)
INPUT_REF = re.compile(r"body\.input\.([A-Za-z_][A-Za-z0-9_]*)|body\.input\[['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\]")


def _issue(code: str, level: str, message: str, node: str | None = None) -> dict:
    return {"code": code, "level": level, "message": message, "node": node}


def _strings(value):
    """Todos los textos dentro de los parámetros de un nodo."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def input_names(raw: dict) -> list[str]:
    """Datos de entrada que usa el flujo (``$json.body.input.<nombre>``)."""
    names = set()
    for node in raw.get("nodes") or []:
        for text in _strings(node.get("parameters") or {}):
            for a, b in INPUT_REF.findall(text):
                names.add(a or b)
    return sorted(names)


INBOUND_PATH = "/api/leads/inbound"
INCIDENTS_PATH = "/api/automation/incidents/inbound"
ERROR_TRIGGER = "n8n-nodes-base.errorTrigger"


def _header_auth(params: dict) -> bool:
    return params.get("authentication") == "genericCredentialType" and params.get("genericAuthType") == "httpHeaderAuth"


def _inbound_checks(nodes: list[dict], path: str = INBOUND_PATH) -> list[dict]:
    issues = []
    targets = [n for n in nodes if n.get("type") == HTTP_REQUEST
               and path in str((n.get("parameters") or {}).get("url") or "")]
    if not targets:
        issues.append(_issue("inbound_target", "error",
                             f"El flujo no entrega nada a PLATIA: falta un HTTP Request a «{path}»."))
    for node in targets:
        if not _header_auth(node.get("parameters") or {}):
            issues.append(_issue("inbound_auth", "error",
                                 "La entrega a PLATIA debe llevar la clave de integración («Header Auth»).",
                                 node.get("name")))
    return issues


def _launch_checks(nodes: list[dict]) -> list[dict]:
    issues: list[dict] = []

    hooks = [n for n in nodes if n.get("type") == WEBHOOK]
    post_hooks = [n for n in hooks if (n.get("parameters") or {}).get("httpMethod") == "POST"]
    if not post_hooks:
        issues.append(_issue("webhook_post", "error",
                             "El flujo debe empezar por un nodo Webhook con método POST."))
    for hook in post_hooks:
        if (hook.get("parameters") or {}).get("authentication") != "headerAuth":
            issues.append(_issue("webhook_auth", "error",
                                 "El Webhook debe pedir la clave de PLATIA (autenticación «Header Auth»).",
                                 hook.get("name")))
    if len(hooks) > 1:
        issues.append(_issue("webhook_many", "warning",
                             "Hay más de un Webhook: PLATIA llama al primero que acepta POST."))

    callbacks = []
    for node in nodes:
        if node.get("type") != HTTP_REQUEST:
            continue
        params = node.get("parameters") or {}
        if "callback_url" in str(params.get("url") or ""):
            callbacks.append(node)
            if not _header_auth(params):
                issues.append(_issue("callback_auth", "error",
                                     "La respuesta a PLATIA debe llevar la clave de integración («Header Auth»).",
                                     node.get("name")))
    if not callbacks:
        issues.append(_issue("callback", "error",
                             "El flujo no responde a PLATIA: falta un HTTP Request a «callback_url».",))
    return issues


def run_checks(raw: dict, fields: list[dict] | None = None, kind: str = "launch") -> list[dict]:
    nodes = [n for n in raw.get("nodes") or [] if not n.get("disabled")]
    if kind == "inbound":
        issues = _inbound_checks(nodes)
    elif kind == "error":
        issues = _inbound_checks(nodes, INCIDENTS_PATH)
        if not any(n.get("type") == ERROR_TRIGGER for n in nodes):
            issues.append(_issue("error_trigger", "error", "El flujo de errores debe empezar por un «Error Trigger»."))
    else:
        issues = _launch_checks(nodes)

    for node in nodes:
        ntype = node.get("type") or ""
        name = node.get("name")
        if ntype in FORBIDDEN_NODES:
            issues.append(_issue("forbidden_node", "error",
                                 f"Nodo no permitido: {FORBIDDEN_NODES[ntype]}.", name))
        if ntype.startswith(AI_NODE_PREFIXES) and ntype not in AI_NODES_ALLOWED:
            issues.append(_issue("direct_ai", "error",
                                 "La IA no se llama directamente: pasa por PLATIA o por el gateway.", name))
        texts = list(_strings(node.get("parameters") or {}))
        if any(host in text for text in texts for host in AI_HOSTS):
            issues.append(_issue("direct_ai", "error",
                                 "El nodo llama a un proveedor de IA directamente: usa el gateway.", name))
        if any(p.search(text) for text in texts for p in SECRET_PATTERNS):
            issues.append(_issue("secret", "error",
                                 "Parece que hay una clave escrita en el nodo: guárdala en una credencial.", name))

    if not raw.get("active"):
        issues.append(_issue("inactive", "warning", "El flujo no está activo en n8n: no se podrá lanzar."))
    if kind != "error" and not (raw.get("settings") or {}).get("errorWorkflow"):
        issues.append(_issue("error_workflow", "warning",
                             "El flujo no tiene flujo de errores: si falla, PLATIA se enterará por el plazo."))

    if fields is not None:
        declared = {f.get("name") for f in fields}
        used = set(input_names(raw))
        for name in sorted(used - declared):
            issues.append(_issue("input_undeclared", "warning",
                                 f"El flujo usa el dato «{name}», pero la ficha no lo pide."))
        for name in sorted(declared - used):
            issues.append(_issue("input_unused", "warning", f"La ficha pide «{name}», pero el flujo no lo usa."))
    return issues


def has_errors(issues: list[dict]) -> bool:
    return any(i["level"] == "error" for i in issues)


