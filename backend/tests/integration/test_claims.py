"""Claims: generation, state machine, adjudication, appeals, closing, remittances, ledger."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, Conflict, ValidationFailed
from app.models.billing import InvoiceStatus
from app.models.insurance import ClaimStatus, Insurer, Policy
from app.models.patients import Patient
from app.services import claims, insurance, invoices, mock_insurer, payments, remittances
from app.services.audit import SYSTEM_ACTOR
from app.services.claims import TRANSITIONS, can_transition
from app.services.invoices import LineSpec
from tests.conftest import check_deferred
from tests.integration.test_billing import entry_lines

D = Decimal
ON = date(2026, 9, 1)
ALL = [s.value for s in ClaimStatus]


# ------------------------------------------------------------------ fixtures


@pytest.fixture
def insured(db: Session) -> tuple[Patient, Policy]:
    """A fresh patient with a clean policy: 80%, copay 20, deductible 100, limit 10,000."""
    patient = db.scalars(select(Patient).order_by(Patient.id)).first()
    assert patient is not None
    insurer = db.scalars(select(Insurer).where(Insurer.code == "CRS")).one()
    policy = insurance.create_policy(
        db,
        SYSTEM_ACTOR,
        patient_id=patient.id,
        insurer_id=insurer.id,
        policy_number="TEST-0000001",
        plan_name="Test plan",
        coverage_percent=D("80"),
        copay=D("20.00"),
        deductible=D("100.00"),
        annual_limit=D("10000.00"),
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
    )
    for other in db.scalars(
        select(Policy).where(Policy.patient_id == patient.id, Policy.id != policy.id)
    ).all():
        other.is_active = False
    db.flush()
    return patient, policy


@pytest.fixture
def svc(db: Session):  # type: ignore[no-untyped-def]
    from app.models.catalog import Service

    ids = {s.code: s.id for s in db.scalars(select(Service)).all()}
    return lambda code: ids[code]


def issued_invoice(db: Session, actor, patient: Patient, svc, code: str = "RAD-CT-HEAD"):  # type: ignore[no-untyped-def]
    inv = invoices.create_invoice(
        db,
        actor,
        patient_id=patient.id,
        visit_id=None,
        price_list_id=None,
        notes="",
        lines=[
            LineSpec(quantity=D(1), service_id=svc(code), service_date=ON),
            LineSpec(quantity=D(1), service_id=svc("LAB-CBC"), service_date=ON),
        ],
    )
    invoices.issue_invoice(db, actor, inv.id, invoice_date=ON)
    return inv


def submitted_claim(db: Session, actor_for, insured, svc):  # type: ignore[no-untyped-def]
    patient, policy = insured
    inv = issued_invoice(db, actor_for("billing"), patient, svc)
    claim = claims.create_claim(db, actor_for("billing"), invoice_id=inv.id, policy_id=policy.id)
    claims.submit_claim(db, actor_for("insurance"), claim.id, on=ON)
    return inv, claim


def ar_insurers_balance(db: Session) -> Decimal:
    return D(
        db.execute(
            text(
                "SELECT coalesce(sum(l.debit) - sum(l.credit), 0) FROM journal_lines l "
                "JOIN accounts a ON a.id = l.account_id WHERE a.code = '1110'"
            )
        ).scalar()
    )


def pending_total(db: Session) -> Decimal:
    return D(db.execute(text("SELECT coalesce(sum(insurance_pending), 0) FROM invoices")).scalar())


# ------------------------------------------------------------------ state machine


@pytest.mark.parametrize("current", ALL)
@pytest.mark.parametrize("target", ALL)
def test_state_machine_table(current: str, target: str) -> None:
    allowed = {
        "draft": {"submitted", "cancelled"},
        "submitted": {"under_review"},
        "under_review": {"approved", "partially_approved", "denied"},
        "approved": {"paid"},
        "partially_approved": {"paid"},
        "denied": {"appealed", "closed"},
        "appealed": {"under_review"},
        "paid": set(),
        "closed": set(),
        "cancelled": set(),
    }
    assert can_transition(current, target) is (target in allowed[current])
    assert set(TRANSITIONS[current]) == allowed[current]


def test_service_rejects_invalid_transitions(db: Session, actor_for, insured, svc) -> None:  # type: ignore[no-untyped-def]
    officer = actor_for("insurance")
    patient, policy = insured
    inv = issued_invoice(db, actor_for("billing"), patient, svc)
    claim = claims.create_claim(db, officer, invoice_id=inv.id, policy_id=policy.id)
    for bad in (
        lambda: claims.appeal_claim(db, officer, claim.id, "x"),
        lambda: claims.close_claim(db, officer, claim.id, "x"),
        lambda: claims.record_decision(db, officer, claim.id, outcome="approve"),
        lambda: mock_insurer.adjudicate(db, officer, claim.id),
    ):
        with pytest.raises(Conflict) as exc:
            bad()
        assert exc.value.code == "invalid_transition"
    claims.submit_claim(db, officer, claim.id, on=ON)
    with pytest.raises(Conflict):
        claims.submit_claim(db, officer, claim.id, on=ON)
    with pytest.raises(Conflict):
        claims.cancel_claim(db, officer, claim.id, "too late")


# ------------------------------------------------------------------ creation & coverage


def test_claim_splits_invoice_and_allocates_lines(db: Session, actor_for, insured, svc) -> None:  # type: ignore[no-untyped-def]
    patient, policy = insured
    inv = issued_invoice(db, actor_for("billing"), patient, svc)  # 780 + 38 = 818
    claim = claims.create_claim(db, actor_for("billing"), invoice_id=inv.id, policy_id=policy.id)
    # 818 - 20 copay = 798; - 100 deductible = 698; 80% = 558.40
    assert (claim.billed_amount, claim.copay_amount, claim.deductible_amount) == (
        D("818.00"),
        D("20.00"),
        D("100.00"),
    )
    assert (claim.insurer_amount, claim.patient_amount) == (D("558.40"), D("259.60"))
    assert sum(ln.insurer_amount for ln in claim.lines) == claim.insurer_amount
    assert claim.status == ClaimStatus.DRAFT and claim.events[0].event_type == "created"

    # The deductible is now met for 2026: a second claim applies none.
    inv2 = issued_invoice(db, actor_for("billing"), patient, svc, code="RAD-US-ABD")
    pv = claims.preview(db, invoice_id=inv2.id, policy_id=policy.id)
    assert pv.deductible_met == D("100.00") and pv.result.deductible == D("0.00")


def test_claim_creation_guards(db: Session, actor_for, insured, svc) -> None:  # type: ignore[no-untyped-def]
    clerk = actor_for("billing")
    patient, policy = insured
    draft = invoices.create_invoice(
        db,
        clerk,
        patient_id=patient.id,
        visit_id=None,
        price_list_id=None,
        notes="",
        lines=[LineSpec(quantity=D(1), service_id=svc("OPD-FU"), service_date=ON)],
    )
    with pytest.raises(Conflict):
        claims.create_claim(db, clerk, invoice_id=draft.id, policy_id=policy.id)
    inv = issued_invoice(db, clerk, patient, svc)
    other_policy = db.scalars(select(Policy).where(Policy.patient_id != patient.id)).first()
    with pytest.raises(ValidationFailed):
        claims.create_claim(db, clerk, invoice_id=inv.id, policy_id=other_policy.id)  # type: ignore[union-attr]
    claims.create_claim(db, clerk, invoice_id=inv.id, policy_id=policy.id)
    with pytest.raises(Conflict) as exc:
        claims.create_claim(db, clerk, invoice_id=inv.id, policy_id=policy.id)
    assert exc.value.code == "claim_exists"
    policy.effective_to = date(2026, 8, 31)
    db.flush()
    inv3 = issued_invoice(db, clerk, patient, svc)
    with pytest.raises(BusinessRuleViolation) as exc2:
        claims.create_claim(db, clerk, invoice_id=inv3.id, policy_id=policy.id)
    assert exc2.value.code == "policy_not_active"


def test_insurer_share_capped_by_what_the_patient_still_owes(
    db: Session, actor_for, insured, svc
) -> None:  # type: ignore[no-untyped-def]
    clerk = actor_for("billing")
    patient, policy = insured
    inv = issued_invoice(db, clerk, patient, svc)
    payments.record_payment(
        db,
        clerk,
        invoice_id=inv.id,
        method="cash",
        amount=D("700.00"),
        received_on=ON,
        reference="",
        notes="",
    )
    claim = claims.create_claim(db, clerk, invoice_id=inv.id, policy_id=policy.id)
    assert claim.insurer_amount == D("118.00")  # only 118.00 is still collectible
    assert claim.insurer_amount + claim.patient_amount == claim.billed_amount


# ------------------------------------------------------------------ submit / adjudicate / ledger


def test_submit_moves_ar_and_caps_patient_payments(db: Session, actor_for, insured, svc) -> None:  # type: ignore[no-untyped-def]
    inv, claim = submitted_claim(db, actor_for, insured, svc)
    check_deferred(db)
    assert entry_lines(db, claim.transfer_entry_id) == {  # type: ignore[arg-type]
        "1110": (D("558.40"), D(0)),
        "1100": (D(0), D("558.40")),
    }
    assert inv.insurance_pending == D("558.40") and inv.patient_due == D("259.60")
    with pytest.raises(BusinessRuleViolation) as exc:
        payments.record_payment(
            db,
            actor_for("billing"),
            invoice_id=inv.id,
            method="cash",
            amount=D("259.61"),
            received_on=ON,
            reference="",
            notes="",
        )
    assert exc.value.code == "overpayment"
    with pytest.raises(BusinessRuleViolation) as exc2:
        invoices.void_invoice(db, actor_for("billing"), inv.id, "x")
    assert exc2.value.code == "has_claim"
    assert ar_insurers_balance(db) == pending_total(db)


def test_partial_approval_posts_contractual_adjustment(
    db: Session, actor_for, insured, svc
) -> None:  # type: ignore[no-untyped-def]
    officer = actor_for("insurance")
    inv, claim = submitted_claim(db, actor_for, insured, svc)
    mock_insurer.adjudicate(
        db, officer, claim.id, outcome="partial", approved_amount=D("400.00"), on=ON
    )
    check_deferred(db)
    assert claim.status == ClaimStatus.PARTIALLY_APPROVED and claim.approved_amount == D("400.00")
    assert claim.adjustment_amount == D("158.40") and claim.outstanding == D("400.00")
    assert inv.adjusted_amount == D("158.40") and inv.insurance_pending == D("400.00")
    assert [e.event_type for e in claim.events][-3:] == [
        "under_review",
        "partially_approved",
        "adjustment",
    ]
    assert ar_insurers_balance(db) == pending_total(db)


def test_denial_appeal_and_reapproval(db: Session, actor_for, insured, svc) -> None:  # type: ignore[no-untyped-def]
    officer = actor_for("insurance")
    _, claim = submitted_claim(db, actor_for, insured, svc)
    mock_insurer.adjudicate(db, officer, claim.id, outcome="deny", denial_code="CO-50", on=ON)
    assert claim.status == ClaimStatus.DENIED and claim.denial_code == "CO-50"
    with pytest.raises(ValidationFailed):
        claims.appeal_claim(db, officer, claim.id, "  ")
    claims.appeal_claim(db, officer, claim.id, "Records attached")
    assert claim.status == ClaimStatus.APPEALED and claim.appeal_count == 1
    mock_insurer.adjudicate(db, officer, claim.id, outcome="deny", denial_code="CO-16", on=ON)
    claims.appeal_claim(db, officer, claim.id, "Second appeal")
    mock_insurer.adjudicate(db, officer, claim.id, outcome="deny", denial_code="CO-16", on=ON)
    with pytest.raises(BusinessRuleViolation) as exc:
        claims.appeal_claim(db, officer, claim.id, "Third")
    assert exc.value.code == "appeal_limit"
    # Denials need a known code.
    _, fresh = submitted_claim(db, actor_for, insured, svc)
    with pytest.raises(ValidationFailed):
        mock_insurer.adjudicate(db, officer, fresh.id, outcome="deny", denial_code="NOPE")


def test_close_denied_claim_returns_balance_to_patient(
    db: Session, actor_for, insured, svc
) -> None:  # type: ignore[no-untyped-def]
    officer = actor_for("insurance")
    inv, claim = submitted_claim(db, actor_for, insured, svc)
    mock_insurer.adjudicate(db, officer, claim.id, outcome="deny", denial_code="PR-204", on=ON)
    closed = claims.close_claim(db, officer, claim.id, "Not covered", on=ON)
    check_deferred(db)
    assert closed.status == ClaimStatus.CLOSED
    assert inv.insurance_pending == D("0.00") and inv.patient_due == inv.total
    assert ar_insurers_balance(db) == pending_total(db)
    # The invoice can now be settled by the patient in full.
    payments.record_payment(
        db,
        actor_for("billing"),
        invoice_id=inv.id,
        method="card",
        amount=inv.total,
        received_on=ON,
        reference="4242",
        notes="",
    )
    assert inv.status == InvoiceStatus.PAID


def test_mock_insurer_is_deterministic_and_batches(db: Session, actor_for, insured, svc) -> None:  # type: ignore[no-untyped-def]
    _, claim = submitted_claim(db, actor_for, insured, svc)
    first, second = mock_insurer.decide(claim), mock_insurer.decide(claim)
    assert first == second
    done = mock_insurer.run_batch(db, actor_for("insurance"))
    assert claim.id in [c.id for c in done]
    assert claim.status in ("approved", "partially_approved", "denied")


# ------------------------------------------------------------------ remittances


def _approved(db: Session, actor_for, insured, svc, code: str = "RAD-CT-HEAD"):  # type: ignore[no-untyped-def]
    patient, policy = insured
    inv = issued_invoice(db, actor_for("billing"), patient, svc, code=code)
    claim = claims.create_claim(db, actor_for("billing"), invoice_id=inv.id, policy_id=policy.id)
    officer = actor_for("insurance")
    claims.submit_claim(db, officer, claim.id, on=ON)
    mock_insurer.adjudicate(db, officer, claim.id, outcome="approve", on=ON)
    return inv, claim


def test_remittance_reconciliation_flags_and_posting(db: Session, actor_for, insured, svc) -> None:  # type: ignore[no-untyped-def]
    officer = actor_for("insurance")
    inv1, c1 = _approved(db, actor_for, insured, svc)
    inv2, c2 = _approved(db, actor_for, insured, svc, code="RAD-US-ABD")
    _, draft = (
        insured[0],
        claims.create_claim(
            db,
            officer,
            invoice_id=issued_invoice(db, actor_for("billing"), insured[0], svc, "LAB-LIPID").id,
            policy_id=insured[1].id,
        ),
    )
    csv_text = "\n".join(
        [
            "claim_number,paid_amount,remark",
            f"{c1.claim_number},{c1.approved_amount:.2f},full",
            f"{c2.claim_number},{c2.approved_amount - D('50.00'):.2f},short",
            f"{c1.claim_number},10.00,duplicate after full payment",
            "CLM-999999,99.00,unknown",
            f"{draft.claim_number},5.00,not approved",
        ]
    )
    remittance = remittances.import_remittance(
        db,
        officer,
        insurer_id=c1.insurer_id,
        reference="EFT-TEST-1",
        payment_date=date(2026, 9, 15),
        filename="era.csv",
        csv_text=csv_text,
    )
    statuses = [ln.match_status for ln in remittance.lines]
    assert statuses == ["matched", "short_paid", "overpaid", "unmatched", "unmatched"]
    assert remittance.lines[1].message.startswith("Short paid by 50.00")
    assert c1.paid_amount == 0  # nothing moves on import

    with pytest.raises(Conflict):
        remittances.import_remittance(
            db,
            officer,
            insurer_id=c1.insurer_id,
            reference="EFT-TEST-1",
            payment_date=date(2026, 9, 15),
            filename="x",
            csv_text=csv_text,
        )

    remittances.post_remittance(db, officer, remittance.id)
    check_deferred(db)
    assert remittance.status == "posted"
    assert remittance.posted_amount == c1.approved_amount + c2.approved_amount - D("50.00")
    assert c1.status == ClaimStatus.PAID and c2.status == ClaimStatus.APPROVED
    assert c2.outstanding == D("50.00")
    pay_entry = entry_lines(
        db,
        db.execute(
            text("SELECT journal_entry_id FROM payments WHERE id = :p"),
            {"p": remittance.lines[0].payment_id},
        ).scalar(),
    )
    assert pay_entry == {"1020": (c1.approved_amount, D(0)), "1110": (D(0), c1.approved_amount)}
    assert inv1.insurance_pending == D("0.00")
    with pytest.raises(Conflict):
        remittances.post_remittance(db, officer, remittance.id)

    # Accept the short pay: the 50.00 becomes a contractual adjustment and the claim is paid.
    claims.accept_short_pay(db, officer, c2.id, "Fee schedule", on=date(2026, 9, 16))
    check_deferred(db)
    assert c2.status == ClaimStatus.PAID and c2.adjustment_amount == D("50.00")
    assert inv2.insurance_pending == D("0.00")
    assert ar_insurers_balance(db) == pending_total(db)


@pytest.mark.parametrize(
    ("csv_text", "code"),
    [
        ("claim,amount\nCLM-1,1.00", "invalid_csv_header"),
        ("claim_number,paid_amount\nCLM-1,abc", "invalid_csv"),
        ("claim_number,paid_amount\nCLM-1,1.005", "invalid_csv"),
        ("claim_number,paid_amount\nCLM-1,-5.00", "invalid_csv"),
        ("claim_number,paid_amount\n", "empty_csv"),
    ],
)
def test_remittance_csv_validation(csv_text: str, code: str) -> None:
    with pytest.raises(ValidationFailed) as exc:
        remittances.parse_csv(csv_text)
    assert exc.value.code == code


def test_remittance_total_mismatch_and_other_insurer(db: Session, actor_for, insured, svc) -> None:  # type: ignore[no-untyped-def]
    officer = actor_for("insurance")
    _, claim = _approved(db, actor_for, insured, svc)
    text_ = f"claim_number,paid_amount\n{claim.claim_number},{claim.approved_amount:.2f}\n"
    with pytest.raises(ValidationFailed) as exc:
        remittances.import_remittance(
            db,
            officer,
            insurer_id=claim.insurer_id,
            reference="EFT-T2",
            payment_date=ON,
            filename="x",
            csv_text=text_,
            expected_total=D("1.00"),
        )
    assert exc.value.code == "total_mismatch"
    other = db.scalars(select(Insurer).where(Insurer.id != claim.insurer_id)).first()
    rem = remittances.import_remittance(
        db,
        officer,
        insurer_id=other.id,
        reference="EFT-T3",  # type: ignore[union-attr]
        payment_date=ON,
        filename="x",
        csv_text=text_,
    )
    assert rem.lines[0].match_status == "unmatched"
    assert "another insurer" in rem.lines[0].message
    with pytest.raises(BusinessRuleViolation):
        remittances.post_remittance(db, officer, rem.id)


def test_claim_events_are_append_only(db: Session, actor_for, insured, svc) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy.exc import DBAPIError

    _, claim = submitted_claim(db, actor_for, insured, svc)
    db.flush()
    nested = db.begin_nested()
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("UPDATE claim_events SET note = 'x' WHERE claim_id = :c"), {"c": claim.id})
    nested.rollback()
    nested = db.begin_nested()
    with pytest.raises(DBAPIError, match="cannot be deleted"):
        db.execute(text("DELETE FROM claims WHERE id = :c"), {"c": claim.id})
    nested.rollback()


# ------------------------------------------------------------------ API


def test_claim_api_roles_preview_masking_and_attachments(
    client: TestClient, login, db: Session, insured, svc
) -> None:  # type: ignore[no-untyped-def]
    patient, policy = insured
    billing, officer = login("billing"), login("insurance")
    inv = client.post(
        "/api/v1/invoices",
        headers=billing,
        json={
            "patient_id": patient.id,
            "lines": [
                {"service_id": svc("RAD-MRI-KNEE"), "quantity": "1", "service_date": "2026-09-05"}
            ],
        },
    ).json()
    client.post(
        f"/api/v1/invoices/{inv['id']}/issue", headers=billing, json={"invoice_date": "2026-09-05"}
    )

    pv = client.get(
        "/api/v1/claims/preview",
        params={"invoice_id": inv["id"], "policy_id": policy.id},
        headers=billing,
    ).json()
    assert pv["billed"] == "1150.00" and pv["insurer_amount"] == "824.00"  # (1150-20-100)*80%

    assert (
        client.post(
            "/api/v1/claims",
            headers=login("accountant"),
            json={"invoice_id": inv["id"], "policy_id": policy.id},
        ).status_code
        == 403
    )
    claim = client.post(
        "/api/v1/claims", headers=billing, json={"invoice_id": inv["id"], "policy_id": policy.id}
    )
    assert claim.status_code == 201, claim.text
    cid = claim.json()["id"]
    assert claim.json()["allowed_transitions"] == ["cancelled", "submitted"]
    assert claim.json()["policy_number"] == "TEST-0000001"

    # Billing clerks draft; only insurance officers submit.
    assert client.post(f"/api/v1/claims/{cid}/submit", headers=billing).status_code == 403
    submitted = client.post(f"/api/v1/claims/{cid}/submit", headers=officer)
    assert submitted.json()["status"] == "submitted"
    bad = client.post(f"/api/v1/claims/{cid}/appeal", headers=officer, json={"note": "x"})
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "invalid_transition"
    assert bad.json()["error"]["details"]["allowed"] == ["under_review"]

    denied = client.post(
        f"/api/v1/claims/{cid}/adjudicate",
        headers=officer,
        json={"outcome": "deny", "denial_code": "CO-50"},
    ).json()
    assert denied["status"] == "denied"
    assert denied["denial_description"].startswith("Not deemed a medical necessity")

    pdf = b"%PDF-1.4 appeal letter"
    up = client.post(
        f"/api/v1/claims/{cid}/attachments",
        headers=officer,
        files={"file": ("appeal letter.pdf", pdf, "application/pdf")},
    )
    assert up.status_code == 201 and up.json()["size_bytes"] == len(pdf)
    fake = client.post(
        f"/api/v1/claims/{cid}/attachments",
        headers=officer,
        files={"file": ("x.pdf", b"not a pdf", "application/pdf")},
    )
    assert fake.json()["error"]["code"] == "file_type_mismatch"
    exe = client.post(
        f"/api/v1/claims/{cid}/attachments",
        headers=officer,
        files={"file": ("x.exe", b"MZ", "application/x-msdownload")},
    )
    assert exe.json()["error"]["code"] == "unsupported_file_type"
    dl = client.get(f"/api/v1/claims/{cid}/attachments/{up.json()['id']}", headers=login("auditor"))
    assert dl.content == pdf
    assert dl.headers["content-disposition"].startswith("attachment;")
    assert dl.headers["x-content-type-options"] == "nosniff"

    appealed = client.post(
        f"/api/v1/claims/{cid}/appeal", headers=officer, json={"note": "Letter attached"}
    ).json()
    assert appealed["status"] == "appealed"
    assert [e["event_type"] for e in appealed["events"]] == [
        "created",
        "submitted",
        "under_review",
        "denied",
        "attachment",
        "appealed",
    ]

    finance_view = client.get(f"/api/v1/claims/{cid}", headers=login("finance")).json()
    assert (
        finance_view["policy_number"].endswith("0001")
        and "TEST" not in finance_view["policy_number"]
    )
    counts = client.get("/api/v1/claims/counts", headers=login("finance")).json()["counts"]
    assert counts.get("appealed", 0) >= 1
    listed = client.get(
        "/api/v1/claims", params={"status": "appealed", "search": patient.mrn}, headers=officer
    ).json()
    assert any(c["id"] == cid for c in listed["items"])
    batch = client.post("/api/v1/claims/run-mock-insurer", headers=officer).json()
    assert batch["processed"] >= 1


def test_remittance_api_upload_and_idempotent_post(
    client: TestClient, login, db: Session, actor_for, insured, svc
) -> None:  # type: ignore[no-untyped-def]
    _, claim = _approved(db, actor_for, insured, svc)
    db.flush()
    officer = login("insurance")
    body = f"claim_number,paid_amount,remark\n{claim.claim_number},{claim.approved_amount:.2f},ok\n"
    resp = client.post(
        "/api/v1/remittances",
        headers=officer,
        data={
            "insurer_id": str(claim.insurer_id),
            "reference": "EFT-API-1",
            "payment_date": "2026-09-20",
            "expected_total": f"{claim.approved_amount:.2f}",
        },
        files={"file": ("era.csv", body.encode(), "text/csv")},
    )
    assert resp.status_code == 201, resp.text
    rem = resp.json()
    assert rem["counts"]["matched"] == 1 and rem["status"] == "imported"
    assert (
        client.post(f"/api/v1/remittances/{rem['id']}/post", headers=login("finance")).status_code
        == 403
    )
    key = {**officer, "Idempotency-Key": "remit-post-0001"}
    first = client.post(f"/api/v1/remittances/{rem['id']}/post", headers=key)
    retry = client.post(f"/api/v1/remittances/{rem['id']}/post", headers=key)
    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json() and first.json()["status"] == "posted"
    claim_after = client.get(f"/api/v1/claims/{claim.id}", headers=officer).json()
    assert claim_after["status"] == "paid"
    listed = client.get("/api/v1/remittances", headers=login("accountant")).json()
    assert listed["total"] >= 1


def test_insurers_and_policies_api(client: TestClient, login, db: Session) -> None:  # type: ignore[no-untyped-def]
    officer = login("insurance")
    insurers = client.get("/api/v1/insurers", headers=login("finance")).json()
    assert {i["code"] for i in insurers} >= {"CRS", "MER", "SUN", "SHP"}
    bad = client.post(
        "/api/v1/insurers",
        headers=officer,
        json={
            "code": "BAD",
            "name": "Bad",
            "approval_rate": "0.5",
            "partial_rate": "0.5",
            "denial_rate": "0.5",
        },
    )
    assert bad.status_code == 422
    ok = client.post(
        "/api/v1/insurers", headers=officer, json={"code": "NEWP", "name": "New Payer"}
    )
    assert ok.status_code == 201
    assert (
        client.post(
            "/api/v1/insurers", headers=login("billing"), json={"code": "NOPE", "name": "x"}
        ).status_code
        == 403
    )
    patient = db.scalars(select(Patient).order_by(Patient.id.desc())).first()
    pol = client.post(
        "/api/v1/policies",
        headers=login("billing"),
        json={
            "patient_id": patient.id,
            "insurer_id": ok.json()["id"],
            "policy_number": "NEWP-123",  # type: ignore[union-attr]
            "plan_name": "Basic",
            "coverage_percent": "75",
            "annual_limit": "5000.00",
            "effective_from": "2026-01-01",
        },
    )
    assert pol.status_code == 201
    dup = client.post(
        "/api/v1/policies",
        headers=officer,
        json={
            "patient_id": patient.id,
            "insurer_id": ok.json()["id"],
            "policy_number": "NEWP-123",  # type: ignore[union-attr]
            "plan_name": "Basic",
            "coverage_percent": "75",
            "annual_limit": "5000.00",
            "effective_from": "2026-01-01",
        },
    )
    assert dup.status_code == 409
    masked = client.get(
        "/api/v1/policies",
        params={"patient_id": patient.id},  # type: ignore[union-attr]
        headers=login("accountant"),
    ).json()
    assert all("NEWP" not in p["policy_number"] for p in masked["items"])
    deactivated = client.post(
        f"/api/v1/policies/{pol.json()['id']}/status", headers=officer, json={"is_active": False}
    )
    assert deactivated.json()["is_active"] is False
    codes = client.get("/api/v1/denial-codes", headers=officer).json()
    assert {c["code"] for c in codes} >= {"CO-50", "PR-204"}
