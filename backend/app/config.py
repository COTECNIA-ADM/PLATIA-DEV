"""Configuración del backend leída de variables de entorno (Apéndice F del libro).

Nunca se escriben secretos en el código: si falta una variable crítica,
el arranque falla con un mensaje claro.
"""
import os
from datetime import timedelta
from urllib.parse import quote_plus

REQUIRED_ENV_VARS = [
    "DB_HOST",
    "DB_USER",
    "DB_PASSWORD",
    "REDIS_HOST",
    "REDIS_PASSWORD",
    "APP_SECRET_KEY",
    "AI_SERVICE_URL",
    "AI_SERVICE_API_KEY",
    "JWT_SECRET_KEY",
    "MFA_ENCRYPTION_KEY",
]


def validate_env() -> None:
    missing = [var for var in REQUIRED_ENV_VARS if not os.environ.get(var)]
    if missing:
        raise RuntimeError(
            f"Faltan variables de entorno obligatorias: {', '.join(missing)}. "
            "Revisa el fichero .env (plantilla en .env.example). Si vienes de una fase "
            "anterior, ejecuta: python scripts/generate_env.py --actualizar"
        )


def _mysql_url(db_name: str) -> str:
    user = quote_plus(os.environ["DB_USER"])
    password = quote_plus(os.environ["DB_PASSWORD"])
    host = os.environ["DB_HOST"]
    port = os.environ.get("DB_PORT", "3306")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{db_name}?charset=utf8mb4"


def redis_url(db_index_var: str, default: str) -> str:
    password = quote_plus(os.environ["REDIS_PASSWORD"])
    host = os.environ["REDIS_HOST"]
    port = os.environ.get("REDIS_PORT", "6379")
    db_index = os.environ.get(db_index_var, default)
    return f"redis://:{password}@{host}:{port}/{db_index}"


class Config:
    """Configuración de producción y desarrollo (contenedores)."""

    TESTING = False

    def __init__(self) -> None:
        validate_env()
        self.SECRET_KEY = os.environ["APP_SECRET_KEY"]

        # Tres esquemas MySQL con multi-bind de SQLAlchemy (Capítulo 5)
        self.SQLALCHEMY_DATABASE_URI = _mysql_url(os.environ.get("DB_NAME_CORE", "platform_core"))
        self.SQLALCHEMY_BINDS = {
            "core": _mysql_url(os.environ.get("DB_NAME_CORE", "platform_core")),
            "operations": _mysql_url(os.environ.get("DB_NAME_OPS", "operations_db")),
            "analytics": _mysql_url(os.environ.get("DB_NAME_ANALYTICS", "analytics_db")),
        }
        self.SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_size": int(os.environ.get("DB_POOL_SIZE", "10")),
            "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", "20")),
            "pool_pre_ping": True,
            "pool_recycle": 1800,
        }
        self.SQLALCHEMY_TRACK_MODIFICATIONS = False

        self.REDIS_URL = redis_url("REDIS_DB_CACHE", "0")
        self.AI_SERVICE_URL = os.environ["AI_SERVICE_URL"].rstrip("/")
        self.AI_SERVICE_API_KEY = os.environ["AI_SERVICE_API_KEY"]
        self.QDRANT_URL = (
            f"http://{os.environ.get('QDRANT_HOST', 'qdrant')}:{os.environ.get('QDRANT_PORT', '6333')}"
        )
        self.QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", "")
        self.HEALTH_TIMEOUT_SECONDS = float(os.environ.get("HEALTH_TIMEOUT_SECONDS", "3"))
        _security_settings(self)


def _security_settings(cfg, env=None) -> None:
    """Seguridad e IAM (Capítulo 6, ADR-009). Valores por defecto del libro."""
    env = os.environ if env is None else env

    def _minutes(var: str, default: str) -> timedelta:
        return timedelta(minutes=int(env.get(var, default)))

    cfg.JWT_SECRET_KEY = env["JWT_SECRET_KEY"]
    cfg.JWT_ACCESS_TOKEN_EXPIRES = _minutes("JWT_ACCESS_MINUTES", "30")
    cfg.JWT_REFRESH_TOKEN_EXPIRES = _minutes("JWT_REFRESH_MINUTES", "480")  # 8 horas
    # El token de acceso viaja en la cabecera Authorization. El de refresco, en
    # una cookie HttpOnly SameSite=Strict limitada a /api/auth (no la lee JavaScript).
    cfg.JWT_TOKEN_LOCATION = ["headers", "cookies"]
    cfg.JWT_REFRESH_COOKIE_NAME = "platia_refresh"
    cfg.JWT_REFRESH_COOKIE_PATH = "/api/auth"
    cfg.JWT_COOKIE_SAMESITE = "Strict"
    cfg.JWT_COOKIE_SECURE = env.get("COOKIE_SECURE", "false").lower() == "true"
    cfg.JWT_COOKIE_CSRF_PROTECT = False  # cubierto por SameSite=Strict (ADR-009)
    cfg.JWT_SESSION_COOKIE = False
    cfg.MFA_ENCRYPTION_KEY = env["MFA_ENCRYPTION_KEY"]
    cfg.MFA_ISSUER = env.get("MFA_ISSUER", "PLATIA")
    cfg.BCRYPT_ROUNDS = int(env.get("BCRYPT_ROUNDS", "12"))
    cfg.PASSWORD_MIN_LENGTH = int(env.get("PASSWORD_MIN_LENGTH", "12"))
    cfg.LOGIN_MAX_FAILURES = int(env.get("LOGIN_MAX_FAILURES", "5"))
    cfg.LOGIN_LOCK_MINUTES = int(env.get("LOGIN_LOCK_MINUTES", "15"))
    cfg.PERMISSIONS_CACHE_SECONDS = int(env.get("PERMISSIONS_CACHE_SECONDS", "300"))
    # Peticiones por minuto: REST, operaciones de IA y login (Capítulo 6)
    cfg.RATE_LIMIT_DEFAULT = int(env.get("RATE_LIMIT_DEFAULT", "30"))
    cfg.RATE_LIMIT_AI = int(env.get("RATE_LIMIT_AI", "10"))
    cfg.RATE_LIMIT_LOGIN = int(env.get("RATE_LIMIT_LOGIN", "5"))


class TestConfig:
    """Configuración para tests unitarios: SQLite en memoria, sin servicios externos."""

    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_BINDS = {"core": "sqlite://", "operations": "sqlite://", "analytics": "sqlite://"}
    SQLALCHEMY_ENGINE_OPTIONS: dict = {}
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REDIS_URL = "redis://localhost:6379/0"
    AI_SERVICE_URL = "http://ai_service:8000"
    AI_SERVICE_API_KEY = "test-key"
    QDRANT_URL = "http://qdrant:6333"
    QDRANT_API_KEY = ""
    HEALTH_TIMEOUT_SECONDS = 0.5

    def __init__(self) -> None:
        # Valores fijos solo para tests; no leen el entorno
        _security_settings(
            self,
            {
                "JWT_SECRET_KEY": "test-jwt-secret-con-longitud-suficiente-32",
                "MFA_ENCRYPTION_KEY": "Y2xhdmUtZGUtdGVzdC1zb2xvLXBhcmEtcHl0ZXN0ISE=",
                "BCRYPT_ROUNDS": "4",  # rápido en tests
            },
        )
