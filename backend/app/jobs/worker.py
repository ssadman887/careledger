"""Celery application. Run with: celery -A app.jobs.worker worker --loglevel=info"""

from celery import Celery
from celery.schedules import crontab

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


@celery_app.task(name="careledger.payroll_calculate")
def calculate_payroll(run_id: int) -> str:
    """Compute payslips for a queued run. On failure the run is marked failed with the error."""
    return process_payroll_run(run_id)


def process_payroll_run(run_id: int) -> str:
    from app.core.db import session_scope
    from app.services import payroll
    from app.services.audit import Actor

    actor = Actor(id=None, label="payroll-job", roles=frozenset())
    try:
        with session_scope() as session:
            run = payroll.calculate_run(session, actor, run_id)
            return str(run.status)
    except Exception as exc:  # recorded on the run so the UI can show it
        with session_scope() as session:
            payroll.mark_failed(session, actor, run_id, f"{type(exc).__name__}: {exc}")
        return "failed"


def dispatch_payroll_run(run_id: int) -> None:
    """Queue the calculation on Celery; if the broker is unreachable, run it in-process."""
    try:
        calculate_payroll.apply_async(args=(run_id,), retry=False)
    except Exception:
        process_payroll_run(run_id)


@celery_app.task(name="careledger.payroll_monthly")
def run_monthly_payroll() -> str:
    """Monthly (25th): create and calculate this month's run if it does not exist yet.
    Submission and approval stay with people."""
    from datetime import UTC, datetime

    from app.core.db import session_scope
    from app.repositories import payroll as payroll_repo
    from app.services import payroll
    from app.services.audit import Actor

    today = datetime.now(UTC).date()
    actor = Actor(id=None, label="payroll-job", roles=frozenset())
    with session_scope() as session:
        if payroll_repo.run_for_month(session, today.year, today.month) is not None:
            return "exists"
        run = payroll.create_run(session, actor, year=today.year, month=today.month, pay_date=None)
        run_id = run.id
    return process_payroll_run(run_id)


@celery_app.task(name="careledger.budget_check")
def run_budget_check() -> int:
    """Daily: raise budget alerts (warning at the threshold, exceeded above 100%)."""
    from datetime import UTC, datetime

    from app.core.db import session_scope
    from app.services import budgets
    from app.services.audit import Actor

    actor = Actor(id=None, label="budget-job", roles=frozenset())
    with session_scope() as session:
        return len(budgets.check_alerts(session, actor, as_of=datetime.now(UTC).date()))


celery_app.conf.beat_schedule = {
    "dunning-daily": {"task": "careledger.dunning_run", "schedule": 24 * 3600},
    "vendor-payments-daily": {"task": "careledger.vendor_payment_run", "schedule": 24 * 3600},
    "budget-check-daily": {"task": "careledger.budget_check", "schedule": 24 * 3600},
    "payroll-monthly": {
        "task": "careledger.payroll_monthly",
        "schedule": crontab(minute=0, hour=2, day_of_month=25),
    },
}
