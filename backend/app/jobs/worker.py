"""Celery application. Run with: celery -A app.jobs.worker worker --loglevel=info"""

from celery import Celery

from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging()
_settings = get_settings()

celery_app = Celery("careledger", broker=_settings.redis_url, backend=_settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


@celery_app.task(name="careledger.ping")
def ping() -> str:
    return "pong"
