"""Cliente Redis compartido por la caché de permisos, la lista de tokens
revocados y el límite de peticiones."""
import redis
from flask import Flask, current_app


def init_redis(app: Flask) -> None:
    if "redis" not in app.extensions:
        app.extensions["redis"] = redis.Redis.from_url(
            app.config["REDIS_URL"], socket_timeout=2, socket_connect_timeout=2
        )


def get_redis() -> redis.Redis:
    return current_app.extensions["redis"]
