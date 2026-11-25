"""Import every model module so Base.metadata is complete (Alembic autogenerate, tests)."""

from app.models.audit import AuditLog
from app.models.base import Base
from app.models.billing import (
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    Payment,
    PaymentKind,
    PaymentMethod,
    Refund,
    RefundStatus,
)
from app.models.catalog import PriceList, PriceListItem, Service
from app.models.identity import RefreshToken, Role, RoleName, User, user_roles
from app.models.ledger import (
    Account,
    AccountType,
    EntryStatus,
    FiscalPeriod,
    JournalEntry,
    JournalLine,
    PeriodStatus,
)
from app.models.org import CostCenter, Department
from app.models.patients import Patient, Visit, VisitStatus, VisitType
from app.models.platform import IdempotencyKey

__all__ = [
    "Account",
    "AccountType",
    "AuditLog",
    "Base",
    "CostCenter",
    "Department",
    "EntryStatus",
    "FiscalPeriod",
    "IdempotencyKey",
    "Invoice",
    "InvoiceLine",
    "InvoiceStatus",
    "JournalEntry",
    "JournalLine",
    "Patient",
    "Payment",
    "PaymentKind",
    "PaymentMethod",
    "PeriodStatus",
    "PriceList",
    "PriceListItem",
    "RefreshToken",
    "Refund",
    "RefundStatus",
    "Role",
    "RoleName",
    "Service",
    "User",
    "Visit",
    "VisitStatus",
    "VisitType",
    "user_roles",
]
