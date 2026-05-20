import redis as redis_lib
from celery import Celery
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

# ── SQLAlchemy ──────────────────────────────────────────────────────────────────
db = SQLAlchemy()

# ── Flask-Migrate ───────────────────────────────────────────────────────────────
migrate = Migrate()

# ── JWT ─────────────────────────────────────────────────────────────────────────
jwt = JWTManager()

# ── Bcrypt ──────────────────────────────────────────────────────────────────────
bcrypt = Bcrypt()

# ── Rate Limiter ─────────────────────────────────────────────────────────────────
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per hour"],
    headers_enabled=True,
)

# ── Celery (configured after app is created) ────────────────────────────────────
celery = Celery(__name__)


def init_celery(app, celery_instance: Celery) -> None:
    """Bind Celery to the Flask app so tasks have access to app context."""
    celery_instance.conf.update(
        broker_url=app.config["CELERY_BROKER_URL"],
        result_backend=app.config["CELERY_RESULT_BACKEND"],
        task_serializer=app.config["CELERY_TASK_SERIALIZER"],
        result_serializer=app.config["CELERY_RESULT_SERIALIZER"],
        accept_content=app.config["CELERY_ACCEPT_CONTENT"],
        timezone=app.config["CELERY_TIMEZONE"],
        enable_utc=app.config["CELERY_ENABLE_UTC"],
    )

    class ContextTask(celery_instance.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_instance.Task = ContextTask


def get_redis_client(app) -> redis_lib.Redis:
    """
    Return a Redis client backed by a connection pool.
    Used by the health check and any service that needs direct Redis access.
    decode_responses=True so all keys/values are native Python strings.
    """
    return redis_lib.from_url(
        app.config["REDIS_URL"],
        decode_responses=True,
    )
