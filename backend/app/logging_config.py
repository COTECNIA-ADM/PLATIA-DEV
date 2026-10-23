"""Logging estructurado en JSON con request-id (Capítulo 22). Nunca print()."""
import logging
import os

import structlog


def configure_logging() -> None:
    level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    renderer = (
        structlog.processors.JSONRenderer()
        if os.environ.get("LOG_FORMAT", "json") == "json"
        else structlog.dev.ConsoleRenderer()
    )
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
    )
