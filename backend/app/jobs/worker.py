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


@celery_app.task(name="careledger.mock_insurer")
def run_mock_insurer() -> int:
    """Adjudicate all submitted/appealed claims (same logic as POST /claims/run-mock-insurer)."""
    from app.core.db import session_scope
    from app.services import mock_insurer
    from app.services.audit import Actor

    actor = Actor(id=None, label=mock_insurer.MOCK_ACTOR_LABEL, roles=frozenset())
    with session_scope() as session:
        return len(mock_insurer.run_batch(session, actor))


@celery_app.task(name="careledger.dunning_run")
def run_dunning() -> int:
    """Daily: create reminders for overdue patient balances."""
    from datetime import UTC, datetime

    from app.core.db import session_scope
    from app.services import ar
    from app.services.audit import Actor

    actor = Actor(id=None, label="dunning-job", roles=frozenset())
    with session_scope() as session:
        return len(ar.run_dunning(session, actor, as_of=datetime.now(UTC).date()))


@celery_app.task(name="careledger.vendor_payment_run")
def run_vendor_payments() -> int:
    """Daily: pay approved vendor bills whose scheduled date has arrived."""
    from datetime import UTC, datetime

    from app.core.db import session_scope
    from app.services import ap
    from app.services.audit import Actor

    actor = Actor(id=None, label="payment-run-job", roles=frozenset())
    with session_scope() as session:
        return len(ap.run_scheduled_payments(session, actor, as_of=datetime.now(UTC).date()))


celery_app.conf.beat_schedule = {
    "dunning-daily": {"task": "careledger.dunning_run", "schedule": 24 * 3600},
    "vendor-payments-daily": {"task": "careledger.vendor_payment_run", "schedule": 24 * 3600},
}
