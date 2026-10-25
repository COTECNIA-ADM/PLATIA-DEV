"""Prompts versionados en base de datos (Capítulo 11).

- Solo hay una versión activa por nombre. Publicar crea una versión nueva y
  archiva la anterior; volver atrás es activar una versión anterior.
- Las variables se escriben ``{{nombre}}``. Se usan llaves dobles para que el
  JSON de ejemplo que lleve un prompt no se confunda con una variable.
- Caché en Redis: 5 minutos, o 30 segundos para los prompts ``agent.*`` (se
  iteran más durante el desarrollo de agentes). Publicar o activar la invalida.
- ``content_hash`` (SHA-256) detecta cambios hechos directamente en la base de
  datos saltándose el versionado: lo revisa una tarea programada.
"""
import hashlib
import json
import re
from dataclasses import dataclass

import structlog

from ..errors import NotFoundError, ValidationError
from ..extensions import db
from ..models import Prompt, utcnow
from ..security.redis_store import get_redis

log = structlog.get_logger(__name__)

VARIABLE = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")
NAME_PATTERN = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")


@dataclass(frozen=True)
class ActivePrompt:
    id: int
    name: str
    version: int
    system_prompt: str
    user_template: str
    content_hash: str

    def render(self, variables: dict) -> tuple[str, str]:
        return render(self.system_prompt, variables), render(self.user_template, variables)


def content_hash(system_prompt: str, user_template: str | None) -> str:
    return hashlib.sha256(f"{system_prompt}\x00{user_template or ''}".encode()).hexdigest()


def variables_of(*templates: str | None) -> set[str]:
    return {m.group(1) for t in templates if t for m in VARIABLE.finditer(t)}


_TEMPLATE_TAG = re.compile(r"<\s*/?\s*([a-z_]+)[^<>]*>", re.IGNORECASE)


def _neutralize_tags(value: str, tags: set[str]) -> str:
    """Un texto de fuera (documento, conversación) no puede cerrar ni abrir las etiquetas
    que delimitan su bloque en la plantilla: «</document>» pasa a «‹/document>»."""
    if not tags or "<" not in value:
        return value
    pattern = re.compile(r"<(\s*/?\s*(?:" + "|".join(sorted(map(re.escape, tags))) + r")\b)", re.IGNORECASE)
    return pattern.sub(r"‹\1", value)


def render(template: str | None, variables: dict) -> str:
    if not template:
        return ""
    missing = variables_of(template) - set(variables)
    if missing:
        raise ValidationError(f"Faltan variables del prompt: {', '.join(sorted(missing))}.")
    tags = {m.group(1).lower() for m in _TEMPLATE_TAG.finditer(template)} | {"system", "instructions"}

    def value(m: re.Match) -> str:
        raw = variables[m.group(1)]
        return _neutralize_tags(str(raw), tags) if raw is not None else ""

    return VARIABLE.sub(value, template)


def _cache_key(name: str) -> str:
    return f"prompt:{name}:active"


def _ttl(name: str) -> int:
    return 30 if name.startswith("agent.") else 300


def invalidate(name: str) -> None:
    try:
        get_redis().delete(_cache_key(name))
    except Exception as exc:  # noqa: BLE001 - sin caché solo se pierde rendimiento
        log.warning("prompt_cache_unavailable", error=str(exc))


def get_active(name: str) -> ActivePrompt:
    try:
        cached = get_redis().get(_cache_key(name))
        if cached:
            return ActivePrompt(**json.loads(cached))
    except Exception as exc:  # noqa: BLE001
        log.warning("prompt_cache_unavailable", error=str(exc))
    row = db.session.scalar(db.select(Prompt).filter_by(name=name, is_active=True))
    if row is None:
        raise NotFoundError(f"No hay ninguna versión activa del prompt '{name}'.")
    active = ActivePrompt(id=row.id, name=row.name, version=row.version, system_prompt=row.system_prompt,
                          user_template=row.user_template or "",
                          content_hash=row.content_hash or content_hash(row.system_prompt, row.user_template))
    try:
        get_redis().setex(_cache_key(name), _ttl(name), json.dumps(active.__dict__))
    except Exception:  # noqa: BLE001
        pass
    return active


def publish(name: str, system_prompt: str, user_template: str | None, *, author_id: int | None,
            notes: str | None = None, service_type: str | None = None, description: str | None = None,
            activate: bool = True) -> Prompt:
    """Crea una versión nueva. Si ``activate``, pasa a ser la activa. No hace commit."""
    if not NAME_PATTERN.match(name):
        raise ValidationError("El nombre del prompt debe tener la forma 'dominio.tarea' en minúsculas.")
    previous = db.session.scalars(db.select(Prompt).filter_by(name=name).order_by(Prompt.version.desc())).first()
    if previous is not None:
        # Las variables que usa el código no pueden desaparecer de una versión nueva
        lost = variables_of(previous.system_prompt, previous.user_template) - \
            variables_of(system_prompt, user_template)
        if lost:
            raise ValidationError(f"La versión nueva ha perdido variables que usa la plataforma: "
                                  f"{', '.join(sorted(lost))}.")
        service_type = service_type or previous.service_type
        description = description or previous.description
    prompt = Prompt(name=name, version=(previous.version + 1) if previous else 1, service_type=service_type,
                    system_prompt=system_prompt, user_template=user_template, description=description,
                    notes=notes, is_active=False, created_by=author_id,
                    content_hash=content_hash(system_prompt, user_template))
    db.session.add(prompt)
    db.session.flush()
    if activate:
        activate_version(prompt)
    return prompt


def activate_version(prompt: Prompt) -> None:
    """Activa una versión y archiva la que estuviera activa. No hace commit."""
    for other in db.session.scalars(db.select(Prompt).filter_by(name=prompt.name, is_active=True)):
        if other.id != prompt.id:
            other.is_active = False
            other.archived_at = utcnow()
    prompt.is_active = True
    prompt.archived_at = None
    invalidate(prompt.name)


def verify_integrity() -> list[dict]:
    """Prompts activos cuyo contenido ya no coincide con su hash registrado."""
    violations = []
    for prompt in db.session.scalars(db.select(Prompt).filter_by(is_active=True)):
        current = content_hash(prompt.system_prompt, prompt.user_template)
        if prompt.content_hash and current != prompt.content_hash:
            violations.append({"name": prompt.name, "version": prompt.version,
                               "stored_hash": prompt.content_hash, "current_hash": current})
    return violations
