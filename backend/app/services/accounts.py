"""Chart of accounts and org dimension management."""

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, Conflict, NotFound, ValidationFailed
from app.models.ledger import Account, AccountType
from app.models.org import CostCenter, Department
from app.repositories import ledger as repo
from app.services import audit
from app.services.audit import Actor

VALID_TYPES = {t.value for t in AccountType}


def get_account(session: Session, account_id: int) -> Account:
    account = repo.get_account(session, account_id)
    if account is None:
        raise NotFound("Account not found")
    return account


def _validate_parent(
    session: Session, parent_id: int | None, type_: str, self_id: int | None
) -> None:
    if parent_id is None:
        return
    parent = repo.get_account(session, parent_id)
    if parent is None:
        raise NotFound("Parent account not found", code="parent_not_found")
    if not parent.is_header:
        raise BusinessRuleViolation("Parent must be a header account", code="parent_not_header")
    if parent.type != type_:
        raise BusinessRuleViolation(
            "Parent account must have the same type", code="parent_type_mismatch"
        )
    # Walk up to prevent cycles.
    seen: set[int] = set()
    cursor: Account | None = parent
    while cursor is not None:
        if self_id is not None and cursor.id == self_id:
            raise BusinessRuleViolation("Account hierarchy cannot contain cycles", code="cycle")
        if cursor.id in seen:
            break
        seen.add(cursor.id)
        cursor = repo.get_account(session, cursor.parent_id) if cursor.parent_id else None


def _validate_cost_center(session: Session, cost_center_id: int | None) -> None:
    if cost_center_id is not None and session.get(CostCenter, cost_center_id) is None:
        raise NotFound("Cost center not found", code="cost_center_not_found")


def create_account(
    session: Session,
    actor: Actor,
    *,
    code: str,
    name: str,
    type_: str,
    parent_id: int | None,
    cost_center_id: int | None,
    is_header: bool,
    description: str,
) -> Account:
    if type_ not in VALID_TYPES:
        raise ValidationFailed("Invalid account type", code="invalid_type")
    if repo.get_account_by_code(session, code) is not None:
        raise Conflict(f"Account code {code} already exists", code="account_exists")
    _validate_parent(session, parent_id, type_, None)
    _validate_cost_center(session, cost_center_id)
    account = Account(
        code=code,
        name=name,
        type=type_,
        parent_id=parent_id,
        cost_center_id=cost_center_id,
        is_header=is_header,
        is_active=True,
        description=description,
    )
    session.add(account)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="account",
        entity_id=account.id,
        action="create",
        after=audit.snapshot(account),
    )
    return account


def update_account(
    session: Session,
    actor: Actor,
    account_id: int,
    *,
    name: str | None,
    parent_id: int | None,
    clear_parent: bool,
    cost_center_id: int | None,
    clear_cost_center: bool,
    is_active: bool | None,
    description: str | None,
) -> Account:
    account = get_account(session, account_id)
    before = audit.snapshot(account)
    if name is not None:
        account.name = name
    if description is not None:
        account.description = description
    if clear_parent:
        account.parent_id = None
    elif parent_id is not None:
        _validate_parent(session, parent_id, account.type, account.id)
        account.parent_id = parent_id
    if clear_cost_center:
        account.cost_center_id = None
    elif cost_center_id is not None:
        _validate_cost_center(session, cost_center_id)
        account.cost_center_id = cost_center_id
    if is_active is False and account.is_active:
        if repo.account_balance(session, account.id) != 0:
            raise BusinessRuleViolation(
                "Accounts with a non-zero balance cannot be deactivated", code="non_zero_balance"
            )
        if account.is_header and repo.has_children(session, account.id):
            raise BusinessRuleViolation(
                "Header accounts with children cannot be deactivated", code="has_children"
            )
    if is_active is not None:
        account.is_active = is_active
    session.flush()
    action = "status_change" if before["is_active"] != account.is_active else "update"
    audit.record(
        session,
        actor,
        entity_type="account",
        entity_id=account.id,
        action=action,
        before=before,
        after=audit.snapshot(account),
    )
    return account


def create_department(
    session: Session, actor: Actor, *, code: str, name: str, revenue_account_id: int | None
) -> Department:
    if revenue_account_id is not None:
        account = get_account(session, revenue_account_id)
        if account.type != AccountType.REVENUE or account.is_header:
            raise BusinessRuleViolation(
                "Revenue account must be a postable revenue account", code="invalid_revenue_account"
            )
    dept = Department(code=code, name=name, revenue_account_id=revenue_account_id)
    session.add(dept)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="department",
        entity_id=dept.id,
        action="create",
        after=audit.snapshot(dept),
    )
    return dept


def create_cost_center(
    session: Session, actor: Actor, *, code: str, name: str, department_id: int | None
) -> CostCenter:
    if department_id is not None and session.get(Department, department_id) is None:
        raise NotFound("Department not found", code="department_not_found")
    cc = CostCenter(code=code, name=name, department_id=department_id)
    session.add(cc)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="cost_center",
        entity_id=cc.id,
        action="create",
        after=audit.snapshot(cc),
    )
    return cc
