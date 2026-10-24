"""Errores de dominio y manejadores globales (Capítulo 7).

- Los errores técnicos (404, 405, 500...) se convierten en JSON con un mensaje
  genérico. El detalle va al log, nunca a la respuesta.
- Los errores de negocio se lanzan como excepciones de dominio con un mensaje
  pensado para mostrarse al usuario.
"""
import structlog
from flask import Flask, g, jsonify
from pydantic import ValidationError as PydanticValidationError
from werkzeug.exceptions import HTTPException

log = structlog.get_logger(__name__)


class DomainError(Exception):
    """Error de negocio con un mensaje seguro para el cliente."""

    status_code = 400
    error_type = "domain"

    def __init__(self, message: str, **details):
        super().__init__(message)
        self.message = message
        self.details = details


class ValidationError(DomainError):
    status_code = 422
    error_type = "validation"


class NotFoundError(DomainError):
    status_code = 404
    error_type = "not_found"


class ConflictError(DomainError):
    status_code = 409
    error_type = "conflict"


class ForbiddenError(DomainError):
    status_code = 403
    error_type = "forbidden"


class BusinessRuleError(DomainError):
    """Una regla de negocio impide la operación (p. ej. una transición no permitida)."""

    status_code = 422
    error_type = "business_rule"


GENERIC_MESSAGES = {
    400: "Petición incorrecta.",
    401: "Autenticación requerida.",
    403: "Acceso no autorizado.",
    404: "Recurso no encontrado.",
    405: "Método no permitido.",
    409: "Conflicto con el estado actual del recurso.",
    413: "El fichero es demasiado grande.",
    415: "Tipo de contenido no admitido.",
    422: "Datos no válidos.",
    429: "Demasiadas peticiones. Inténtalo más tarde.",
}


def _pydantic_errors(exc: PydanticValidationError) -> list[dict]:
    # Solo campo y mensaje: nunca el valor recibido (puede contener datos personales)
    return [
        {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
        for err in exc.errors(include_url=False, include_input=False)
    ]


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(DomainError)
    def _domain(exc: DomainError):
        body = {"error": exc.message, "type": exc.error_type}
        if exc.details:
            body["details"] = exc.details
        return jsonify(body), exc.status_code

    @app.errorhandler(PydanticValidationError)
    def _pydantic(exc: PydanticValidationError):
        return jsonify(error="Datos no válidos.", type="validation", fields=_pydantic_errors(exc)), 422

    @app.errorhandler(HTTPException)
    def _http(exc: HTTPException):
        code = exc.code or 500
        if code >= 500:
            log.error("http_error", status=code, error=str(exc))
        return jsonify(error=GENERIC_MESSAGES.get(code, "Error en la petición.")), code

    @app.errorhandler(Exception)
    def _unhandled(exc: Exception):
        from .extensions import db

        db.session.rollback()
        log.exception("unhandled_exception", error_type=type(exc).__name__,
                      request_id=g.get("request_id"))
        return jsonify(error="Error interno del servidor.", request_id=g.get("request_id")), 500
