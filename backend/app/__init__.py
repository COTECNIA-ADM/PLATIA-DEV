"""Fábrica de la aplicación Flask (Capítulo 7)."""
import uuid

import structlog
from flask import Flask, g, jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix

from .extensions import db, jwt, migrate
from .security import sessions
from .security.headers import apply_security_headers
from .security.redis_store import init_redis
from .logging_config import configure_logging


def create_app(config: object | None = None) -> Flask:
    configure_logging()
    app = Flask(__name__)

    if config is None:
        from .config import Config

        config = Config()
    app.config.from_object(config)

    db.init_app(app)
    migrate.init_app(app, db)
    _init_security(app)

    from . import models  # noqa: F401  (registra las tablas para Alembic)
    from .cli import register_cli

    register_cli(app)

    @app.before_request
    def bind_request_id() -> None:
        # Trazabilidad: cada petición lleva un X-Request-ID (Apéndice B, middleware)
        g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=g.request_id, path=request.path)

    @app.after_request
    def add_request_id(response):
        response.headers["X-Request-ID"] = g.get("request_id", "")
        return apply_security_headers(response)

    from .routes.admin import admin_bp
    from .routes.auth import auth_bp
    from .routes.health import health_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    return app


def _init_security(app: Flask) -> None:
    # Solo Nginx llega al backend: su X-Forwarded-For es la IP real del cliente
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    init_redis(app)
    jwt.init_app(app)

    @jwt.token_in_blocklist_loader
    def _revoked(_header, payload):
        return sessions.is_revoked(payload)

    def _unauthorized(message: str):
        return jsonify(error=message), 401

    jwt.unauthorized_loader(lambda _reason: _unauthorized("Autenticación requerida."))
    jwt.invalid_token_loader(lambda _reason: _unauthorized("Token no válido."))
    jwt.expired_token_loader(lambda _h, _p: _unauthorized("Token caducado."))
    jwt.revoked_token_loader(lambda _h, _p: _unauthorized("Sesión cerrada."))
    jwt.needs_fresh_token_loader(lambda _h, _p: _unauthorized("Vuelve a iniciar sesión."))
