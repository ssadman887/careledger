import pytest
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, Conflict, NotFound, ValidationFailed
from app.services import accounts
from app.services.audit import SYSTEM_ACTOR


def _create(db: Session, code: str, **kw):  # type: ignore[no-untyped-def]
    args = {
        "name": f"Account {code}",
        "type_": "expense",
        "parent_id": None,
        "cost_center_id": None,
        "is_header": False,
        "description": "",
    }
    args.update(kw)
    return accounts.create_account(db, SYSTEM_ACTOR, code=code, **args)


def test_hierarchy_cannot_cycle(db: Session) -> None:
    top = _create(db, "H1", is_header=True)
    mid = _create(db, "H2", is_header=True, parent_id=top.id)
    with pytest.raises(BusinessRuleViolation, match="cycles"):
        accounts.update_account(
            db,
            SYSTEM_ACTOR,
            top.id,
            name=None,
            parent_id=mid.id,
            clear_parent=False,
            cost_center_id=None,
            clear_cost_center=False,
            is_active=None,
            description=None,
        )


def test_header_with_children_cannot_be_deactivated(db: Session) -> None:
    top = _create(db, "H3", is_header=True)
    _create(db, "C3", parent_id=top.id)
    with pytest.raises(BusinessRuleViolation, match="children"):
        accounts.update_account(
            db,
            SYSTEM_ACTOR,
            top.id,
            name=None,
            parent_id=None,
            clear_parent=False,
            cost_center_id=None,
            clear_cost_center=False,
            is_active=False,
            description=None,
        )


def test_cost_center_assignment_and_clearing(db: Session) -> None:
    cc = accounts.create_cost_center(db, SYSTEM_ACTOR, code="CC-T", name="Test", department_id=None)
    acct = _create(db, "C4", cost_center_id=cc.id)
    assert acct.cost_center_id == cc.id
    other = _create(db, "C5")
    updated = accounts.update_account(
        db,
        SYSTEM_ACTOR,
        other.id,
        name="Renamed",
        parent_id=None,
        clear_parent=False,
        cost_center_id=cc.id,
        clear_cost_center=False,
        is_active=None,
        description="desc",
    )
    assert (updated.cost_center_id, updated.name, updated.description) == (cc.id, "Renamed", "desc")
    cleared = accounts.update_account(
        db,
        SYSTEM_ACTOR,
        other.id,
        name=None,
        parent_id=None,
        clear_parent=True,
        cost_center_id=None,
        clear_cost_center=True,
        is_active=None,
        description=None,
    )
    assert cleared.cost_center_id is None and cleared.parent_id is None
    with pytest.raises(NotFound):
        _create(db, "C6", cost_center_id=999_999)


def test_validation_errors(db: Session) -> None:
    with pytest.raises(ValidationFailed):
        _create(db, "C7", type_="nonsense")
    _create(db, "C8")
    with pytest.raises(Conflict):
        _create(db, "C8")
    with pytest.raises(NotFound):
        _create(db, "C9", parent_id=999_999)
    with pytest.raises(NotFound):
        accounts.get_account(db, 999_999)
    with pytest.raises(NotFound):
        accounts.create_cost_center(db, SYSTEM_ACTOR, code="CC-X", name="X", department_id=999_999)
