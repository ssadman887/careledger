from typing import Annotated, Literal

from fastapi import APIRouter, Depends

from app.core.deps import CurrentActor, DbSession, read_roles, require_roles
from app.core.errors import ErrorEnvelope, PermissionDenied
from app.core.pagination import Page, PageParams, page_params
from app.models.approvals import Approval, ApprovalKind, ApprovalStatus
from app.models.identity import RoleName
from app.repositories import approvals as repo
from app.schemas.phase4 import (
    ApprovalOut,
    ApprovalPolicyOut,
    ApprovalPolicyUpdate,
    CommentIn,
    DecisionIn,
    PendingCountOut,
)
from app.services import approvals
from app.services.audit import Actor

router = APIRouter(
    prefix="/approvals",
    tags=["approvals"],
    responses={
        401: {"model": ErrorEnvelope},
        403: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
    },
)

R = RoleName
PolicyRead = Annotated[Actor, Depends(read_roles(R.ADMIN, R.FINANCE_MANAGER, R.ACCOUNTANT))]
PolicyWrite = Annotated[Actor, Depends(require_roles(R.ADMIN, R.FINANCE_MANAGER))]
OVERSIGHT = frozenset({R.FINANCE_MANAGER.value, R.AUDITOR.value, R.ADMIN.value})


def _out(a: Approval, actor: Actor) -> ApprovalOut:
    out = ApprovalOut.model_validate(a)
    try:
        approvals.check_can_decide(actor, a)
        out.can_decide = True
    except Exception:
        out.can_decide = False
    return out


def _visible(a: Approval, actor: Actor) -> None:
    if actor.roles & OVERSIGHT or a.approver_role in actor.roles or a.requested_by_id == actor.id:
        return
    raise PermissionDenied("You cannot view this approval request")


@router.get("", response_model=Page[ApprovalOut])
def list_approvals(
    actor: CurrentActor,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    status: ApprovalStatus | None = None,
    kind: ApprovalKind | None = None,
    scope: Literal["to_decide", "mine", "all"] = "to_decide",
) -> Page[ApprovalOut]:
    """`to_decide`: requests my roles approve; `mine`: requests I made; `all`: oversight roles."""
    if scope == "all" and not actor.roles & OVERSIGHT:
        raise PermissionDenied("Only finance managers, admins and auditors can list all approvals")
    rows, total = approvals.list_approvals(
        db,
        actor,
        params,
        status=status.value if status else None,
        kind=kind.value if kind else None,
        scope=scope,
    )
    return Page(
        items=[_out(a, actor) for a in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get("/pending-count", response_model=PendingCountOut)
def pending_count(actor: CurrentActor, db: DbSession) -> PendingCountOut:
    return PendingCountOut(pending=repo.pending_count(db, sorted(actor.roles)))


@router.get("/policies", response_model=list[ApprovalPolicyOut])
def list_policies(_: PolicyRead, db: DbSession) -> list[ApprovalPolicyOut]:
    return [ApprovalPolicyOut.model_validate(approvals.policy(db, k.value)) for k in ApprovalKind]


@router.patch("/policies/{kind}", response_model=ApprovalPolicyOut)
def update_policy(
    kind: ApprovalKind, body: ApprovalPolicyUpdate, actor: PolicyWrite, db: DbSession
) -> ApprovalPolicyOut:
    policy = approvals.update_policy(
        db,
        actor,
        kind.value,
        threshold_amount=body.threshold,
        approver_role=body.approver_role,
        is_active=body.is_active,
    )
    return ApprovalPolicyOut.model_validate(policy)


@router.get("/{approval_id}", response_model=ApprovalOut)
def get_approval(approval_id: int, actor: CurrentActor, db: DbSession) -> ApprovalOut:
    approval = approvals.get_approval(db, approval_id)
    _visible(approval, actor)
    return _out(approval, actor)


@router.post("/{approval_id}/decision", response_model=ApprovalOut)
def decide(approval_id: int, body: DecisionIn, actor: CurrentActor, db: DbSession) -> ApprovalOut:
    """Approve or reject. The approver must hold the policy's role and not be the requester."""
    return _out(
        approvals.decide(db, actor, approval_id, approve=body.approve, note=body.note), actor
    )


@router.post("/{approval_id}/comments", response_model=ApprovalOut)
def comment(approval_id: int, body: CommentIn, actor: CurrentActor, db: DbSession) -> ApprovalOut:
    approval = approvals.get_approval(db, approval_id)
    _visible(approval, actor)
    if R.AUDITOR.value in actor.roles and len(actor.roles) == 1:
        raise PermissionDenied("Auditors have read-only access")
    return _out(approvals.comment(db, actor, approval_id, body.body), actor)
