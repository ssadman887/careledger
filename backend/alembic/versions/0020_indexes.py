"""indexes found in the Phase 7 query review

Revision ID: 0020_indexes
Revises: 0019_alert_percent
Create Date: 2026-11-26 10:00:00

* claim_lines.invoice_line_id: "is this invoice line already claimed?" checks.
* remittance_lines.payment_id: remittance <-> payment lookups.
* journal_entries (status, entry_date): every report and dashboard aggregate.
* invoices (status, due_date): overdue balances, dunning candidates.
"""
from collections.abc import Sequence

from alembic import op


revision: str = '0020_indexes'
down_revision: str | None = '0019_alert_percent'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index('ix_claim_lines_invoice_line_id', 'claim_lines', ['invoice_line_id'])
    op.create_index('ix_remittance_lines_payment_id', 'remittance_lines', ['payment_id'])
    op.create_index('ix_journal_entries_status_date', 'journal_entries', ['status', 'entry_date'])
    op.create_index('ix_invoices_status_due', 'invoices', ['status', 'due_date'])


def downgrade() -> None:
    op.drop_index('ix_invoices_status_due', table_name='invoices')
    op.drop_index('ix_journal_entries_status_date', table_name='journal_entries')
    op.drop_index('ix_remittance_lines_payment_id', table_name='remittance_lines')
    op.drop_index('ix_claim_lines_invoice_line_id', table_name='claim_lines')
