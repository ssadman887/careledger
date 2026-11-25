"""Account mapping for auto-posting (docs/ARCHITECTURE.md section 4).

Business services describe *what* happened; this module turns it into balanced journal lines.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation
from app.models.billing import PaymentMethod
from app.repositories import ledger as ledger_repo
from app.services.ledger import LineInput

ZERO = Decimal("0.00")

CASH = "1010"
BANK = "1020"
AR_PATIENTS = "1100"
AR_INSURERS = "1110"
PATIENT_DEPOSITS = "2200"
SALES_TAX = "2300"
CONTRACTUAL_ADJ = "4900"
PATIENT_DISCOUNTS = "4910"
OTHER_INCOME = "4950"
BAD_DEBT = "5400"


def account_id(session: Session, code: str) -> int:
    account = ledger_repo.get_account_by_code(session, code)
    if account is None or account.is_header or not account.is_active:
        raise BusinessRuleViolation(
            f"Posting account {code} is missing or not postable; check the chart of accounts",
            code="posting_account_missing",
        )
    return account.id


def money_account_code(method: str) -> str:
    """Where money comes from / goes to for a payment method."""
    if method == PaymentMethod.CASH:
        return CASH
    if method in (PaymentMethod.CARD, PaymentMethod.BANK_TRANSFER, PaymentMethod.INSURANCE):
        return BANK
    if method == PaymentMethod.DEPOSIT:
        return PATIENT_DEPOSITS
    raise BusinessRuleViolation(f"Unknown payment method {method}", code="invalid_method")


@dataclass(frozen=True)
class RevenueLine:
    """Gross revenue for one department (credited to that department's revenue account)."""

    department_id: int
    revenue_account_id: int | None
    gross: Decimal


def invoice_issue_lines(
    session: Session,
    *,
    total: Decimal,
    discount_total: Decimal,
    tax_total: Decimal,
    revenue: Iterable[RevenueLine],
    memo: str,
) -> list[LineInput]:
    """Dr AR-Patients (total) + Dr Discounts; Cr department revenue (gross) + Cr Sales tax."""
    lines = [LineInput(account_id(session, AR_PATIENTS), debit=total, description=memo)]
    if discount_total > 0:
        lines.append(
            LineInput(
                account_id(session, PATIENT_DISCOUNTS),
                debit=discount_total,
                description="Discounts",
            )
        )
    by_account: dict[tuple[int, int], Decimal] = {}
    for rev in revenue:
        acct = rev.revenue_account_id or account_id(session, OTHER_INCOME)
        key = (acct, rev.department_id)
        by_account[key] = by_account.get(key, ZERO) + rev.gross
    for (acct, dept), gross in sorted(by_account.items()):
        if gross > 0:
            lines.append(
                LineInput(
                    acct, credit=gross, description="Patient service revenue", department_id=dept
                )
            )
    if tax_total > 0:
        lines.append(
            LineInput(account_id(session, SALES_TAX), credit=tax_total, description="Sales tax")
        )
    return lines


def simple_transfer(
    session: Session, *, debit_code: str, credit_code: str, amount: Decimal, description: str
) -> list[LineInput]:
    return [
        LineInput(account_id(session, debit_code), debit=amount, description=description),
        LineInput(account_id(session, credit_code), credit=amount, description=description),
    ]
