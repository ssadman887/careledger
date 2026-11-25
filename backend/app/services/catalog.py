"""Service catalog and price lists with effective dates."""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, Conflict, NotFound, ValidationFailed
from app.models.catalog import PriceList, PriceListItem, Service
from app.models.org import Department
from app.repositories import billing as repo
from app.services import audit
from app.services.audit import Actor


def get_service(session: Session, service_id: int) -> Service:
    service = repo.get_service(session, service_id)
    if service is None:
        raise NotFound("Service not found")
    return service


def create_service(
    session: Session, actor: Actor, *, code: str, name: str, department_id: int, tax_rate: Decimal
) -> Service:
    if repo.get_service_by_code(session, code) is not None:
        raise Conflict(f"Service code {code} already exists", code="service_exists")
    if session.get(Department, department_id) is None:
        raise NotFound("Department not found", code="department_not_found")
    if not (Decimal("0") <= tax_rate < Decimal("1")):
        raise ValidationFailed(
            "Tax rate must be a fraction between 0 and 1", code="invalid_tax_rate"
        )
    service = Service(code=code, name=name, department_id=department_id, tax_rate=tax_rate)
    session.add(service)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="service",
        entity_id=service.id,
        action="create",
        after=audit.snapshot(service),
    )
    return service


def update_service(
    session: Session,
    actor: Actor,
    service_id: int,
    *,
    name: str | None,
    tax_rate: Decimal | None,
    is_active: bool | None,
) -> Service:
    service = get_service(session, service_id)
    before = audit.snapshot(service)
    if name is not None:
        service.name = name
    if tax_rate is not None:
        if not (Decimal("0") <= tax_rate < Decimal("1")):
            raise ValidationFailed(
                "Tax rate must be a fraction between 0 and 1", code="invalid_tax_rate"
            )
        service.tax_rate = tax_rate
    if is_active is not None:
        service.is_active = is_active
    session.flush()
    action = "status_change" if before["is_active"] != service.is_active else "update"
    audit.record(
        session,
        actor,
        entity_type="service",
        entity_id=service.id,
        action=action,
        before=before,
        after=audit.snapshot(service),
    )
    return service


def get_price_list(session: Session, price_list_id: int) -> PriceList:
    price_list = repo.get_price_list(session, price_list_id)
    if price_list is None:
        raise NotFound("Price list not found")
    return price_list


def default_price_list(session: Session) -> PriceList:
    price_list = repo.default_price_list(session)
    if price_list is None:
        raise BusinessRuleViolation("No default price list is configured", code="no_price_list")
    return price_list


def create_price_list(
    session: Session, actor: Actor, *, code: str, name: str, is_default: bool
) -> PriceList:
    if is_default:
        current = repo.default_price_list(session)
        if current is not None:
            current.is_default = False
            session.flush()
    price_list = PriceList(code=code, name=name, is_default=is_default)
    session.add(price_list)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="price_list",
        entity_id=price_list.id,
        action="create",
        after=audit.snapshot(price_list),
    )
    return price_list


def set_price(
    session: Session,
    actor: Actor,
    *,
    price_list_id: int,
    service_id: int,
    unit_price: Decimal,
    effective_from: date,
) -> PriceListItem:
    """Add a price effective from a date. The currently open-ended price (if it started earlier)
    is closed the day before, so prices form a gap-free history."""
    get_price_list(session, price_list_id)
    get_service(session, service_id)
    if unit_price < 0:
        raise ValidationFailed("Price cannot be negative", code="invalid_price")
    current = repo.open_ended_item(session, price_list_id, service_id)
    if current is not None:
        if effective_from <= current.effective_from:
            raise BusinessRuleViolation(
                "New price must start after the current price's effective date",
                code="price_overlap",
            )
        before = audit.snapshot(current)
        current.effective_to = effective_from - timedelta(days=1)
        session.flush()
        audit.record(
            session,
            actor,
            entity_type="price_list_item",
            entity_id=current.id,
            action="update",
            before=before,
            after=audit.snapshot(current),
        )
    item = PriceListItem(
        price_list_id=price_list_id,
        service_id=service_id,
        unit_price=unit_price,
        effective_from=effective_from,
    )
    session.add(item)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="price_list_item",
        entity_id=item.id,
        action="create",
        after=audit.snapshot(item),
    )
    return item


def prices_on(
    session: Session, price_list_id: int, service_ids: set[int], on: date
) -> dict[int, Decimal]:
    return repo.price_on(session, price_list_id, service_ids, on)
