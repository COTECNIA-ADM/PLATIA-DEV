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
        self.CELERY_BROKER_URL = redis_url("REDIS_DB_CELERY", "1")
        _security_settings(self)
        _business_settings(self)
        _ai_settings(self)
        _search_settings(self)


def _business_settings(cfg, env=None) -> None:
    """Backend de negocio y colas (Capítulos 7-9)."""
    env = os.environ if env is None else env
    # Peticiones por minuto y usuario según el tipo de operación (Capítulo 7)
    cfg.RATE_LIMIT_READ = int(env.get("RATE_LIMIT_READ", "60"))
    cfg.RATE_LIMIT_WRITE = int(env.get("RATE_LIMIT_WRITE", "20"))
    cfg.RATE_LIMIT_UPLOAD = int(env.get("RATE_LIMIT_UPLOAD", "10"))
    cfg.RATE_LIMIT_EXPORT = int(env.get("RATE_LIMIT_EXPORT", "5"))
    # Documentos: se guardan en un volumen, nunca con el nombre que envía el usuario
    cfg.DOCUMENT_STORAGE_PATH = env.get("DOCUMENT_STORAGE_PATH", "/data/documents")
    cfg.DOCUMENT_MAX_MB = int(env.get("DOCUMENT_MAX_MB", "100"))
    cfg.MAX_CONTENT_LENGTH = (cfg.DOCUMENT_MAX_MB + 1) * 1024 * 1024
    # Motor de oportunidades y alertas (Capítulo 9)
    cfg.OPPORTUNITY_FEEDS = env.get("OPPORTUNITY_FEEDS", "")  # nombre|url separados por comas
    cfg.FEED_MAX_MB = int(env.get("FEED_MAX_MB", "20"))
    cfg.ALERT_SCORE_THRESHOLD = float(env.get("ALERT_SCORE_THRESHOLD", "7.0"))
    cfg.ALERT_LOOKBACK_HOURS = int(env.get("ALERT_LOOKBACK_HOURS", "48"))
    cfg.DEAL_STALLED_DAYS = int(env.get("DEAL_STALLED_DAYS", "14"))
    cfg.NOTIFICATION_RETENTION_DAYS = int(env.get("NOTIFICATION_RETENTION_DAYS", "90"))
    cfg.AUDIT_ANONYMIZE_DAYS = int(env.get("AUDIT_ANONYMIZE_DAYS", "365"))
    cfg.SESSION_RETENTION_DAYS = int(env.get("SESSION_RETENTION_DAYS", "30"))
    # Umbral de tareas pendientes por cola antes de avisar (Capítulo 8)
    cfg.QUEUE_ALERT_THRESHOLDS = env.get("QUEUE_ALERT_THRESHOLDS", "default=50,ai=20,documents=20,automation=10")
    cfg.TIMEZONE = env.get("TIMEZONE", "Europe/Madrid")
    cfg.CELERY_TASK_TIME_LIMIT = int(env.get("CELERY_TASK_TIME_LIMIT", "600"))


def _ai_settings(cfg, env=None) -> None:
    """Núcleo de IA (Capítulos 10-12). La elección de modelo por tarea está en la BD
    (llm_service_config), no aquí: se cambia desde Admin sin reiniciar."""
    env = os.environ if env is None else env

    def _flag(var: str, default: str) -> bool:
        return env.get(var, default).strip().lower() in ("1", "true", "yes", "si", "sí")

    cfg.AI_ENABLED = _flag("AI_ENABLED", "true")
    cfg.AI_REQUEST_TIMEOUT = float(env.get("AI_REQUEST_TIMEOUT", "180"))
    cfg.AI_AUTO_ENRICH = _flag("AI_AUTO_ENRICH", "true")
    cfg.AI_MAX_THROTTLE_SECONDS = float(env.get("AI_MAX_THROTTLE_SECONDS", "10"))
    cfg.AI_SAMPLE_RETENTION_DAYS = int(env.get("AI_SAMPLE_RETENTION_DAYS", "30"))
    cfg.AI_USD_EUR_RATE = float(env.get("AI_USD_EUR_RATE", "0.92"))
    # RAG (Capítulo 12)
    cfg.RAG_SCORE_THRESHOLD = float(env.get("RAG_SCORE_THRESHOLD", "0.35"))
    cfg.RAG_MAX_CHUNKS = int(env.get("RAG_MAX_CHUNKS", "6"))
    cfg.RAG_QUERY_REWRITE = _flag("RAG_QUERY_REWRITE", "true")
    cfg.RAG_EVAL_SAMPLE_RATE = float(env.get("RAG_EVAL_SAMPLE_RATE", "0.05"))
    # Puntuación semántica de oportunidades (Capítulo 9): similitud -> 0-10
    cfg.SEMANTIC_SCORING = _flag("SEMANTIC_SCORING", "true")
    cfg.SEMANTIC_SIM_LOW = float(env.get("SEMANTIC_SIM_LOW", "0.15"))
    cfg.SEMANTIC_SIM_HIGH = float(env.get("SEMANTIC_SIM_HIGH", "0.65"))
    cfg.OPPORTUNITY_VECTOR_THRESHOLD = float(env.get("OPPORTUNITY_VECTOR_THRESHOLD", "7.0"))
    # Caracteres máximos que se envían al modelo por documento
    cfg.ANALYSIS_MAX_CHARS = int(env.get("ANALYSIS_MAX_CHARS", "150000"))
    cfg.ENRICH_MAX_CHARS = int(env.get("ENRICH_MAX_CHARS", "40000"))
    # Copiloto y agentes (Capítulos 14 y 15)
    cfg.COPILOT_HISTORY_TURNS = int(env.get("COPILOT_HISTORY_TURNS", "10"))  # turnos completos en el contexto
    cfg.COPILOT_SUMMARY_BATCH = int(env.get("COPILOT_SUMMARY_BATCH", "10"))  # mensajes de margen antes de resumir
    cfg.COPILOT_MAX_MESSAGE_CHARS = int(env.get("COPILOT_MAX_MESSAGE_CHARS", "4000"))
    cfg.AGENT_APPROVAL_TTL_MINUTES = int(env.get("AGENT_APPROVAL_TTL_MINUTES", "15"))
    cfg.MEMORY_MAX_PER_USER = int(env.get("MEMORY_MAX_PER_USER", "50"))
    cfg.MEMORY_INJECT = int(env.get("MEMORY_INJECT", "10"))
    cfg.MEMORY_EXTRACT_ENABLED = _flag("MEMORY_EXTRACT_ENABLED", "true")
    cfg.MEMORY_EXTRACT_EVERY = int(env.get("MEMORY_EXTRACT_EVERY", "2"))  # cada N intercambios


def _search_settings(cfg, env=None) -> None:
    """Búsqueda con Meilisearch y clasificador de intención (Capítulo 13)."""
    env = os.environ if env is None else env

    def _flag(var: str, default: str) -> bool:
        return env.get(var, default).strip().lower() in ("1", "true", "yes", "si", "sí")

    cfg.SEARCH_ENABLED = _flag("SEARCH_ENABLED", "true")
    cfg.MEILI_URL = env.get("MEILI_URL", "http://meilisearch:7700").rstrip("/")
    cfg.MEILI_MASTER_KEY = env.get("MEILI_MASTER_KEY", "")
    cfg.MEILI_INDEX_PREFIX = env.get("MEILI_INDEX_PREFIX", "platia_")
    cfg.MEILI_TIMEOUT = float(env.get("MEILI_TIMEOUT", "5"))
    cfg.MEILI_DOCUMENT_TEXT_CHARS = int(env.get("MEILI_DOCUMENT_TEXT_CHARS", "20000"))
    cfg.SEARCH_SQL_FALLBACK = _flag("SEARCH_SQL_FALLBACK", "true")
    cfg.SEARCH_SEMANTIC_RERANK = _flag("SEARCH_SEMANTIC_RERANK", "true")
    cfg.SEARCH_ASSISTANT_SEMANTIC = _flag("SEARCH_ASSISTANT_SEMANTIC", "true")
    cfg.SEARCH_RERANK_CANDIDATES = int(env.get("SEARCH_RERANK_CANDIDATES", "50"))
    cfg.SEARCH_RERANK_WEIGHT = float(env.get("SEARCH_RERANK_WEIGHT", "0.5"))
    cfg.SEARCH_LOG_RETENTION_DAYS = int(env.get("SEARCH_LOG_RETENTION_DAYS", "90"))
    # Buscar mientras se escribe genera más peticiones que una pantalla normal
    cfg.RATE_LIMIT_SEARCH = int(env.get("RATE_LIMIT_SEARCH", "120"))
    # Clasificador de intención: umbral de la capa 1 y confianza mínima de la capa 2
    cfg.INTENT_LAYER1_THRESHOLD = float(env.get("INTENT_LAYER1_THRESHOLD", "0.75"))
    cfg.INTENT_MIN_CONFIDENCE = float(env.get("INTENT_MIN_CONFIDENCE", "0.5"))
    cfg.INTENT_LLM_ENABLED = _flag("INTENT_LLM_ENABLED", "true")


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
        import tempfile

        _business_settings(self, {
            "DOCUMENT_STORAGE_PATH": tempfile.mkdtemp(prefix="platia-docs-"),
            "DOCUMENT_MAX_MB": "2",
            "RATE_LIMIT_WRITE": "200",
            "RATE_LIMIT_READ": "200",
            "RATE_LIMIT_UPLOAD": "50",
        })
        _ai_settings(self, {
            "SEMANTIC_SCORING": "false",  # los tests de IA lo activan con un cliente falso
            "RAG_SCORE_THRESHOLD": "0.05",  # el cliente falso puntúa por palabras en común
            "RAG_EVAL_SAMPLE_RATE": "0",
            "AI_MAX_THROTTLE_SECONDS": "0",
        })
        _search_settings(self, {"MEILI_URL": "http://meilisearch:7700", "MEILI_MASTER_KEY": "test-key",
                                "SEARCH_SEMANTIC_RERANK": "true", "RATE_LIMIT_SEARCH": "500"})
        # Las tareas se ejecutan en línea, sin broker
        self.CELERY_BROKER_URL = "memory://"
        self.CELERY_ALWAYS_EAGER = True
