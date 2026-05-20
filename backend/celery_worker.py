"""
Celery worker entry point.

Start worker:
    celery -A celery_worker.celery worker --loglevel=info --pool=solo

Start beat scheduler (cron tasks) in a separate terminal:
    celery -A celery_worker.celery beat --loglevel=info

Note: --pool=solo is required on Windows. Use gevent or prefork on Linux/prod.
"""
from app import create_app
from app.extensions import celery

# Create the Flask app — this configures Celery via init_celery()
app = create_app()

# Import task modules so Celery auto-discovers them.
# The ContextTask defined in extensions.py wraps every task execution
# in `with app.app_context()` automatically — no manual push needed here.
import app.tasks.scanner_tasks       # noqa: F401, E402
import app.tasks.subscription_tasks  # noqa: F401, E402
import app.tasks.max_pain_tasks      # noqa: F401, E402
