"""Guardrails de entrada y salida para el texto libre que llega a la IA (Capítulo 14).

Acciones graduadas: ALLOW (sin problema), SANITIZE (se limpia y se sigue) y
BLOCK (se rechaza). Entrada: longitud y caracteres de control, intentos de
inyección de prompt, peticiones maliciosas y datos personales. Salida:
credenciales, filtración del prompt de sistema y referencias a la
infraestructura interna.

Son una capa más, no la única: el modelo solo recibe el contexto que el
usuario puede ver (filtro de acceso en Qdrant) y no tiene herramientas que
modifiquen datos en esta fase.
"""
import re
import unicodedata
from dataclasses import dataclass, field

from . import pii

ALLOW, SANITIZE, BLOCK = "allow", "sanitize", "block"

# Se comparan con el texto plegado (_fold): minúsculas sin tildes y con los caracteres
# parecidos de otros alfabetos convertidos a latinos. Por eso van sin tildes.
INJECTION_PATTERNS = [re.compile(p, re.IGNORECASE) for p in (
    r"\bignore\s+(?:\w+\s+){0,3}(previous|prior|above|earlier)\s+(instructions|prompts?|rules)",
    r"\bdisregard\s+(all\s+|your\s+|the\s+)*(previous\s+|prior\s+)?(instructions|rules)",
    r"\b(reveal|show|print|repeat)\s+(me\s+)?(your|the)\s+(system\s+)?(prompt|instructions)",
    r"\b(print|repeat|show)\s+(me\s+)?the\s+instructions\s+you\s+were\s+given",
    r"\byou\s+are\s+now\s+(a|an|in)\b",
    r"\b(jailbreak|dan\s+mode|developer\s+mode)\b",
    r"\bact\s+as\s+(an?\s+)?(unrestricted|unfiltered)",
    r"\b(ignora|olvida|no\s+hagas\s+caso\s+(?:a|de))\s+(?:\w+\s+){0,3}(instrucciones|reglas|restricciones)\s+"
    r"(anteriores|previas|que\s+te\s+(han|hayan)\s+(dado|puesto))",
    r"\bolvida\s+(todas\s+)?(tus|las)\s+(instrucciones|reglas|restricciones)",
    r"\b(ignora|no\s+hagas\s+caso\s+(?:a|de))\s+(todas\s+)?tus\s+(instrucciones|reglas|restricciones)",
    r"\b(revela|muestra|repite|ensena|dime)(me|nos)?\s+(tu|tus|el|las)\s+(prompt|mensaje|instrucciones)\s+(de|del)\s+sistema",
    r"\bahora\s+eres\s+(un|una)\b",
    r"\bmodo\s+(desarrollador|sin\s+restricciones)\b",
    r"<\s*/?\s*(system|instructions)\s*>",
)]

MALICIOUS_PATTERNS = [re.compile(p, re.IGNORECASE) for p in (
    r"\b(crea|genera|escribe|programa|write|create|build)\b.{0,40}\b(ransomware|keylogger|malware|troyano|trojan|botnet)\b",
    r"\b(exfiltra|exfiltrate|volcar|dump)\b.{0,40}\b(contrase[nñ]as|passwords|credenciales|credentials|base\s+de\s+datos)\b",
)]

CREDENTIAL_PATTERNS = [re.compile(p) for p in (
    r"sk-ant-[A-Za-z0-9_\-]{10,}",
    r"\bsk-[A-Za-z0-9]{20,}",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"\b(?:mysql|postgres(?:ql)?|redis|mongodb)(?:\+\w+)?://[^\s:@/]*:[^\s@/]+@",
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
    # "contraseña: Abc12345!" sí; "contraseña: mínimo doce caracteres" no
    r"(?i)\b(?:password|passwd|contrase[nñ]a|api[_-]?key|secret)\s*[:=]\s*(?=\S*\d)(?=\S*[A-Za-z])\S{8,}",
)]

INTERNAL_PATTERNS = [re.compile(p) for p in (
    r"/data/documents/\S*",
    r"\b(?:ANTHROPIC_API_KEY|AI_SERVICE_API_KEY|JWT_SECRET_KEY|MFA_ENCRYPTION_KEY|DB_PASSWORD|REDIS_PASSWORD|QDRANT_API_KEY)\b",
    r"https?://(?:ai_service|qdrant|mysql|redis|backend)(?::\d+)?\S*",
)]


@dataclass
class GuardrailResult:
    action: str
    text: str
    reasons: list[str] = field(default_factory=list)
    pii_types: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.action == BLOCK

    @property
    def user_message(self) -> str:
        messages = {
            "empty": "la pregunta está vacía.",
            "too_long": "es demasiado larga (máximo 2.000 caracteres).",
            "prompt_injection": "contiene instrucciones que intentan cambiar el comportamiento del asistente.",
            "malicious_request": "pide algo que la plataforma no puede hacer.",
        }
        return " ".join(messages.get(r, r) for r in self.reasons)


def _normalize(text: str) -> str:
    # Quita caracteres de control (salvo saltos de línea y tabuladores) y normaliza Unicode
    text = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")


# Letras de otros alfabetos que se confunden con las latinas (cirílico y griego)
_CONFUSABLES = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s",
    "ԁ": "d", "һ": "h", "ӏ": "l", "А": "A", "В": "B", "Е": "E", "І": "I", "К": "K", "М": "M", "Н": "H",
    "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X", "α": "a", "ε": "e", "ι": "i", "ο": "o", "ρ": "p",
    "υ": "u", "Α": "A", "Β": "B", "Ε": "E", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P",
    "Τ": "T", "Χ": "X",
})
# Letras sueltas separadas por guiones o puntos: «I-g-n-o-r-e» → «Ignore»
_SPLIT_LETTERS = re.compile(r"(?<=\b\w)[-_.*·](?=\w\b)")


def _fold(text: str) -> str:
    """Forma del texto para buscar patrones (no se usa para lo que se envía al modelo)."""
    text = unicodedata.normalize("NFKD", text.translate(_CONFUSABLES))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return _SPLIT_LETTERS.sub("", text)


def check_input(text: str, max_chars: int = 2000) -> GuardrailResult:
    text = _normalize(text or "").strip()
    if not text:
        return GuardrailResult(BLOCK, "", ["empty"])
    if len(text) > max_chars:
        return GuardrailResult(BLOCK, text[:max_chars], ["too_long"])
    folded = _fold(text)
    if any(p.search(folded) for p in INJECTION_PATTERNS):
        return GuardrailResult(BLOCK, text, ["prompt_injection"])
    if any(p.search(folded) for p in MALICIOUS_PATTERNS):
        return GuardrailResult(BLOCK, text, ["malicious_request"])
    redacted, found = pii.redact(text)
    if found:
        return GuardrailResult(SANITIZE, redacted, ["pii_redacted"], found)
    return GuardrailResult(ALLOW, text)


def _system_prompt_leaked(output: str, system_prompt: str, window: int = 80) -> bool:
    """¿Contiene la respuesta un fragmento literal largo del prompt de sistema?"""
    flat_out = " ".join(output.split()).lower()
    flat_sys = " ".join(system_prompt.split()).lower()
    if len(flat_sys) < window:
        return False
    step = window // 2
    return any(flat_sys[i:i + window] in flat_out for i in range(0, len(flat_sys) - window + 1, step))


def check_output(text: str, system_prompt: str | None = None) -> GuardrailResult:
    if any(p.search(text or "") for p in CREDENTIAL_PATTERNS):
        return GuardrailResult(BLOCK, "", ["credentials"])
    if system_prompt and _system_prompt_leaked(text or "", system_prompt):
        return GuardrailResult(BLOCK, "", ["system_prompt_leak"])
    cleaned = text or ""
    reasons = []
    for pattern in INTERNAL_PATTERNS:
        cleaned, n = pattern.subn("[interno]", cleaned)
        if n:
            reasons.append("internal_reference")
    if reasons:
        return GuardrailResult(SANITIZE, cleaned, sorted(set(reasons)))
    return GuardrailResult(ALLOW, cleaned)
