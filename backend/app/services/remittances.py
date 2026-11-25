"""Remittance (insurer payment advice) import, reconciliation and posting.

CSV format (header row required; extra columns ignored):

    claim_number,paid_amount,remark
    CLM-000012,840.00,Paid per contract
    CLM-000013,120.50,

Import parses and *reconciles* each line against our claims without moving money:
  matched     paid == outstanding approved amount
  short_paid  0 < paid < outstanding           (posted; remainder stays open or can be accepted)
  overpaid    paid > outstanding               (not posted; needs manual follow-up)
  unmatched   unknown claim, other insurer, claim not approved, duplicate, or zero amount
Post then records insurer payments (Dr Bank / Cr AR-Insurers) for matched and short-paid lines,
re-validating each line first.
"""

import csv
import io
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, Conflict, NotFound, ValidationFailed
from app.core.money import quantize
from app.models.insurance import (
    ClaimStatus,
    MatchStatus,
    Remittance,
    RemittanceLine,
    RemittanceStatus,
)
from app.repositories import billing as billing_repo
from app.repositories import insurance as repo
from app.services import audit, claims
from app.services.audit import Actor
from app.services.insurance import get_insurer

MAX_LINES = 2000
MAX_BYTES = 1024 * 1024
ZERO = Decimal("0.00")
PAYABLE = (ClaimStatus.APPROVED, ClaimStatus.PARTIALLY_APPROVED)


@dataclass(frozen=True)
class ParsedLine:
    line_no: int
    claim_number: str
    paid_amount: Decimal
    remark: str


def parse_csv(text: str) -> list[ParsedLine]:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValidationFailed("Remittance file is larger than 1 MB", code="file_too_large")
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    fields = {(f or "").strip().lower() for f in (reader.fieldnames or [])}
    if not {"claim_number", "paid_amount"} <= fields:
        raise ValidationFailed(
            "CSV needs a header with claim_number and paid_amount columns",
            code="invalid_csv_header",
        )
    lines: list[ParsedLine] = []
    errors: list[str] = []
    for i, raw in enumerate(reader, start=1):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if not any(row.values()):
            continue
        number, amount_text = row.get("claim_number", ""), row.get("paid_amount", "")
        try:
            amount = Decimal(amount_text)
            if not amount.is_finite() or amount < 0 or quantize(amount) != amount:
                raise InvalidOperation
        except InvalidOperation:
            errors.append(f"line {i}: invalid paid_amount {amount_text!r}")
            continue
        if not number:
            errors.append(f"line {i}: claim_number is empty")
            continue
        lines.append(ParsedLine(i, number.upper(), quantize(amount), row.get("remark", "")[:255]))
        if len(lines) > MAX_LINES:
            raise ValidationFailed(f"At most {MAX_LINES} lines per file", code="too_many_lines")
    if errors:
        raise ValidationFailed(
            "Remittance file has invalid lines", code="invalid_csv", details={"errors": errors[:50]}
        )
    if not lines:
        raise ValidationFailed("Remittance file has no lines", code="empty_csv")
    return lines


def _reconcile(
    session: Session, insurer_id: int, parsed: ParsedLine, allocated: dict[int, Decimal]
) -> tuple[int | None, Decimal | None, str, str]:
    """(claim_id, expected, match_status, message) for one line."""
    claim = repo.get_claim_by_number(session, parsed.claim_number)
    if claim is None:
        return None, None, MatchStatus.UNMATCHED, "Unknown claim number"
    if claim.insurer_id != insurer_id:
        return claim.id, None, MatchStatus.UNMATCHED, "Claim belongs to another insurer"
    if claim.status not in PAYABLE:
        return claim.id, None, MatchStatus.UNMATCHED, f"Claim is {claim.status}, not approved"
    expected = claim.outstanding - allocated.get(claim.id, ZERO)
    if parsed.paid_amount == 0:
        return claim.id, expected, MatchStatus.UNMATCHED, "Zero payment"
    if expected <= 0:
        return claim.id, expected, MatchStatus.OVERPAID, "Claim already fully settled"
    if parsed.paid_amount == expected:
        allocated[claim.id] = allocated.get(claim.id, ZERO) + parsed.paid_amount
        return claim.id, expected, MatchStatus.MATCHED, "Matched"
    if parsed.paid_amount < expected:
        allocated[claim.id] = allocated.get(claim.id, ZERO) + parsed.paid_amount
        return (
            claim.id,
            expected,
            MatchStatus.SHORT_PAID,
            (f"Short paid by {expected - parsed.paid_amount:.2f}"),
        )
    return (
        claim.id,
        expected,
        MatchStatus.OVERPAID,
        (f"Overpaid by {parsed.paid_amount - expected:.2f}; not posted"),
    )


def import_remittance(
    session: Session,
    actor: Actor,
    *,
    insurer_id: int,
    reference: str,
    payment_date: date,
    filename: str,
    csv_text: str,
    expected_total: Decimal | None = None,
) -> Remittance:
    insurer = get_insurer(session, insurer_id)
    reference = reference.strip()
    if not reference:
        raise ValidationFailed(
            "Payer reference (EFT / cheque number) is required", code="reference_required"
        )
    if repo.remittance_reference_taken(session, insurer.id, reference):
        raise Conflict("This remittance was already imported", code="duplicate_remittance")
    parsed = parse_csv(csv_text)
    total = sum((p.paid_amount for p in parsed), ZERO)
    if expected_total is not None and expected_total != total:
        raise ValidationFailed(
            f"Lines total {total:.2f} but the payment is {expected_total:.2f}",
            code="total_mismatch",
        )
    remittance = Remittance(
        remittance_number=billing_repo.next_number(session, "remittance_number_seq", "REM"),
        insurer_id=insurer.id,
        reference=reference,
        payment_date=payment_date,
        status=RemittanceStatus.IMPORTED,
        total_amount=total,
        posted_amount=ZERO,
        source_filename=filename[:255],
        imported_by_id=actor.id,
    )
    session.add(remittance)
    session.flush()
    allocated: dict[int, Decimal] = {}
    for p in parsed:
        claim_id, expected, status, message = _reconcile(session, insurer.id, p, allocated)
        session.add(
            RemittanceLine(
                remittance_id=remittance.id,
                line_no=p.line_no,
                claim_number=p.claim_number,
                claim_id=claim_id,
                paid_amount=p.paid_amount,
                expected_amount=expected,
                match_status=status,
                message=message,
                remark=p.remark,
            )
        )
    session.flush()
    session.refresh(remittance)
    audit.record(
        session,
        actor,
        entity_type="remittance",
        entity_id=remittance.id,
        action="create",
        after=audit.snapshot(
            remittance, extra={"lines": len(parsed), "summary": summary(remittance)}
        ),
    )
    return remittance


def summary(remittance: Remittance) -> dict[str, int]:
    counts = {m.value: 0 for m in MatchStatus}
    for line in remittance.lines:
        counts[line.match_status] += 1
    return counts


def get_remittance(session: Session, remittance_id: int, *, lock: bool = False) -> Remittance:
    remittance = repo.get_remittance(session, remittance_id, lock=lock)
    if remittance is None:
        raise NotFound("Remittance not found")
    return remittance


def post_remittance(session: Session, actor: Actor, remittance_id: int) -> Remittance:
    """Post matched and short-paid lines to the ledger as insurer payments."""
    remittance = get_remittance(session, remittance_id, lock=True)
    if remittance.status != RemittanceStatus.IMPORTED:
        raise Conflict("Remittance is already posted", code="already_posted")
    before = audit.snapshot(remittance)
    posted = ZERO
    for line in remittance.lines:
        if line.match_status not in (MatchStatus.MATCHED, MatchStatus.SHORT_PAID):
            continue
        claim = claims.get_claim(session, line.claim_id, lock=True) if line.claim_id else None
        if claim is None or claim.status not in PAYABLE or line.paid_amount > claim.outstanding:
            line.match_status = MatchStatus.UNMATCHED
            line.message = "Claim changed after import; not posted"
            continue
        payment = claims.record_insurer_payment(
            session,
            actor,
            claim,
            line.paid_amount,
            on=remittance.payment_date,
            reference=f"{remittance.remittance_number}/{remittance.reference}",
        )
        line.payment_id = payment.id
        posted += line.paid_amount
    if posted == 0:
        raise BusinessRuleViolation("No matched lines to post", code="nothing_to_post")
    remittance.posted_amount = posted
    remittance.status = RemittanceStatus.POSTED
    remittance.posted_at = datetime.now(UTC)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="remittance",
        entity_id=remittance.id,
        action="status_change",
        before=before,
        after=audit.snapshot(remittance, extra={"summary": summary(remittance)}),
    )
    return remittance
