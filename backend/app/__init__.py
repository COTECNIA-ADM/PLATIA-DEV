"""Fábrica de la aplicación Flask (Capítulo 7)."""
import uuid

import structlog
from flask import Flask, g, request

from .extensions import db, migrate
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
        return response

    from .routes.health import health_bp

    app.register_blueprint(health_bp)
    return app
