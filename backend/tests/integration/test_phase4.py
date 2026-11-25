"""Phase 4: approval engine, AR aging / dunning / write-offs, AP three-way match and payments."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, Conflict, PermissionDenied, ValidationFailed
from app.models.approvals import Approval
from app.models.ar import WriteOff
from app.models.billing import InvoiceStatus
from app.models.ledger import EntryStatus
from app.models.patients import Patient
from app.services import ap, approvals, ar, invoices, ledger
from app.services.ap import APLine
from app.services.audit import SYSTEM_ACTOR
from app.services.invoices import LineSpec
from app.services.ledger import LineInput
from tests.conftest import check_deferred
from tests.integration.test_billing import entry_lines

D = Decimal
AS_OF = date(2026, 11, 30)


@pytest.fixture
def svc(db: Session):  # type: ignore[no-untyped-def]
    from app.models.catalog import Service

    ids = {s.code: s.id for s in db.scalars(select(Service)).all()}
    return lambda code: ids[code]


@pytest.fixture
def patient(db: Session) -> Patient:
    return db.scalars(select(Patient).order_by(Patient.id.desc())).first()  # type: ignore[return-value]


def issue(db: Session, actor, patient: Patient, svc, on: date, code: str = "OPD-FU"):  # type: ignore[no-untyped-def]
    inv = invoices.create_invoice(
        db,
        actor,
        patient_id=patient.id,
        visit_id=None,
        price_list_id=None,
        notes="",
        lines=[LineSpec(quantity=D(1), service_id=svc(code), service_date=on)],
    )
    invoices.issue_invoice(db, actor, inv.id, invoice_date=on)
    return inv


def account_balance(db: Session, code: str) -> Decimal:
    return D(
        db.execute(
            text(
                "SELECT coalesce(sum(l.debit) - sum(l.credit), 0) FROM journal_lines l "
                "JOIN accounts a ON a.id = l.account_id JOIN journal_entries e ON e.id = l.entry_id "
                "WHERE a.code = :c AND e.status = 'posted'"
            ),
            {"c": code},
        ).scalar()
    )


# ------------------------------------------------------------------ AR aging


def test_aging_by_patient_bucket_boundaries(db: Session, actor_for, patient, svc) -> None:  # type: ignore[no-untyped-def]
    clerk = actor_for("billing")
    ages = {30: "0-30", 31: "31-60", 60: "31-60", 61: "61-90", 90: "61-90", 91: "90+"}
    for days in ages:
        issue(db, clerk, patient, svc, AS_OF - timedelta(days=days))  # 120.00 each
    report = ar.aging(db, by="patient", as_of=AS_OF)
    row = next(r for r in report.rows if r.party_id == patient.id)
    assert row.buckets == {
        "0-30": D("120.00"),
        "31-60": D("240.00"),
        "61-90": D("240.00"),
        "90+": D("120.00"),
    }
    assert row.total == D("720.00")
    assert report.total == sum(report.totals.values())
    # Invoices dated after as_of are excluded.
    earlier = ar.aging(db, by="patient", as_of=AS_OF - timedelta(days=61))
    early_row = next(r for r in earlier.rows if r.party_id == patient.id)
    # Only the invoices dated on/before that day (aged 61, 90, 91 at AS_OF) count, aged 0-30 then.
    assert early_row.total == D("360.00") and early_row.buckets["0-30"] == D("360.00")


def test_aging_by_insurer_matches_pending_claims(db: Session, actor_for) -> None:  # type: ignore[no-untyped-def]
    report = ar.aging(db, by="insurer", as_of=datetime.now(UTC).date())
    pending = D(
        db.execute(text("SELECT coalesce(sum(insurance_pending), 0) FROM invoices")).scalar()
    )
    assert report.total == pending
    with pytest.raises(ValidationFailed):
        ar.aging(db, by="department", as_of=AS_OF)


# ------------------------------------------------------------------ dunning


def test_dunning_levels_and_idempotency(db: Session, actor_for, patient, svc) -> None:  # type: ignore[no-untyped-def]
    clerk = actor_for("billing")
    inv = issue(db, clerk, patient, svc, date(2026, 9, 1))  # due 2026-10-01
    first = ar.run_dunning(db, SYSTEM_ACTOR, as_of=date(2026, 10, 15))
    mine = [n for n in first if n.invoice_id == inv.id]
    assert [(n.level, n.days_overdue, n.amount_due) for n in mine] == [(1, 14, D("120.00"))]
    again = ar.run_dunning(db, SYSTEM_ACTOR, as_of=date(2026, 10, 20))
    assert not [n for n in again if n.invoice_id == inv.id]  # same level: no duplicate
    later = ar.run_dunning(db, SYSTEM_ACTOR, as_of=date(2026, 12, 5))
    assert [n.level for n in later if n.invoice_id == inv.id] == [3]


# ------------------------------------------------------------------ write-offs via the approval engine


def test_write_off_needs_approval_and_posts_to_bad_debt(
    db: Session, actor_for, patient, svc
) -> None:  # type: ignore[no-untyped-def]
    clerk, finance = actor_for("billing"), actor_for("finance")
    inv = issue(db, clerk, patient, svc, date(2026, 8, 1), code="RAD-US-ABD")  # 340.00
    with pytest.raises(BusinessRuleViolation):
        ar.request_write_off(db, clerk, invoice_id=inv.id, amount=D("340.01"), reason="x")
    wo = ar.request_write_off(
        db, clerk, invoice_id=inv.id, amount=D("340.00"), reason="Uncollectible"
    )
    assert wo.status == "pending_approval" and wo.journal_entry_id is None  # threshold 0
    approval = db.scalars(
        select(Approval).where(Approval.kind == "write_off", Approval.entity_id == wo.id)
    ).one()
    assert approval.status == "pending" and approval.approver_role == "finance_manager"
    with pytest.raises(PermissionDenied):
        approvals.decide(db, clerk, approval.id, approve=True, note="")  # requester / wrong role
    with pytest.raises(ValidationFailed):
        approvals.decide(db, finance, approval.id, approve=False, note=" ")

    approvals.decide(db, finance, approval.id, approve=True, note="Agreed")
    check_deferred(db)
    assert wo.status == "posted" and approval.status == "approved"
    assert entry_lines(db, wo.journal_entry_id) == {
        "5400": (D("340.00"), D(0)),  # type: ignore[arg-type]
        "1100": (D(0), D("340.00")),
    }
    assert inv.adjusted_amount == D("340.00") and inv.status == InvoiceStatus.PAID
    with pytest.raises(Conflict):
        approvals.decide(db, finance, approval.id, approve=True, note="")


def test_write_off_below_threshold_posts_immediately(db: Session, actor_for, patient, svc) -> None:  # type: ignore[no-untyped-def]
    clerk, finance = actor_for("billing"), actor_for("finance")
    approvals.update_policy(
        db, finance, "write_off", threshold_amount=D("50.00"), approver_role=None, is_active=None
    )
    inv = issue(db, clerk, patient, svc, date(2026, 8, 1))
    small = ar.request_write_off(
        db, clerk, invoice_id=inv.id, amount=D("50.00"), reason="Small balance"
    )
    assert small.status == "posted"
    big = ar.request_write_off(db, clerk, invoice_id=inv.id, amount=D("50.01"), reason="Rest")
    assert big.status == "pending_approval"
    ar.reject_write_off(db, finance, big.id, "Keep chasing")
    assert big.status == "rejected"


# ------------------------------------------------------------------ approval engine thresholds


def test_manual_journal_threshold_follows_policy(db: Session, actor_for, acct) -> None:  # type: ignore[no-untyped-def]
    accountant, finance = actor_for("accountant"), actor_for("finance")

    def entry(amount: str):  # type: ignore[no-untyped-def]
        return ledger.create_manual_entry(
            db,
            accountant,
            entry_date=date(2026, 6, 1),
            memo="t",
            lines=[
                LineInput(acct("5300"), debit=D(amount)),
                LineInput(acct("1020"), credit=D(amount)),
            ],
            approval_threshold=approvals.threshold(db, "manual_journal"),
        )

    assert approvals.threshold(db, "manual_journal") == D("10000.00")
    assert entry("10000.00").status == EntryStatus.POSTED  # equal: no approval
    pending = entry("10000.01")
    assert pending.status == EntryStatus.PENDING_APPROVAL
    approval = db.scalars(
        select(Approval).where(Approval.kind == "manual_journal", Approval.entity_id == pending.id)
    ).one()
    assert approval.reference == pending.entry_number

    approvals.update_policy(
        db,
        finance,
        "manual_journal",
        threshold_amount=D("20000.00"),
        approver_role=None,
        is_active=None,
    )
    assert entry("15000.00").status == EntryStatus.POSTED
    approvals.update_policy(
        db, finance, "manual_journal", threshold_amount=None, approver_role=None, is_active=False
    )
    assert entry("999999.00").status == EntryStatus.POSTED  # inactive policy: no approvals

    # Deciding through the domain endpoint keeps the approval record in sync.
    ledger.approve_entry(db, finance, pending.id)
    db.refresh(approval)
    assert approval.status == "approved" and approval.decided_by_label == finance.label


def test_engine_enforces_approver_role(db: Session, actor_for, acct) -> None:  # type: ignore[no-untyped-def]
    accountant, finance = actor_for("accountant"), actor_for("finance")
    pending = ledger.create_manual_entry(
        db,
        accountant,
        entry_date=date(2026, 6, 1),
        memo="big",
        lines=[
            LineInput(acct("5300"), debit=D("50000.00")),
            LineInput(acct("1020"), credit=D("50000.00")),
        ],
        approval_threshold=D("10000.00"),
    )
    approval = db.scalars(
        select(Approval).where(Approval.entity_id == pending.id, Approval.kind == "manual_journal")
    ).one()
    with pytest.raises(PermissionDenied) as exc:
        approvals.decide(db, actor_for("auditor"), approval.id, approve=True, note="")
    assert exc.value.code == "not_approver"
    approvals.comment(db, finance, approval.id, "Please attach the utility invoice")
    approvals.decide(db, finance, approval.id, approve=False, note="No supporting document")
    assert pending.status == EntryStatus.REJECTED and approval.status == "rejected"
    assert [c.body for c in approval.comments] == ["Please attach the utility invoice"]
    with pytest.raises(ValidationFailed):
        approvals.update_policy(
            db, finance, "refund", threshold_amount=D("-1"), approver_role=None, is_active=None
        )
    with pytest.raises(ValidationFailed):
        approvals.update_policy(
            db, finance, "refund", threshold_amount=None, approver_role="auditor", is_active=None
        )


# ------------------------------------------------------------------ AP


@pytest.fixture
def vendor(db: Session, actor_for, acct):  # type: ignore[no-untyped-def]
    return ap.create_vendor(
        db,
        actor_for("accountant"),
        code="TESTV",
        name="Test Vendor",
        email="",
        tax_id="T-1",
        bank_reference="BANK-12345678",
        payment_terms_days=30,
        default_expense_account_id=acct("5200"),
    )


def received_po(db: Session, actor, vendor, acct, amount: str = "900.00"):  # type: ignore[no-untyped-def]
    po = ap.create_po(
        db,
        actor,
        vendor_id=vendor.id,
        order_date=date(2026, 9, 1),
        expected_date=None,
        notes="",
        lines=[APLine("Supplies", acct("5200"), D(3), D(amount) / 3)],
    )
    ap.issue_po(db, actor, po.id)
    ap.receive_po(db, actor, po.id, received_on=date(2026, 9, 3))
    return po


def test_three_way_matched_bill_auto_approves_and_posts(
    db: Session, actor_for, vendor, acct
) -> None:  # type: ignore[no-untyped-def]
    accountant = actor_for("accountant")
    po = received_po(db, accountant, vendor, acct)
    bill = ap.create_bill(
        db,
        accountant,
        vendor_id=vendor.id,
        vendor_invoice_number="INV-1",
        bill_date=date(2026, 9, 5),
        due_date=None,
        purchase_order_id=po.id,
        lines=None,
        notes="",
    )
    assert bill.total == D("900.00") and bill.match_status == "matched"
    assert bill.due_date == date(2026, 10, 5)
    ap.submit_bill(db, accountant, bill.id)
    check_deferred(db)
    assert bill.status == "approved" and po.status == "closed"
    assert entry_lines(db, bill.approval_entry_id) == {
        "5200": (D("900.00"), D(0)),  # type: ignore[arg-type]
        "2010": (D(0), D("900.00")),
    }
    with pytest.raises(BusinessRuleViolation):
        ap.pay_bill(
            db,
            accountant,
            bill.id,
            amount=D("900.01"),
            paid_on=None,
            method="bank_transfer",
            reference="",
        )
    p1 = ap.pay_bill(
        db,
        accountant,
        bill.id,
        amount=D("400.00"),
        paid_on=date(2026, 9, 20),
        method="cheque",
        reference="CHQ-1",
    )
    assert bill.status == "partially_paid"
    assert entry_lines(db, p1.journal_entry_id) == {
        "2010": (D("400.00"), D(0)),  # type: ignore[arg-type]
        "1020": (D(0), D("400.00")),
    }
    ap.pay_bill(
        db,
        accountant,
        bill.id,
        amount=None,
        paid_on=date(2026, 9, 21),
        method="bank_transfer",
        reference="BACS-2",
    )
    assert bill.status == "paid" and bill.balance_due == D("0.00")
    with pytest.raises(Conflict):
        ap.create_bill(
            db,
            accountant,
            vendor_id=vendor.id,
            vendor_invoice_number="INV-1",
            bill_date=date(2026, 9, 5),
            due_date=None,
            purchase_order_id=po.id,
            lines=None,
            notes="",
        )


@pytest.mark.parametrize("case", ["not_received", "variance", "over_threshold"])
def test_bills_needing_approval(db: Session, actor_for, vendor, acct, case: str) -> None:  # type: ignore[no-untyped-def]
    accountant, finance = actor_for("accountant"), actor_for("finance")
    if case == "not_received":
        po = ap.create_po(
            db,
            accountant,
            vendor_id=vendor.id,
            order_date=date(2026, 9, 1),
            expected_date=None,
            notes="",
            lines=[APLine("x", acct("5200"), D(1), D("100.00"))],
        )
        ap.issue_po(db, accountant, po.id)
        po_id, lines = po.id, None
    elif case == "variance":
        po_id = received_po(db, accountant, vendor, acct).id
        lines = [APLine("Supplies", acct("5200"), D(1), D("950.00"))]
    else:
        po_id, lines = None, [APLine("Big order", acct("5200"), D(1), D("5000.01"))]
    bill = ap.create_bill(
        db,
        accountant,
        vendor_id=vendor.id,
        vendor_invoice_number=f"V-{case}",
        bill_date=date(2026, 9, 5),
        due_date=None,
        purchase_order_id=po_id,
        lines=lines,
        notes="",
    )
    ap.submit_bill(db, accountant, bill.id)
    assert bill.status == "pending_approval" and bill.approval_entry_id is None
    assert (
        bill.match_status
        == {"not_received": "not_received", "variance": "variance", "over_threshold": "no_po"}[case]
    )
    approval = db.scalars(
        select(Approval).where(Approval.kind == "vendor_bill", Approval.entity_id == bill.id)
    ).one()
    approvals.decide(db, finance, approval.id, approve=True, note="Verified with vendor")
    check_deferred(db)
    assert bill.status == "approved" and bill.approval_entry_id is not None


def test_payment_run_and_ap_reconciliation(db: Session, actor_for, vendor, acct) -> None:  # type: ignore[no-untyped-def]
    accountant = actor_for("accountant")
    bill = ap.create_bill(
        db,
        accountant,
        vendor_id=vendor.id,
        vendor_invoice_number="RUN-1",
        bill_date=date(2026, 9, 1),
        due_date=None,
        purchase_order_id=None,
        lines=[APLine("Service", acct("5500"), D(1), D("300.00"))],
        notes="",
    )
    ap.submit_bill(db, accountant, bill.id)
    ap.schedule_payment(db, accountant, bill.id, date(2026, 9, 25))
    assert not [
        p
        for p in ap.run_scheduled_payments(db, accountant, as_of=date(2026, 9, 24))
        if p.vendor_bill_id == bill.id
    ]
    paid = ap.run_scheduled_payments(db, accountant, as_of=date(2026, 9, 25))
    assert [p.amount for p in paid if p.vendor_bill_id == bill.id] == [D("300.00")]
    assert bill.status == "paid"
    open_bills = D(
        db.execute(
            text(
                "SELECT coalesce(sum(total - amount_paid), 0) FROM vendor_bills "
                "WHERE status IN ('approved','partially_paid')"
            )
        ).scalar()
    )
    assert -account_balance(db, "2010") == open_bills


def test_ap_validation(db: Session, actor_for, vendor, acct) -> None:  # type: ignore[no-untyped-def]
    accountant = actor_for("accountant")
    with pytest.raises(ValidationFailed):
        ap.create_po(
            db,
            accountant,
            vendor_id=vendor.id,
            order_date=date(2026, 9, 1),
            expected_date=None,
            notes="",
            lines=[APLine("x", acct("4110"), D(1), D("1"))],
        )  # revenue account
    with pytest.raises(ValidationFailed):
        ap.create_bill(
            db,
            accountant,
            vendor_id=vendor.id,
            vendor_invoice_number="X",
            bill_date=date(2026, 9, 1),
            due_date=None,
            purchase_order_id=None,
            lines=None,
            notes="",
        )
    draft = ap.create_po(
        db,
        accountant,
        vendor_id=vendor.id,
        order_date=date(2026, 9, 1),
        expected_date=None,
        notes="",
        lines=[APLine("x", acct("5200"), D(1), D("1"))],
    )
    with pytest.raises(Conflict):
        ap.receive_po(db, accountant, draft.id)
    ap.cancel_po(db, accountant, draft.id)
    with pytest.raises(BusinessRuleViolation):
        ap.create_bill(
            db,
            accountant,
            vendor_id=vendor.id,
            vendor_invoice_number="Y",
            bill_date=date(2026, 9, 1),
            due_date=None,
            purchase_order_id=draft.id,
            lines=None,
            notes="",
        )
    bill = ap.create_bill(
        db,
        accountant,
        vendor_id=vendor.id,
        vendor_invoice_number="Z",
        bill_date=date(2026, 9, 1),
        due_date=None,
        purchase_order_id=None,
        lines=[APLine("x", acct("5200"), D(1), D("10.00"))],
        notes="",
    )
    with pytest.raises(Conflict):
        ap.pay_bill(
            db, accountant, bill.id, amount=None, paid_on=None, method="bank_transfer", reference=""
        )
    ap.void_bill(db, accountant, bill.id, "Entered twice")
    assert bill.status == "void"


# ------------------------------------------------------------------ API


def test_approvals_api_inbox_and_policies(
    client: TestClient, login, db: Session, actor_for, patient, svc
) -> None:  # type: ignore[no-untyped-def]
    clerk = actor_for("billing")
    inv = issue(db, clerk, patient, svc, date(2026, 8, 1))
    db.flush()
    billing, finance = login("billing"), login("finance")
    wo = client.post(
        "/api/v1/ar/write-offs",
        headers=billing,
        json={"invoice_id": inv.id, "amount": "120.00", "reason": "Deceased, no estate"},
    )
    assert wo.status_code == 201 and wo.json()["status"] == "pending_approval"

    inbox = client.get("/api/v1/approvals", params={"status": "pending"}, headers=finance).json()
    item = next(
        a
        for a in inbox["items"]
        if a["kind"] == "write_off" and a["reference"] == wo.json()["write_off_number"]
    )
    assert item["can_decide"] is True
    mine = client.get("/api/v1/approvals", params={"scope": "mine"}, headers=billing).json()
    assert any(a["id"] == item["id"] and a["can_decide"] is False for a in mine["items"])
    assert (
        client.get("/api/v1/approvals", params={"scope": "all"}, headers=billing).status_code == 403
    )
    assert (
        client.get(f"/api/v1/approvals/{item['id']}", headers=login("insurance")).status_code == 403
    )
    assert client.get("/api/v1/approvals/pending-count", headers=finance).json()["pending"] >= 1

    assert (
        client.post(
            f"/api/v1/approvals/{item['id']}/decision", headers=billing, json={"approve": True}
        ).status_code
        == 403
    )
    commented = client.post(
        f"/api/v1/approvals/{item['id']}/comments",
        headers=finance,
        json={"body": "Confirmed with legal"},
    ).json()
    assert commented["comments"][0]["body"] == "Confirmed with legal"
    decided = client.post(
        f"/api/v1/approvals/{item['id']}/decision",
        headers=finance,
        json={"approve": True, "note": "OK"},
    )
    assert decided.status_code == 200 and decided.json()["status"] == "approved"
    posted = client.get(
        "/api/v1/ar/write-offs", params={"invoice_id": inv.id}, headers=finance
    ).json()
    assert posted["items"][0]["status"] == "posted"

    policies = client.get("/api/v1/approvals/policies", headers=login("accountant")).json()
    assert {p["kind"] for p in policies} == {
        "manual_journal",
        "refund",
        "write_off",
        "vendor_bill",
        "payroll_run",
    }
    assert (
        client.patch(
            "/api/v1/approvals/policies/refund",
            headers=login("accountant"),
            json={"threshold": "100.00"},
        ).status_code
        == 403
    )
    changed = client.patch(
        "/api/v1/approvals/policies/refund", headers=finance, json={"threshold": "750.00"}
    )
    assert changed.json()["threshold"] == "750.00"


def test_ar_api(client: TestClient, login) -> None:  # type: ignore[no-untyped-def]
    finance = login("finance")
    aging = client.get(
        "/api/v1/ar/aging", params={"by": "patient", "as_of": "2026-11-30"}, headers=finance
    ).json()
    assert aging["buckets"] == ["0-30", "31-60", "61-90", "90+"]
    assert (
        client.get(
            "/api/v1/ar/aging", params={"by": "insurer"}, headers=login("auditor")
        ).status_code
        == 200
    )
    assert client.get("/api/v1/ar/aging", headers=login("admin")).status_code == 403
    run = client.post(
        "/api/v1/ar/dunning/run", headers=login("billing"), json={"as_of": "2026-11-30"}
    )
    assert run.status_code == 200
    assert (
        client.post("/api/v1/ar/dunning/run", headers=login("accountant"), json={}).status_code
        == 403
    )
    assert client.get("/api/v1/ar/dunning", headers=finance).status_code == 200


def test_payables_api_roles_masking_and_idempotent_payment(client: TestClient, login, acct) -> None:  # type: ignore[no-untyped-def]
    accountant = login("accountant")
    vendor = client.post(
        "/api/v1/vendors",
        headers=accountant,
        json={
            "code": "APIV",
            "name": "API Vendor",
            "bank_reference": "IBAN-998877665544",
            "default_expense_account_id": acct("5200"),
        },
    )
    assert vendor.status_code == 201
    assert vendor.json()["bank_reference"] == "IBAN-998877665544"
    masked = client.get(
        "/api/v1/vendors", params={"search": "API"}, headers=login("auditor")
    ).json()
    assert (
        masked["items"][0]["bank_reference"].endswith("5544")
        and "IBAN" not in masked["items"][0]["bank_reference"]
    )
    assert client.get("/api/v1/vendors", headers=login("billing")).status_code == 403
    assert (
        client.post(
            "/api/v1/vendors", headers=login("finance"), json={"code": "X", "name": "x"}
        ).status_code
        == 403
    )

    vid = vendor.json()["id"]
    po = client.post(
        "/api/v1/purchase-orders",
        headers=accountant,
        json={
            "vendor_id": vid,
            "order_date": "2026-09-01",
            "lines": [
                {
                    "description": "Gauze",
                    "account_id": acct("5200"),
                    "quantity": "10",
                    "unit_price": "12.00",
                }
            ],
        },
    ).json()
    assert po["total"] == "120.00" and po["status"] == "draft"
    client.post(f"/api/v1/purchase-orders/{po['id']}/issue", headers=accountant)
    received = client.post(f"/api/v1/purchase-orders/{po['id']}/receive", headers=accountant).json()
    assert received["status"] == "received" and received["lines"][0]["received_quantity"] == "10.00"
    bill = client.post(
        "/api/v1/vendor-bills",
        headers=accountant,
        json={
            "vendor_id": vid,
            "vendor_invoice_number": "API-1",
            "bill_date": "2026-09-04",
            "purchase_order_id": po["id"],
        },
    ).json()
    assert bill["match_status"] == "matched" and bill["po_number"] == po["po_number"]
    approved = client.post(f"/api/v1/vendor-bills/{bill['id']}/submit", headers=accountant).json()
    assert approved["status"] == "approved"

    key = {**accountant, "Idempotency-Key": "vendor-pay-0001"}
    body = {"paid_on": "2026-09-10", "method": "bank_transfer", "reference": "BACS-9"}
    first = client.post(f"/api/v1/vendor-bills/{bill['id']}/pay", headers=key, json=body)
    retry = client.post(f"/api/v1/vendor-bills/{bill['id']}/pay", headers=key, json=body)
    assert first.status_code == retry.status_code == 201 and first.json() == retry.json()
    after = client.get(f"/api/v1/vendor-bills/{bill['id']}", headers=login("finance")).json()
    assert after["status"] == "paid" and after["amount_paid"] == "120.00"
    pays = client.get(
        "/api/v1/vendor-payments", params={"bill_id": bill["id"]}, headers=accountant
    ).json()
    assert pays["total"] == 1


def test_vendor_updates_and_bill_rejection(db: Session, actor_for, vendor, acct) -> None:  # type: ignore[no-untyped-def]
    accountant, finance = actor_for("accountant"), actor_for("finance")
    updated = ap.update_vendor(
        db,
        accountant,
        vendor.id,
        name="Renamed Vendor",
        email="a@b.example",
        bank_reference=None,
        payment_terms_days=45,
        is_active=None,
    )
    assert (updated.name, updated.payment_terms_days) == ("Renamed Vendor", 45)
    with pytest.raises(ValidationFailed):
        ap.update_vendor(
            db,
            accountant,
            vendor.id,
            name=None,
            email=None,
            bank_reference=None,
            payment_terms_days=365,
            is_active=None,
        )
    bill = ap.create_bill(
        db,
        accountant,
        vendor_id=vendor.id,
        vendor_invoice_number="REJ-1",
        bill_date=date(2026, 9, 1),
        due_date=None,
        purchase_order_id=None,
        lines=[APLine("Consulting", acct("5800"), D(1), D("9000.00"))],
        notes="",
    )
    ap.submit_bill(db, accountant, bill.id)
    approval = db.scalars(
        select(Approval).where(Approval.kind == "vendor_bill", Approval.entity_id == bill.id)
    ).one()
    approvals.decide(db, finance, approval.id, approve=False, note="Not contracted")
    assert bill.status == "rejected" and approval.status == "rejected"
    ap.void_bill(db, accountant, bill.id, "Rejected by finance")
    ap.update_vendor(
        db,
        accountant,
        vendor.id,
        name=None,
        email=None,
        bank_reference=None,
        payment_terms_days=None,
        is_active=False,
    )
    with pytest.raises(BusinessRuleViolation):
        ap.create_po(
            db,
            accountant,
            vendor_id=vendor.id,
            order_date=date(2026, 9, 1),
            expected_date=None,
            notes="",
            lines=[APLine("x", acct("5200"), D(1), D("1"))],
        )
    with pytest.raises(Conflict):
        ap.create_vendor(
            db,
            accountant,
            code="TESTV",
            name="dup",
            email="",
            tax_id="",
            bank_reference="",
            payment_terms_days=30,
            default_expense_account_id=None,
        )


def test_vendor_patch_api(client: TestClient, login) -> None:  # type: ignore[no-untyped-def]
    accountant = login("accountant")
    v = client.post(
        "/api/v1/vendors", headers=accountant, json={"code": "PATCHV", "name": "P"}
    ).json()
    resp = client.patch(f"/api/v1/vendors/{v['id']}", headers=accountant, json={"is_active": False})
    assert resp.status_code == 200 and resp.json()["is_active"] is False
    assert (
        client.patch(
            f"/api/v1/vendors/{v['id']}", headers=login("finance"), json={"name": "x"}
        ).status_code
        == 403
    )


# ------------------------------------------------------------------ as-of (historical) aging


def test_aging_is_historical_and_ties_to_gl(db: Session, actor_for, patient, svc, acct) -> None:  # type: ignore[no-untyped-def]
    from app.repositories import ar as ar_repo
    from app.services import payments

    clerk = actor_for("billing")
    inv = issue(db, clerk, patient, svc, date(2026, 8, 1))  # 120.00
    payments.record_payment(
        db,
        clerk,
        invoice_id=inv.id,
        method="cash",
        amount=D("50.00"),
        received_on=date(2026, 9, 15),
        reference="",
        notes="",
    )
    ar.request_write_off(db, clerk, invoice_id=inv.id, amount=D("20.00"), reason="Goodwill")
    wo = db.scalars(select(WriteOff).where(WriteOff.invoice_id == inv.id)).one()
    ar.approve_write_off(db, actor_for("finance"), wo.id, "ok", on=date(2026, 10, 10))
    # A manual journal touching AR cannot be traced to an invoice: it is shown as unallocated.
    ledger.post_entry(
        db,
        SYSTEM_ACTOR,
        ledger.EntryDraft(
            entry_date=date(2026, 9, 1),
            memo="Manual AR correction",
            source_type="manual",
            lines=[
                LineInput(acct("1100"), debit=D("7.00")),
                LineInput(acct("4950"), credit=D("7.00")),
            ],
        ),
    )
    check_deferred(db)

    def mine(as_of: date):  # type: ignore[no-untyped-def]
        report = ar.aging(db, by="patient", as_of=as_of)
        assert report.total == ar_repo.gl_balance(db, "1100", as_of)  # always ties to the GL
        row = next((r for r in report.rows if r.party_id == patient.id), None)
        unallocated = next((r for r in report.rows if r.party_id == 0), None)
        return row, unallocated

    before_payment, unalloc = mine(date(2026, 9, 10))
    assert before_payment is not None and before_payment.total == D("120.00")
    assert before_payment.buckets["31-60"] == D("120.00")  # 40 days old
    assert (
        unalloc is not None
        and unalloc.total == D("7.00")
        and unalloc.name.startswith("Unallocated")
    )
    after_payment, _ = mine(date(2026, 9, 20))
    assert after_payment is not None and after_payment.total == D("70.00")
    after_write_off, _ = mine(date(2026, 10, 15))
    assert after_write_off is not None and after_write_off.total == D("50.00")
    assert after_write_off.buckets["61-90"] == D("50.00")  # 75 days old
    before_invoice, _ = mine(date(2026, 7, 31))
    assert before_invoice is None


def test_insurer_aging_as_of_dates(db: Session, actor_for, patient, svc) -> None:  # type: ignore[no-untyped-def]
    from app.models.insurance import Insurer
    from app.repositories import ar as ar_repo
    from app.services import claims, insurance, mock_insurer, remittances

    officer = actor_for("insurance")
    insurer = db.scalars(select(Insurer).where(Insurer.code == "SUN")).one()
    policy = insurance.create_policy(
        db,
        SYSTEM_ACTOR,
        patient_id=patient.id,
        insurer_id=insurer.id,
        policy_number="AGE-1",
        plan_name="P",
        coverage_percent=D("100"),
        copay=D("0"),
        deductible=D("0"),
        annual_limit=D("100000"),
        effective_from=date(2026, 1, 1),
        effective_to=None,
    )
    inv = issue(db, actor_for("billing"), patient, svc, date(2026, 9, 1))
    claim = claims.create_claim(db, officer, invoice_id=inv.id, policy_id=policy.id)
    claims.submit_claim(db, officer, claim.id, on=date(2026, 9, 2))
    mock_insurer.adjudicate(db, officer, claim.id, outcome="approve", on=date(2026, 9, 20))
    rem = remittances.import_remittance(
        db,
        officer,
        insurer_id=insurer.id,
        reference="EFT-AGE",
        payment_date=date(2026, 10, 1),
        filename="x.csv",
        csv_text=f"claim_number,paid_amount\n{claim.claim_number},120.00\n",
    )
    remittances.post_remittance(db, officer, rem.id)
    check_deferred(db)

    for as_of, expected in ((date(2026, 9, 15), D("120.00")), (date(2026, 10, 2), None)):
        report = ar.aging(db, by="insurer", as_of=as_of)
        assert report.total == ar_repo.gl_balance(db, "1110", as_of)
        row = next((r for r in report.rows if r.party_id == insurer.id), None)
        assert (row.total if row else None) == expected


# ------------------------------------------------------------------ voiding approved bills


def test_void_approved_bill_reverses_and_reopens_po(db: Session, actor_for, vendor, acct) -> None:  # type: ignore[no-untyped-def]
    accountant, finance = actor_for("accountant"), actor_for("finance")
    po = received_po(db, accountant, vendor, acct)
    bill = ap.create_bill(
        db,
        accountant,
        vendor_id=vendor.id,
        vendor_invoice_number="VOID-1",
        bill_date=date(2026, 9, 5),
        due_date=None,
        purchase_order_id=po.id,
        lines=None,
        notes="",
    )
    ap.submit_bill(db, accountant, bill.id)
    ap.schedule_payment(db, accountant, bill.id, date(2026, 10, 1))
    assert bill.status == "approved" and po.status == "closed"
    with pytest.raises(PermissionDenied) as exc:
        ap.void_bill(db, accountant, bill.id, "Wrong vendor")
    assert exc.value.code == "finance_manager_required"
    with pytest.raises(ValidationFailed):
        ap.void_bill(db, finance, bill.id, " ")

    ap.void_bill(db, finance, bill.id, "Invoice issued to the wrong hospital")
    check_deferred(db)
    assert bill.status == "void" and bill.scheduled_payment_date is None
    original, reversal = (
        entry_lines(db, bill.approval_entry_id),
        entry_lines(db, bill.void_entry_id),
    )  # type: ignore[arg-type]
    assert {k: (c, d) for k, (d, c) in original.items()} == reversal
    assert po.status == "received"  # can be billed again
    rebill = ap.create_bill(
        db,
        accountant,
        vendor_id=vendor.id,
        vendor_invoice_number="VOID-2",
        bill_date=date(2026, 9, 6),
        due_date=None,
        purchase_order_id=po.id,
        lines=None,
        notes="",
    )
    assert rebill.match_status == "matched"
    # The voided bill is no longer picked up by the scheduled payment run.
    paid = ap.run_scheduled_payments(db, accountant, as_of=date(2026, 10, 1))
    assert all(p.vendor_bill_id != bill.id for p in paid)


def test_paid_bill_cannot_be_voided(
    client: TestClient, login, db: Session, actor_for, vendor, acct
) -> None:  # type: ignore[no-untyped-def]
    accountant = actor_for("accountant")
    bill = ap.create_bill(
        db,
        accountant,
        vendor_id=vendor.id,
        vendor_invoice_number="PAIDV",
        bill_date=date(2026, 9, 5),
        due_date=None,
        purchase_order_id=None,
        lines=[APLine("x", acct("5200"), D(1), D("100.00"))],
        notes="",
    )
    ap.submit_bill(db, accountant, bill.id)
    ap.pay_bill(
        db,
        accountant,
        bill.id,
        amount=D("10.00"),
        paid_on=date(2026, 9, 6),
        method="bank_transfer",
        reference="",
    )
    db.flush()
    resp = client.post(
        f"/api/v1/vendor-bills/{bill.id}/void",
        headers=login("finance"),
        json={"reason": "duplicate"},
    )
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "has_payments"
    assert (
        client.post(
            f"/api/v1/vendor-bills/{bill.id}/void", headers=login("billing"), json={"reason": "x"}
        ).status_code
        == 403
    )
