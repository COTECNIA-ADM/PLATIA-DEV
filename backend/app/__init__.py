"""Fábrica de la aplicación Flask (Capítulo 7)."""
import time
import uuid

import structlog
from flask import Flask, g, jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix

from .extensions import db, jwt, migrate
from .security import sessions
from .security.headers import apply_security_headers
from .security.redis_store import init_redis
from .logging_config import configure_logging

log = structlog.get_logger("http")


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

    from .errors import register_error_handlers
    from .queue import init_celery

    register_error_handlers(app)

    from . import models  # noqa: F401  (registra las tablas para Alembic)
    from .cli import register_cli

    register_cli(app)

    @app.before_request
    def bind_request_id() -> None:
        # Trazabilidad: cada petición lleva un X-Request-ID (Apéndice B, middleware)
        g.request_id = (request.headers.get("X-Request-ID") or str(uuid.uuid4()))[:64]
        g.request_start = time.perf_counter()
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=g.request_id, path=request.path)

    @app.after_request
    def add_request_id(response):
        response.headers["X-Request-ID"] = g.get("request_id", "")
        if request.path.startswith("/api/") and request.path != "/api/health":
            duration = (time.perf_counter() - g.get("request_start", time.perf_counter())) * 1000
            log.info("request_completed", method=request.method, status=response.status_code,
                     duration_ms=round(duration, 1))
        return apply_security_headers(response)

    from .routes.admin import admin_bp
    from .routes.admin_tasks import admin_tasks_bp
    from .routes.auth import auth_bp
    from .routes.catalog import catalog_bp
    from .routes.clients import clients_bp
    from .routes.documents import documents_bp
    from .routes.health import health_bp
    from .routes.inbox import inbox_bp
    from .routes.opportunities import opportunities_bp
    from .routes.proposals import proposals_bp
    from .routes.talent import talent_bp

    for bp in (health_bp, auth_bp, admin_bp, admin_tasks_bp, clients_bp, opportunities_bp,
               documents_bp, proposals_bp, catalog_bp, talent_bp, inbox_bp):
        app.register_blueprint(bp)

    init_celery(app)
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
