import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    """Read a required environment variable, raising a clear error if missing."""
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set. "
            f"Copy .env.example to .env and fill in all values."
        )
    return val


class BaseConfig:
    # ── Core ───────────────────────────────────────────────────────────────────
    SECRET_KEY = _require("SECRET_KEY")
    PROPAGATE_EXCEPTIONS = True

    # ── SQLAlchemy ─────────────────────────────────────────────────────────────
    SQLALCHEMY_DATABASE_URI = _require("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_size": 10,
        "max_overflow": 20,
    }

    # ── JWT ────────────────────────────────────────────────────────────────────
    JWT_SECRET_KEY = _require("JWT_SECRET_KEY")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        minutes=int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES_MINUTES", "15"))
    )
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(
        days=int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES_DAYS", "30"))
    )
    JWT_TOKEN_LOCATION = ["headers"]
    JWT_HEADER_NAME = "Authorization"
    JWT_HEADER_TYPE = "Bearer"

    # ── Redis ──────────────────────────────────────────────────────────────────
    REDIS_URL = _require("REDIS_URL")

    # ── Celery ─────────────────────────────────────────────────────────────────
    CELERY_BROKER_URL = _require("CELERY_BROKER_URL")
    CELERY_RESULT_BACKEND = _require("CELERY_RESULT_BACKEND")
    CELERY_TASK_SERIALIZER = "json"
    CELERY_RESULT_SERIALIZER = "json"
    CELERY_ACCEPT_CONTENT = ["json"]
    CELERY_TIMEZONE = "UTC"
    CELERY_ENABLE_UTC = True
    CELERYBEAT_SCHEDULE = {
        "max-pain-snapshot-every-5m": {
            "task":     "app.tasks.max_pain_tasks.capture_max_pain_snapshot",
            "schedule": 300,          # every 5 minutes
            "args":     [],
            "kwargs":   {},
        },
        "max-pain-cleanup-daily": {
            "task":     "app.tasks.max_pain_tasks.cleanup_snapshots",
            "schedule": 86400,        # every 24 hours
            "args":     [],
            "kwargs":   {},
        },
    }

    # ── Max Pain snapshot retention ────────────────────────────────────────────
    # Snapshots older than this many days are deleted by the cleanup task.
    MAX_PAIN_RETENTION_DAYS: int = int(os.getenv("MAX_PAIN_RETENTION_DAYS", "90"))

    # ── Rate Limiting (Flask-Limiter 3.x uses RATELIMIT_STORAGE_URI) ───────────
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI") or _require("REDIS_URL")
    RATELIMIT_DEFAULT = "200 per hour"
    RATELIMIT_HEADERS_ENABLED = True

    # ── Razorpay ───────────────────────────────────────────────────────────────
    RAZORPAY_KEY_ID = _require("RAZORPAY_KEY_ID")
    RAZORPAY_KEY_SECRET = _require("RAZORPAY_KEY_SECRET")
    RAZORPAY_WEBHOOK_SECRET = _require("RAZORPAY_WEBHOOK_SECRET")

    # ── Brevo transactional email ──────────────────────────────────────────────
    # BREVO_ENABLED must be the string "true" (case-insensitive) to activate.
    # Never read BREVO_API_KEY via _require() — it is optional in development.
    BREVO_API_KEY      = os.getenv("BREVO_API_KEY", "")
    BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "")
    BREVO_SENDER_NAME  = os.getenv("BREVO_SENDER_NAME", "Stop Hunter Pro")
    BREVO_ENABLED      = os.getenv("BREVO_ENABLED", "false").strip().lower() == "true"

    # ── Dashboard URL (used in email alert links) ─────────────────────────────
    DASHBOARD_URL = os.getenv("DASHBOARD_URL", "")

    # ── OTP ────────────────────────────────────────────────────────────────────
    OTP_EXPIRES_MINUTES = int(os.getenv("OTP_EXPIRES_MINUTES", "10"))
    OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))

    # ── CORS ───────────────────────────────────────────────────────────────────
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SQLALCHEMY_ECHO = False  # Flip to True to log all SQL during debugging


class TestingConfig(BaseConfig):
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql://postgres:password@localhost:5432/stophunterpro_test",
    )
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=60)
    RATELIMIT_ENABLED = False
    WTF_CSRF_ENABLED = False


class ProductionConfig(BaseConfig):
    DEBUG = False
    SQLALCHEMY_ECHO = False
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"


config_map = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config():
    env = os.getenv("FLASK_ENV", "development")
    cfg = config_map.get(env)
    if cfg is None:
        raise ValueError(
            f"Unknown FLASK_ENV: '{env}'. Must be development, testing, or production."
        )
    return cfg
