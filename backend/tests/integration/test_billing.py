"""Patient billing: invoice -> payment -> ledger, partial payments, void, idempotency, roles,
deposits, refunds, DB guards, PDFs."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, Conflict, PermissionDenied
from app.models.billing import Invoice, InvoiceStatus
from app.models.catalog import Service
from app.models.ledger import Account, JournalEntry, JournalLine
from app.models.patients import Patient, Visit
from app.services import catalog, invoices, payments
from app.services.audit import SYSTEM_ACTOR
from app.services.invoices import LineSpec
from tests.conftest import check_deferred

D = Decimal


# ------------------------------------------------------------------ helpers


@pytest.fixture
def svc(db: Session):  # type: ignore[no-untyped-def]
    ids = {s.code: s.id for s in db.scalars(select(Service)).all()}
    return lambda code: ids[code]


@pytest.fixture
def patient(db: Session) -> Patient:
    return db.scalars(select(Patient).order_by(Patient.id)).first()  # type: ignore[return-value]


@pytest.fixture
def visit(db: Session, patient: Patient) -> Visit:
    v = db.scalars(select(Visit).where(Visit.patient_id == patient.id)).first()
    assert v is not None
    return v


def entry_lines(db: Session, entry_id: int) -> dict[str, tuple[Decimal, Decimal]]:
    """account code -> (debit, credit) for a journal entry."""
    rows = db.execute(
        select(Account.code, JournalLine.debit, JournalLine.credit)
        .join(Account, Account.id == JournalLine.account_id)
        .where(JournalLine.entry_id == entry_id)
    ).all()
    out: dict[str, tuple[Decimal, Decimal]] = {}
    for code, debit, credit in rows:
        d, c = out.get(code, (D(0), D(0)))
        out[code] = (d + debit, c + credit)
    return out


def make_invoice(
    db: Session,
    actor,
    patient: Patient,
    svc,
    *,
    issue: bool = True,  # type: ignore[no-untyped-def]
    on: date = date(2026, 9, 1),
) -> Invoice:
    inv = invoices.create_invoice(
        db,
        actor,
        patient_id=patient.id,
        visit_id=None,
        price_list_id=None,
        notes="",
        lines=[
            LineSpec(quantity=D(1), service_id=svc("ER-L3"), service_date=on),
            LineSpec(quantity=D(2), service_id=svc("LAB-CBC"), service_date=on),
        ],
    )
    if issue:
        invoices.issue_invoice(db, actor, inv.id, invoice_date=on)
    return inv


# ------------------------------------------------------------------ invoice -> ledger


def test_invoice_issue_posts_balanced_entry_by_department(
    db: Session, actor_for, patient, svc
) -> None:  # type: ignore[no-untyped-def]
    clerk = actor_for("billing")
    inv = invoices.create_invoice(
        db,
        clerk,
        patient_id=patient.id,
        visit_id=None,
        price_list_id=None,
        notes="",
        lines=[
            LineSpec(
                quantity=D(1),
                service_id=svc("ER-L3"),
                service_date=date(2026, 9, 1),
                discount_percent=D("10"),
            ),  # 420 - 42
            LineSpec(
                quantity=D(2), service_id=svc("PHAR-ANALG"), service_date=date(2026, 9, 1)
            ),  # 36 + 5% tax
        ],
    )
    assert inv.status == InvoiceStatus.DRAFT
    assert (inv.subtotal, inv.discount_total, inv.tax_total, inv.total) == (
        D("456.00"),
        D("42.00"),
        D("1.80"),
        D("415.80"),
    )

    invoices.issue_invoice(db, clerk, inv.id, invoice_date=date(2026, 9, 1))
    check_deferred(db)
    assert inv.status == InvoiceStatus.ISSUED
    assert inv.due_date == date(2026, 10, 1)
    lines = entry_lines(db, inv.issue_entry_id)  # type: ignore[arg-type]
    assert lines == {
        "1100": (D("415.80"), D(0)),  # AR patients
        "4910": (D("42.00"), D(0)),  # discounts
        "4110": (D(0), D("420.00")),  # emergency revenue
        "4170": (D(0), D("36.00")),  # pharmacy revenue
        "2300": (D(0), D("1.80")),  # sales tax
    }
    dept_lines = db.scalars(
        select(JournalLine).where(
            JournalLine.entry_id == inv.issue_entry_id, JournalLine.credit > 0
        )
    ).all()
    assert all(ln.department_id for ln in dept_lines if ln.description.startswith("Patient"))


def test_prices_follow_effective_dates(db: Session, actor_for, patient, svc) -> None:  # type: ignore[no-untyped-def]
    clerk = actor_for("billing")
    inv = invoices.create_invoice(
        db,
        clerk,
        patient_id=patient.id,
        visit_id=None,
        price_list_id=None,
        notes="",
        lines=[
            LineSpec(quantity=D(1), service_id=svc("ER-TRIAGE"), service_date=date(2026, 6, 30)),
            LineSpec(quantity=D(1), service_id=svc("ER-TRIAGE"), service_date=date(2026, 7, 1)),
        ],
    )
    assert [ln.unit_price for ln in inv.lines] == [D("180.00"), D("195.00")]
    with pytest.raises(BusinessRuleViolation) as exc:
        invoices.create_invoice(
            db,
            clerk,
            patient_id=patient.id,
            visit_id=None,
            price_list_id=None,
            notes="",
            lines=[
                LineSpec(
                    quantity=D(1), service_id=svc("ER-TRIAGE"), service_date=date(2025, 12, 31)
                )
            ],
        )
    assert exc.value.code == "no_price"


def test_payment_flow_partial_then_full(db: Session, actor_for, patient, svc) -> None:  # type: ignore[no-untyped-def]
    clerk = actor_for("billing")
    inv = make_invoice(db, clerk, patient, svc)
    total = inv.total
    assert total == D("496.00")

    p1 = payments.record_payment(
        db,
        clerk,
        invoice_id=inv.id,
        method="cash",
        amount=D("100.00"),
        received_on=date(2026, 9, 5),
        reference="",
        notes="",
    )
    assert inv.status == InvoiceStatus.PARTIALLY_PAID and inv.balance_due == D("396.00")
    assert entry_lines(db, p1.journal_entry_id) == {
        "1010": (D("100.00"), D(0)),  # type: ignore[arg-type]
        "1100": (D(0), D("100.00")),
    }
    with pytest.raises(BusinessRuleViolation) as exc:
        payments.record_payment(
            db,
            clerk,
            invoice_id=inv.id,
            method="card",
            amount=D("396.01"),
            received_on=None,
            reference="1234",
            notes="",
        )
    assert exc.value.code == "overpayment"

    p2 = payments.record_payment(
        db,
        clerk,
        invoice_id=inv.id,
        method="card",
        amount=D("396.00"),
        received_on=date(2026, 9, 6),
        reference="4242",
        notes="",
    )
    check_deferred(db)
    assert inv.status == InvoiceStatus.PAID and inv.balance_due == D("0.00")
    assert entry_lines(db, p2.journal_entry_id)["1020"] == (D("396.00"), D(0))  # type: ignore[arg-type]
    with pytest.raises(Conflict):
        payments.record_payment(
            db,
            clerk,
            invoice_id=inv.id,
            method="cash",
            amount=D("1.00"),
            received_on=None,
            reference="",
            notes="",
        )
    # AR for this invoice nets to zero: 496 debited at issue, 100 + 396 credited by payments.
    ar = db.execute(
        text(
            "SELECT sum(l.debit) - sum(l.credit) FROM journal_lines l "
            "JOIN journal_entries e ON e.id = l.entry_id JOIN accounts a ON a.id = l.account_id "
            "WHERE a.code = '1100' AND e.id = ANY(:ids)"
        ),
        {"ids": [inv.issue_entry_id, p1.journal_entry_id, p2.journal_entry_id]},
    ).scalar()
    assert ar == D("0.00")


def test_void_reverses_issue_entry(db: Session, actor_for, patient, svc) -> None:  # type: ignore[no-untyped-def]
    clerk = actor_for("billing")
    inv = make_invoice(db, clerk, patient, svc)
    invoices.void_invoice(db, clerk, inv.id, "Billed wrong patient")
    check_deferred(db)
    assert inv.status == InvoiceStatus.VOID
    reversal = db.get(JournalEntry, inv.void_entry_id)
    assert reversal is not None and reversal.reversal_of_id == inv.issue_entry_id
    issued, voided = entry_lines(db, inv.issue_entry_id), entry_lines(db, reversal.id)  # type: ignore[arg-type]
    assert {k: (c, d) for k, (d, c) in issued.items()} == voided
    with pytest.raises(Conflict):
        invoices.void_invoice(db, clerk, inv.id, "again")


def test_void_with_payments_requires_refund_first(db: Session, actor_for, patient, svc) -> None:  # type: ignore[no-untyped-def]
    clerk = actor_for("billing")
    inv = make_invoice(db, clerk, patient, svc)
    p = payments.record_payment(
        db,
        clerk,
        invoice_id=inv.id,
        method="cash",
        amount=D("50.00"),
        received_on=date(2026, 9, 2),
        reference="",
        notes="",
    )
    with pytest.raises(BusinessRuleViolation) as exc:
        invoices.void_invoice(db, clerk, inv.id, "x")
    assert exc.value.code == "has_payments"
    payments.request_refund(
        db,
        clerk,
        payment_id=p.id,
        amount=D("50.00"),
        reason="Void",
        approval_threshold=D("500"),
        refunded_on=date(2026, 9, 3),
    )
    assert inv.status == InvoiceStatus.ISSUED and inv.amount_paid == D("0.00")
    invoices.void_invoice(db, clerk, inv.id, "Now refunded")
    assert inv.status == InvoiceStatus.VOID


def test_draft_void_posts_nothing_and_drafts_are_editable(
    db: Session, actor_for, patient, svc
) -> None:  # type: ignore[no-untyped-def]
    clerk = actor_for("billing")
    inv = make_invoice(db, clerk, patient, svc, issue=False)
    invoices.update_draft(
        db,
        clerk,
        inv.id,
        notes="edited",
        lines=[LineSpec(quantity=D(3), service_id=svc("OPD-FU"), service_date=date(2026, 9, 1))],
    )
    assert inv.total == D("360.00") and len(inv.lines) == 1
    invoices.void_invoice(db, clerk, inv.id, "Not needed")
    assert inv.issue_entry_id is None and inv.void_entry_id is None


def test_issue_requires_open_period_and_positive_total(
    db: Session, actor_for, patient, svc
) -> None:  # type: ignore[no-untyped-def]
    clerk = actor_for("billing")
    empty = invoices.create_invoice(
        db, clerk, patient_id=patient.id, visit_id=None, price_list_id=None, notes="", lines=[]
    )
    with pytest.raises(BusinessRuleViolation) as exc:
        invoices.issue_invoice(db, clerk, empty.id)
    assert exc.value.code == "empty_invoice"
    inv = make_invoice(db, clerk, patient, svc, issue=False)
    with pytest.raises(BusinessRuleViolation) as exc:
        invoices.issue_invoice(db, clerk, inv.id, invoice_date=date(2019, 1, 1))
    assert exc.value.code == "no_fiscal_period"


# ------------------------------------------------------------------ DB guards


@pytest.mark.parametrize(
    ("stmt", "match"),
    [
        ("UPDATE invoice_lines SET unit_price = 1 WHERE invoice_id = :i", "frozen"),
        ("DELETE FROM invoice_lines WHERE invoice_id = :i", "frozen"),
        (
            "UPDATE invoices SET total = total + 1, subtotal = subtotal + 1 WHERE id = :i",
            "immutable",
        ),
        ("DELETE FROM invoices WHERE id = :i", "cannot be deleted"),
    ],
)
def test_issued_invoice_db_guards(
    db: Session, actor_for, patient, svc, stmt: str, match: str
) -> None:  # type: ignore[no-untyped-def]
    inv = make_invoice(db, actor_for("billing"), patient, svc)
    db.flush()
    nested = db.begin_nested()
    with pytest.raises(DBAPIError, match=match):
        db.execute(text(stmt), {"i": inv.id})
    nested.rollback()


def test_payments_cannot_be_deleted(db: Session, actor_for, patient, svc) -> None:  # type: ignore[no-untyped-def]
    clerk = actor_for("billing")
    inv = make_invoice(db, clerk, patient, svc)
    p = payments.record_payment(
        db,
        clerk,
        invoice_id=inv.id,
        method="cash",
        amount=D("10.00"),
        received_on=date(2026, 9, 2),
        reference="",
        notes="",
    )
    db.flush()
    nested = db.begin_nested()
    with pytest.raises(DBAPIError, match="cannot be deleted"):
        db.execute(text("DELETE FROM payments WHERE id = :p"), {"p": p.id})
    nested.rollback()


# ------------------------------------------------------------------ deposits & refunds


def test_deposit_received_applied_and_limited(db: Session, actor_for, patient, svc) -> None:  # type: ignore[no-untyped-def]
    from app.repositories import billing as repo

    clerk = actor_for("billing")
    dep = payments.record_deposit(
        db,
        clerk,
        patient_id=patient.id,
        method="bank_transfer",
        amount=D("300.00"),
        received_on=date(2026, 9, 1),
        reference="TRX-1",
        notes="",
    )
    assert entry_lines(db, dep.journal_entry_id) == {
        "1020": (D("300.00"), D(0)),  # type: ignore[arg-type]
        "2200": (D(0), D("300.00")),
    }
    inv = make_invoice(db, clerk, patient, svc)
    applied = payments.apply_deposit(
        db, clerk, invoice_id=inv.id, amount=D("250.00"), applied_on=date(2026, 9, 2)
    )
    assert entry_lines(db, applied.journal_entry_id) == {
        "2200": (D("250.00"), D(0)),  # type: ignore[arg-type]
        "1100": (D(0), D("250.00")),
    }
    assert repo.deposit_balance(db, patient.id) == D("50.00")
    with pytest.raises(BusinessRuleViolation) as exc:
        payments.apply_deposit(db, clerk, invoice_id=inv.id, amount=D("50.01"), applied_on=None)
    assert exc.value.code == "insufficient_deposit"
    # Only the unapplied 50.00 of the 300.00 deposit can be refunded.
    with pytest.raises(BusinessRuleViolation) as exc:
        payments.request_refund(
            db, clerk, payment_id=dep.id, amount=D("60.00"), reason="x", approval_threshold=D("500")
        )
    assert exc.value.code == "over_refund"
    rf = payments.request_refund(
        db,
        clerk,
        payment_id=dep.id,
        amount=D("50.00"),
        reason="Leftover",
        approval_threshold=D("500"),
        refunded_on=date(2026, 9, 3),
    )
    check_deferred(db)
    assert entry_lines(db, rf.journal_entry_id) == {
        "2200": (D("50.00"), D(0)),  # type: ignore[arg-type]
        "1020": (D(0), D("50.00")),
    }
    assert repo.deposit_balance(db, patient.id) == D("0.00")


def test_refund_approval_workflow(db: Session, actor_for, patient, svc) -> None:  # type: ignore[no-untyped-def]
    clerk, finance = actor_for("billing"), actor_for("finance")
    inv = make_invoice(db, clerk, patient, svc)
    p = payments.record_payment(
        db,
        clerk,
        invoice_id=inv.id,
        method="cash",
        amount=inv.total,
        received_on=date(2026, 9, 2),
        reference="",
        notes="",
    )
    big = payments.request_refund(
        db,
        clerk,
        payment_id=p.id,
        amount=D("450.00"),
        reason="Overcharge",
        approval_threshold=D("400.00"),
    )
    assert big.status == "pending_approval" and big.journal_entry_id is None
    assert inv.status == InvoiceStatus.PAID  # nothing moves until approved
    # Pending refunds reserve their amount.
    with pytest.raises(BusinessRuleViolation):
        payments.request_refund(
            db,
            clerk,
            payment_id=p.id,
            amount=D("46.01"),
            reason="x",
            approval_threshold=D("400.00"),
        )
    with pytest.raises(PermissionDenied):
        payments.approve_refund(db, clerk, big.id, "self")
    payments.approve_refund(db, finance, big.id, "OK", refunded_on=date(2026, 9, 4))
    check_deferred(db)
    assert big.status == "completed"
    assert entry_lines(db, big.journal_entry_id) == {
        "1100": (D("450.00"), D(0)),  # type: ignore[arg-type]
        "1010": (D(0), D("450.00")),
    }
    assert inv.status == InvoiceStatus.PARTIALLY_PAID and inv.balance_due == D("450.00")
    rejected = payments.request_refund(
        db, clerk, payment_id=p.id, amount=D("46.00"), reason="r", approval_threshold=D("10.00")
    )
    payments.reject_refund(db, finance, rejected.id, "Not justified")
    assert rejected.status == "rejected"


def test_card_reference_is_last_four_only(db: Session, actor_for, patient, svc) -> None:  # type: ignore[no-untyped-def]
    from app.core.errors import ValidationFailed

    clerk = actor_for("billing")
    inv = make_invoice(db, clerk, patient, svc)
    with pytest.raises(ValidationFailed):
        payments.record_payment(
            db,
            clerk,
            invoice_id=inv.id,
            method="card",
            amount=D("1.00"),
            received_on=None,
            reference="4242424242424242",
            notes="",
        )


def test_price_history_is_gap_free_and_non_overlapping(db: Session, svc) -> None:  # type: ignore[no-untyped-def]
    default = catalog.default_price_list(db)
    item = catalog.set_price(
        db,
        SYSTEM_ACTOR,
        price_list_id=default.id,
        service_id=svc("LAB-CBC"),
        unit_price=D("40.00"),
        effective_from=date(2026, 10, 1),
    )
    assert catalog.prices_on(db, default.id, {svc("LAB-CBC")}, date(2026, 9, 30)) == {
        svc("LAB-CBC"): D("38.00")
    }
    assert catalog.prices_on(db, default.id, {svc("LAB-CBC")}, date(2026, 10, 1)) == {
        svc("LAB-CBC"): D("40.00")
    }
    with pytest.raises(BusinessRuleViolation):
        catalog.set_price(
            db,
            SYSTEM_ACTOR,
            price_list_id=default.id,
            service_id=svc("LAB-CBC"),
            unit_price=D("1"),
            effective_from=date(2026, 10, 1),
        )
    db.flush()
    nested = db.begin_nested()
    with pytest.raises(DBAPIError, match="price_list_items_no_overlap"):
        db.execute(
            text(
                "INSERT INTO price_list_items (price_list_id, service_id, unit_price, effective_from, effective_to)"
                " VALUES (:l, :s, 1, '2026-10-15', '2026-10-20')"
            ),
            {"l": default.id, "s": item.service_id},
        )
    nested.rollback()


# ------------------------------------------------------------------ API: idempotency, roles, PDFs


def _api_invoice(client: TestClient, headers, patient: Patient, svc) -> dict:  # type: ignore[no-untyped-def]
    created = client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "patient_id": patient.id,
            "lines": [
                {"service_id": svc("OPD-NEW"), "quantity": "1", "service_date": "2026-09-10"},
                {
                    "service_id": svc("LAB-LIPID"),
                    "quantity": "1",
                    "service_date": "2026-09-10",
                    "discount_percent": "50",
                },
            ],
        },
    )
    assert created.status_code == 201, created.text
    issued = client.post(
        f"/api/v1/invoices/{created.json()['id']}/issue",
        headers=headers,
        json={"invoice_date": "2026-09-10"},
    )
    assert issued.status_code == 200, issued.text
    return issued.json()


def test_idempotent_payment_retry_does_not_double_post(
    client: TestClient, login, patient, svc, db: Session
) -> None:  # type: ignore[no-untyped-def]
    headers = login("billing")
    inv = _api_invoice(client, headers, patient, svc)
    assert inv["total"] == "232.00"
    body = {
        "invoice_id": inv["id"],
        "method": "cash",
        "amount": "100.00",
        "received_on": "2026-09-11",
    }
    key = {**headers, "Idempotency-Key": "pay-test-0001"}

    first = client.post("/api/v1/payments", json=body, headers=key)
    retry = client.post("/api/v1/payments", json=body, headers=key)
    assert first.status_code == retry.status_code == 201
    assert first.json() == retry.json()

    inv_after = client.get(f"/api/v1/invoices/{inv['id']}", headers=headers).json()
    assert inv_after["amount_paid"] == "100.00"
    entries = db.scalars(
        select(JournalEntry).where(
            JournalEntry.source_type == "payment", JournalEntry.source_id == str(first.json()["id"])
        )
    ).all()
    assert len(entries) == 1

    reused = client.post("/api/v1/payments", json={**body, "amount": "50.00"}, headers=key)
    assert reused.status_code == 422
    assert reused.json()["error"]["code"] == "idempotency_key_reused"
    # A different key is a different payment.
    other = client.post(
        "/api/v1/payments", json=body, headers={**headers, "Idempotency-Key": "pay-test-0002"}
    )
    assert other.status_code == 201 and other.json()["id"] != first.json()["id"]
    bad_key = client.post(
        "/api/v1/payments", json=body, headers={**headers, "Idempotency-Key": "x"}
    )
    assert bad_key.json()["error"]["code"] == "invalid_idempotency_key"


def test_failed_request_does_not_burn_the_key(client: TestClient, login, patient, svc) -> None:  # type: ignore[no-untyped-def]
    headers = login("billing")
    inv = _api_invoice(client, headers, patient, svc)
    key = {**headers, "Idempotency-Key": "pay-test-retry"}
    too_much = {
        "invoice_id": inv["id"],
        "method": "cash",
        "amount": "999.00",
        "received_on": "2026-09-11",
    }
    assert client.post("/api/v1/payments", json=too_much, headers=key).status_code == 422
    ok = {**too_much, "amount": "10.00"}
    # Same key, corrected body after a failure: rejected as reuse? No: the failed attempt rolled back.
    assert client.post("/api/v1/payments", json=ok, headers=key).status_code == 201


@pytest.mark.parametrize(
    ("username", "can_read", "can_bill"),
    [
        ("billing", True, True),
        ("insurance", True, False),
        ("finance", True, False),
        ("accountant", True, False),
        ("auditor", True, False),
        ("admin", False, False),
    ],
)
def test_billing_role_restrictions(
    client: TestClient,
    login,
    patient,
    svc,  # type: ignore[no-untyped-def]
    username: str,
    can_read: bool,
    can_bill: bool,
) -> None:
    headers = login(username)
    assert (client.get("/api/v1/invoices", headers=headers).status_code == 200) is can_read
    created = client.post("/api/v1/invoices", headers=headers, json={"patient_id": patient.id})
    assert (created.status_code == 201) is can_bill
    payment = client.post(
        "/api/v1/payments",
        headers=headers,
        json={
            "patient_id": patient.id,
            "method": "cash",
            "amount": "10.00",
            "received_on": "2026-09-11",
        },
    )
    assert (payment.status_code == 201) is can_bill
    if not can_bill:
        assert created.status_code == 403 and payment.status_code == 403


def test_refund_approval_requires_finance_via_api(client: TestClient, login, patient, svc) -> None:  # type: ignore[no-untyped-def]
    billing = login("billing")
    inv = _api_invoice(client, billing, patient, svc)
    pay = client.post(
        "/api/v1/payments",
        headers=billing,
        json={
            "invoice_id": inv["id"],
            "method": "bank_transfer",
            "amount": inv["total"],
            "received_on": "2026-09-11",
            "reference": "BANKREF-987654",
        },
    ).json()
    # Masking: billing sees the full bank reference; the accountant sees only the last 4.
    assert pay["reference"] == "BANKREF-987654"
    acct_view = client.get(f"/api/v1/payments/{pay['id']}", headers=login("accountant")).json()
    assert acct_view["reference"].endswith("7654") and "BANKREF" not in acct_view["reference"]

    pending = client.post(
        f"/api/v1/payments/{pay['id']}/refunds",
        headers=billing,
        json={"amount": "200.00", "reason": "Overcharge"},
    )
    # 200.00 is below the default 500.00 threshold: completes immediately.
    assert pending.json()["status"] == "completed"
    big_inv = _api_invoice(client, billing, patient, svc)
    client.post(
        "/api/v1/payments",
        headers=billing,
        json={
            "invoice_id": big_inv["id"],
            "method": "cash",
            "amount": big_inv["total"],
            "received_on": "2026-09-11",
        },
    )
    client.post(
        "/api/v1/payments",
        headers=billing,
        json={
            "patient_id": patient.id,
            "method": "cash",
            "amount": "900.00",
            "received_on": "2026-09-11",
        },
    )
    deposits = client.get(
        "/api/v1/payments", params={"kind": "deposit", "patient_id": patient.id}, headers=billing
    ).json()["items"]
    refund = client.post(
        f"/api/v1/payments/{deposits[0]['id']}/refunds",
        headers=billing,
        json={"amount": "600.00", "reason": "Treatment cancelled"},
    ).json()
    assert refund["status"] == "pending_approval"
    assert (
        client.post(f"/api/v1/refunds/{refund['id']}/approve", headers=billing, json={}).status_code
        == 403
    )
    approved = client.post(
        f"/api/v1/refunds/{refund['id']}/approve", headers=login("finance"), json={"note": "OK"}
    )
    assert approved.status_code == 200 and approved.json()["status"] == "completed"
    listed = client.get(
        "/api/v1/refunds", params={"status": "completed"}, headers=login("finance")
    ).json()
    assert listed["total"] >= 2


def test_invoice_list_filters_and_pdfs(client: TestClient, login, patient, svc) -> None:  # type: ignore[no-untyped-def]
    headers = login("billing")
    inv = _api_invoice(client, headers, patient, svc)
    found = client.get(
        "/api/v1/invoices", params={"search": patient.mrn, "status": "issued"}, headers=headers
    ).json()
    assert any(i["id"] == inv["id"] for i in found["items"])
    pay = client.post(
        "/api/v1/payments",
        headers=headers,
        json={
            "invoice_id": inv["id"],
            "method": "card",
            "amount": "10.00",
            "received_on": "2026-09-12",
            "reference": "1111",
        },
    ).json()
    assert pay["reference"] == "**** 1111"
    invoice_pdf = client.get(f"/api/v1/invoices/{inv['id']}/pdf", headers=headers)
    assert invoice_pdf.status_code == 200
    assert invoice_pdf.headers["content-type"] == "application/pdf"
    assert invoice_pdf.content.startswith(b"%PDF")
    receipt = client.get(f"/api/v1/payments/{pay['id']}/receipt", headers=login("auditor"))
    assert receipt.status_code == 200 and receipt.content.startswith(b"%PDF")


def test_float_quantity_rejected(client: TestClient, login, patient, svc) -> None:  # type: ignore[no-untyped-def]
    resp = client.post(
        "/api/v1/invoices",
        headers=login("billing"),
        json={"patient_id": patient.id, "lines": [{"service_id": svc("OPD-FU"), "quantity": 1.5}]},
    )
    assert resp.status_code == 422


def test_patients_and_visits_api(client: TestClient, login) -> None:  # type: ignore[no-untyped-def]
    headers = login("billing")
    created = client.post(
        "/api/v1/patients",
        headers=headers,
        json={
            "first_name": "Test",
            "last_name": "Patient",
            "date_of_birth": "1990-05-01",
            "sex": "female",
        },
    )
    assert created.status_code == 201
    pid = created.json()["id"]
    assert created.json()["mrn"].startswith("MRN-") and created.json()["deposit_balance"] == "0.00"
    depts = client.get("/api/v1/departments", headers=headers).json()
    visit = client.post(
        "/api/v1/visits",
        headers=headers,
        json={
            "patient_id": pid,
            "department_id": depts[0]["id"],
            "visit_type": "outpatient",
            "admit_date": "2026-09-01",
        },
    )
    assert visit.status_code == 201 and visit.json()["status"] == "open"
    closed = client.post(
        f"/api/v1/visits/{visit.json()['id']}/status",
        headers=headers,
        json={"status": "closed", "discharge_date": "2026-09-02"},
    )
    assert closed.json()["status"] == "closed"
    other = client.get(
        "/api/v1/patients", params={"search": "", "page_size": 1}, headers=headers
    ).json()
    mismatch = client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "patient_id": other["items"][0]["id"] if other["items"][0]["id"] != pid else pid + 1,
            "visit_id": visit.json()["id"],
        },
    )
    assert mismatch.status_code in (404, 422)
    future = client.post(
        "/api/v1/patients",
        headers=headers,
        json={"first_name": "A", "last_name": "B", "date_of_birth": "2999-01-01"},
    )
    assert future.status_code == 422
    assert (
        client.post(
            "/api/v1/patients",
            headers=login("accountant"),
            json={"first_name": "A", "last_name": "B", "date_of_birth": "1990-01-01"},
        ).status_code
        == 403
    )


def test_catalog_api(client: TestClient, login, svc) -> None:  # type: ignore[no-untyped-def]
    services = client.get(
        "/api/v1/services",
        params={"search": "ER-", "price_on": "2026-08-01"},
        headers=login("billing"),
    ).json()
    triage = next(s for s in services["items"] if s["code"] == "ER-TRIAGE")
    assert triage["current_price"] == "195.00"
    lists = client.get("/api/v1/price-lists", headers=login("billing")).json()
    default = next(pl for pl in lists if pl["is_default"])
    items = client.get(
        f"/api/v1/price-lists/{default['id']}/items",
        params={"service_id": svc("ER-TRIAGE")},
        headers=login("finance"),
    ).json()
    assert [(i["effective_from"], i["effective_to"]) for i in items] == [
        ("2026-01-01", "2026-06-30"),
        ("2026-07-01", None),
    ]
    new = client.post(
        "/api/v1/services",
        headers=login("finance"),
        json={"code": "OPD-NUTR", "name": "Nutrition consult", "department_id": 1, "tax_rate": "0"},
    )
    assert new.status_code in (201, 404)
    assert (
        client.post(
            "/api/v1/services",
            headers=login("billing"),
            json={"code": "X-1", "name": "x", "department_id": 1},
        ).status_code
        == 403
    )
