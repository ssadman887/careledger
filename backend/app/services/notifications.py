"""In-app notifications, created in the same transaction as the event that causes them.

Sources: approval requested (approvers of that role), approval decided (requester), budget
alerts (finance managers), payroll background calculation finished or failed (preparer).
Notifications are never deleted; users mark them read.
"""

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.core.pagination import PageParams
from app.models.identity import Role, User, user_roles
from app.models.notifications import Notification
from app.repositories.billing import _page

APPROVAL_LINKS = {
    "manual_journal": "/journal/{id}",
    "refund": "/payments?tab=refunds",
    "write_off": "/ar?tab=write-offs",
    "vendor_bill": "/payables/bills/{id}",
    "payroll_run": "/payroll/runs/{id}",
}


def approval_link(kind: str, entity_id: int) -> str:
    return APPROVAL_LINKS.get(kind, "/approvals").format(id=entity_id)


def users_with_role(session: Session, role: str) -> list[int]:
    stmt = (
        select(User.id)
        .join(user_roles, user_roles.c.user_id == User.id)
        .join(Role, Role.id == user_roles.c.role_id)
        .where(Role.name == role, User.is_active.is_(True), User.deleted_at.is_(None))
        .order_by(User.id)
    )
    return list(session.scalars(stmt).all())


def notify(
    session: Session,
    user_ids: Iterable[int],
    *,
    kind: str,
    title: str,
    body: str = "",
    link: str = "",
    level: str = "info",
) -> list[Notification]:
    rows = [
        Notification(
            user_id=uid, kind=kind, level=level, title=title[:200], body=body[:500], link=link[:200]
        )
        for uid in dict.fromkeys(user_ids)  # de-duplicate, keep order
    ]
    session.add_all(rows)
    session.flush()
    return rows


def notify_role(
    session: Session,
    role: str,
    *,
    exclude: int | None = None,
    kind: str,
    title: str,
    body: str = "",
    link: str = "",
    level: str = "info",
) -> list[Notification]:
    ids = [u for u in users_with_role(session, role) if u != exclude]
    return notify(session, ids, kind=kind, title=title, body=body, link=link, level=level)


def list_for(
    session: Session, user_id: int, params: PageParams, *, unread_only: bool
) -> tuple[Sequence[Notification], int]:
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    return _page(session, stmt, params, {"created_at": Notification.created_at}, "-created_at",
                 Notification.id.desc())  # fmt: skip


def unread_count(session: Session, user_id: int) -> int:
    stmt = select(func.count(Notification.id)).where(
        Notification.user_id == user_id, Notification.read_at.is_(None)
    )
    return int(session.scalar(stmt) or 0)


def mark_read(session: Session, user_id: int, notification_id: int) -> Notification:
    row = session.get(Notification, notification_id)
    if row is None or row.user_id != user_id:  # never reveal other users' notifications
        raise NotFound("Notification not found")
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
        session.flush()
    return row


def mark_all_read(session: Session, user_id: int) -> int:
    result = session.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    session.flush()
    return int(getattr(result, "rowcount", 0) or 0)
