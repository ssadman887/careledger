"""Approval queries."""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.pagination import PageParams
from app.models.approvals import Approval, ApprovalPolicy
from app.repositories.billing import _page


def get_policy(session: Session, kind: str) -> ApprovalPolicy | None:
    return session.scalars(select(ApprovalPolicy).where(ApprovalPolicy.kind == kind)).first()


def list_policies(session: Session) -> Sequence[ApprovalPolicy]:
    return session.scalars(select(ApprovalPolicy).order_by(ApprovalPolicy.kind)).all()


def get_approval(session: Session, approval_id: int, *, lock: bool = False) -> Approval | None:
    if lock:
        stmt = select(Approval).where(Approval.id == approval_id).with_for_update()
        return session.scalars(stmt).first()
    return session.get(Approval, approval_id)


def get_by_entity(session: Session, kind: str, entity_id: int) -> Approval | None:
    stmt = select(Approval).where(Approval.kind == kind, Approval.entity_id == entity_id)
    return session.scalars(stmt).first()


def ids_by_entities(session: Session, kind: str, entity_ids: Sequence[int]) -> dict[int, int]:
    """entity id -> approval id for a page of records, in one query."""
    if not entity_ids:
        return {}
    stmt = select(Approval.entity_id, Approval.id).where(
        Approval.kind == kind, Approval.entity_id.in_(entity_ids)
    )
    return {int(e): int(a) for e, a in session.execute(stmt).all()}


def list_approvals(
    session: Session,
    params: PageParams,
    *,
    status: str | None,
    kind: str | None,
    approver_roles: Sequence[str] | None,
    requested_by: int | None,
) -> tuple[Sequence[Approval], int]:
    stmt = select(Approval)
    if status:
        stmt = stmt.where(Approval.status == status)
    if kind:
        stmt = stmt.where(Approval.kind == kind)
    if approver_roles is not None:
        stmt = stmt.where(Approval.approver_role.in_(approver_roles))
    if requested_by is not None:
        stmt = stmt.where(Approval.requested_by_id == requested_by)
    sorts = {"created_at": Approval.created_at, "amount": Approval.amount}
    return _page(session, stmt, params, sorts, "-created_at", Approval.id.desc())


def pending_count(session: Session, roles: Sequence[str]) -> int:
    stmt = select(func.count(Approval.id)).where(
        Approval.status == "pending", Approval.approver_role.in_(roles)
    )
    return session.scalar(stmt) or 0
