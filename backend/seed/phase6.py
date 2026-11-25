"""Tidy seeded notifications so the demo shows what is actually waiting.

Seeding replays months of activity, which leaves "approval needed" notifications for requests
that were decided long ago. Those (and decisions older than the latest month) are marked read;
notifications for still-pending requests and budget alerts stay unread. Idempotent.
"""

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.approvals import Approval, ApprovalStatus
from app.models.notifications import Notification


def seed_phase6(session: Session) -> None:
    pending = set(
        session.scalars(select(Approval.reference).where(Approval.status == ApprovalStatus.PENDING))
    )
    stale = [
        n.id
        for n in session.scalars(
            select(Notification).where(
                Notification.read_at.is_(None), Notification.kind != "budget_alert"
            )
        )
        if not (
            n.kind == "approval_requested" and n.title.removeprefix("Approval needed: ") in pending
        )
    ]
    if stale:
        session.execute(
            update(Notification).where(Notification.id.in_(stale)).values(read_at=datetime.now(UTC))
        )
        session.flush()
