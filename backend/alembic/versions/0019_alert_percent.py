"""widen budget_alerts.percent_used (large overruns of small budgets)

Revision ID: 0019_alert_percent
Revises: 0018_notifications
Create Date: 2026-11-25 18:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0019_alert_percent'
down_revision: str | None = '0018_notifications'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _set_type(type_: sa.Numeric) -> None:
    # budget_alerts is append-only (trigger blocks UPDATE); ALTER TYPE rewrites without UPDATE.
    op.alter_column('budget_alerts', 'percent_used', type_=type_, existing_nullable=False)


def upgrade() -> None:
    _set_type(sa.Numeric(precision=12, scale=2))


def downgrade() -> None:
    _set_type(sa.Numeric(precision=7, scale=2))
