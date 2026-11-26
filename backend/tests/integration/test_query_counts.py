"""N+1 guard: list endpoints issue the same number of SQL statements for 1 row or many."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.db import engine
from app.models.ap import Vendor
from app.models.patients import Patient
from app.services import ap, payments, payroll
from app.services.ap import APLine
from tests.integration import test_phase5 as p5
from tests.integration.test_phase4 import issue

D = Decimal
staff, dept = p5.staff, p5.dept  # re-used fixtures


@contextmanager
def count_queries() -> Iterator[list[int]]:
    seen = [0]

    def _count(*_: object, **__: object) -> None:
        seen[0] += 1

    event.listen(engine, "before_cursor_execute", _count)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", _count)


@pytest.fixture
def svc(db: Session):  # type: ignore[no-untyped-def]
    from app.models.catalog import Service

    ids = {s.code: s.id for s in db.scalars(select(Service)).all()}
    return lambda code: ids[code]


@pytest.fixture
def data(db: Session, actor_for, svc, staff, acct):  # type: ignore[no-untyped-def]
    clerk, accountant, finance = actor_for("billing"), actor_for("accountant"), actor_for("finance")
    people = db.scalars(select(Patient).order_by(Patient.id).limit(4)).all()
    for i, patient in enumerate(people):
        inv = issue(db, clerk, patient, svc, date(2026, 10, 1 + i))
        payments.record_payment(
            db, clerk, invoice_id=inv.id, method="cash", amount=D("50.00"),
            received_on=date(2026, 10, 5), reference="", notes="",
        )  # fmt: skip
    vendor = ap.create_vendor(
        db, accountant, code="QC", name="Query Count Supplies", email="", tax_id="",
        bank_reference="", payment_terms_days=30, default_expense_account_id=acct("5200"),
    )  # fmt: skip
    for i in range(4):
        po = ap.create_po(
            db, accountant, vendor_id=vendor.id, order_date=date(2026, 10, 1), expected_date=None,
            notes="", lines=[APLine(f"Item {i}", acct("5200"), D(1), D("10.00"))],
        )  # fmt: skip
        ap.issue_po(db, accountant, po.id)
        ap.create_bill(
            db, accountant, vendor_id=vendor.id, vendor_invoice_number=f"QC-{i}",
            bill_date=date(2026, 10, 2), due_date=None, purchase_order_id=po.id, lines=None, notes="",
        )  # fmt: skip
    for month in (7, 8, 9):
        run = payroll.create_run(db, accountant, year=2026, month=month, pay_date=None)
        payroll.calculate_run(db, accountant, run.id)
        payroll.submit_run(db, accountant, run.id)
    _ = (finance, Vendor)


LISTS = [
    "/api/v1/invoices",
    "/api/v1/payments",
    "/api/v1/purchase-orders",
    "/api/v1/vendor-bills",
    "/api/v1/payroll/runs",
    "/api/v1/payroll/employees",
    "/api/v1/journal-entries",
    "/api/v1/approvals?scope=all",
    "/api/v1/audit-log",
    "/api/v1/patients",
]


@pytest.mark.parametrize("path", LISTS)
def test_list_query_count_does_not_grow_with_rows(
    client: TestClient, login, data, path: str
) -> None:  # type: ignore[no-untyped-def]
    headers = login("auditor")
    sep = "&" if "?" in path else "?"
    counts = []
    for size in (1, 50):
        with count_queries() as seen:
            resp = client.get(f"{path}{sep}page_size={size}", headers=headers)
        assert resp.status_code == 200, resp.text
        assert len(resp.json()["items"]) >= (1 if size == 1 else 3), path
        counts.append(seen[0])
    assert counts[0] == counts[1], f"{path}: {counts[0]} queries for 1 row, {counts[1]} for many"
    assert counts[1] <= 10, f"{path}: {counts[1]} queries"
