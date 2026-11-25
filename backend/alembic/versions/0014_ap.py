"""ap: vendors, purchase_orders, vendor_bills, vendor_payments (+ lines)

Revision ID: 0014_ap
Revises: 0013_ar
Create Date: 2026-11-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_ap"
down_revision: str | None = "0013_ar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('vendors',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('email', sa.String(length=255), server_default='', nullable=False),
    sa.Column('tax_id', sa.String(length=40), server_default='', nullable=False),
    sa.Column('bank_reference', sa.String(length=80), server_default='', nullable=False),
    sa.Column('payment_terms_days', sa.Integer(), server_default='30', nullable=False),
    sa.Column('default_expense_account_id', sa.BigInteger(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('payment_terms_days BETWEEN 0 AND 180', name=('ck_vendors_valid_terms')),
    sa.ForeignKeyConstraint(['default_expense_account_id'], ['accounts.id'], name=('fk_vendors_default_expense_account_id_accounts'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_vendors')),
    sa.UniqueConstraint('code', name=('uq_vendors_code'))
    )
    op.create_table('purchase_orders',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('po_number', sa.String(length=20), nullable=False),
    sa.Column('vendor_id', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('order_date', sa.Date(), nullable=False),
    sa.Column('expected_date', sa.Date(), nullable=True),
    sa.Column('received_on', sa.Date(), nullable=True),
    sa.Column('total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('notes', sa.Text(), server_default='', nullable=False),
    sa.Column('created_by_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('draft','issued','received','closed','cancelled')", name=('ck_purchase_orders_valid_status')),
    sa.CheckConstraint('total >= 0', name=('ck_purchase_orders_non_negative_total')),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=('fk_purchase_orders_created_by_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], name=('fk_purchase_orders_vendor_id_vendors'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_purchase_orders')),
    sa.UniqueConstraint('po_number', name=('uq_purchase_orders_po_number'))
    )
    op.create_index(('ix_purchase_orders_order_date'), 'purchase_orders', ['order_date'], unique=False)
    op.create_index(('ix_purchase_orders_status'), 'purchase_orders', ['status'], unique=False)
    op.create_index(('ix_purchase_orders_vendor_id'), 'purchase_orders', ['vendor_id'], unique=False)
    op.create_table('purchase_order_lines',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('purchase_order_id', sa.BigInteger(), nullable=False),
    sa.Column('line_no', sa.Integer(), nullable=False),
    sa.Column('description', sa.String(length=300), nullable=False),
    sa.Column('account_id', sa.BigInteger(), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('received_quantity', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('quantity > 0 AND unit_price >= 0 AND amount >= 0', name=('ck_purchase_order_lines_valid_amounts')),
    sa.CheckConstraint('received_quantity >= 0', name=('ck_purchase_order_lines_non_negative_received')),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=('fk_purchase_order_lines_account_id_accounts'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['purchase_order_id'], ['purchase_orders.id'], name=('fk_purchase_order_lines_purchase_order_id_purchase_orders'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=('pk_purchase_order_lines')),
    sa.UniqueConstraint('purchase_order_id', 'line_no', name='uq_po_lines_po_line')
    )
    op.create_index(('ix_purchase_order_lines_purchase_order_id'), 'purchase_order_lines', ['purchase_order_id'], unique=False)
    op.create_table('vendor_bills',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('bill_number', sa.String(length=20), nullable=False),
    sa.Column('vendor_id', sa.BigInteger(), nullable=False),
    sa.Column('vendor_invoice_number', sa.String(length=60), nullable=False),
    sa.Column('purchase_order_id', sa.BigInteger(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('match_status', sa.String(length=20), nullable=False),
    sa.Column('match_note', sa.String(length=300), server_default='', nullable=False),
    sa.Column('bill_date', sa.Date(), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=False),
    sa.Column('scheduled_payment_date', sa.Date(), nullable=True),
    sa.Column('total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('amount_paid', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('notes', sa.Text(), server_default='', nullable=False),
    sa.Column('approval_entry_id', sa.BigInteger(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("match_status IN ('no_po','matched','not_received','variance')", name=('ck_vendor_bills_valid_match')),
    sa.CheckConstraint("status IN ('draft','pending_approval','approved','partially_paid','paid','rejected','void')", name=('ck_vendor_bills_valid_status')),
    sa.CheckConstraint('total >= 0 AND amount_paid >= 0 AND amount_paid <= total', name=('ck_vendor_bills_paid_within_total')),
    sa.ForeignKeyConstraint(['approval_entry_id'], ['journal_entries.id'], name=('fk_vendor_bills_approval_entry_id_journal_entries'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=('fk_vendor_bills_created_by_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['purchase_order_id'], ['purchase_orders.id'], name=('fk_vendor_bills_purchase_order_id_purchase_orders'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], name=('fk_vendor_bills_vendor_id_vendors'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_vendor_bills')),
    sa.UniqueConstraint('bill_number', name=('uq_vendor_bills_bill_number')),
    sa.UniqueConstraint('vendor_id', 'vendor_invoice_number', name='uq_vendor_bills_vendor_invoice')
    )
    op.create_index(('ix_vendor_bills_bill_date'), 'vendor_bills', ['bill_date'], unique=False)
    op.create_index(('ix_vendor_bills_due_date'), 'vendor_bills', ['due_date'], unique=False)
    op.create_index(('ix_vendor_bills_purchase_order_id'), 'vendor_bills', ['purchase_order_id'], unique=False)
    op.create_index(('ix_vendor_bills_scheduled_payment_date'), 'vendor_bills', ['scheduled_payment_date'], unique=False)
    op.create_index(('ix_vendor_bills_status'), 'vendor_bills', ['status'], unique=False)
    op.create_index('ix_vendor_bills_status_due', 'vendor_bills', ['status', 'due_date'], unique=False)
    op.create_index(('ix_vendor_bills_vendor_id'), 'vendor_bills', ['vendor_id'], unique=False)
    op.create_table('vendor_bill_lines',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('vendor_bill_id', sa.BigInteger(), nullable=False),
    sa.Column('line_no', sa.Integer(), nullable=False),
    sa.Column('description', sa.String(length=300), nullable=False),
    sa.Column('account_id', sa.BigInteger(), nullable=False),
    sa.Column('department_id', sa.BigInteger(), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('quantity > 0 AND unit_price >= 0 AND amount >= 0', name=('ck_vendor_bill_lines_valid_amounts')),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=('fk_vendor_bill_lines_account_id_accounts'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=('fk_vendor_bill_lines_department_id_departments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['vendor_bill_id'], ['vendor_bills.id'], name=('fk_vendor_bill_lines_vendor_bill_id_vendor_bills'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=('pk_vendor_bill_lines')),
    sa.UniqueConstraint('vendor_bill_id', 'line_no', name='uq_bill_lines_bill_line')
    )
    op.create_index(('ix_vendor_bill_lines_vendor_bill_id'), 'vendor_bill_lines', ['vendor_bill_id'], unique=False)
    op.create_table('vendor_payments',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('payment_number', sa.String(length=20), nullable=False),
    sa.Column('vendor_bill_id', sa.BigInteger(), nullable=False),
    sa.Column('vendor_id', sa.BigInteger(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('paid_on', sa.Date(), nullable=False),
    sa.Column('method', sa.String(length=20), nullable=False),
    sa.Column('reference', sa.String(length=80), server_default='', nullable=False),
    sa.Column('journal_entry_id', sa.BigInteger(), nullable=True),
    sa.Column('created_by_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("method IN ('bank_transfer','cheque')", name=('ck_vendor_payments_valid_method')),
    sa.CheckConstraint('amount > 0', name=('ck_vendor_payments_positive_amount')),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=('fk_vendor_payments_created_by_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entries.id'], name=('fk_vendor_payments_journal_entry_id_journal_entries'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['vendor_bill_id'], ['vendor_bills.id'], name=('fk_vendor_payments_vendor_bill_id_vendor_bills'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], name=('fk_vendor_payments_vendor_id_vendors'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_vendor_payments')),
    sa.UniqueConstraint('payment_number', name=('uq_vendor_payments_payment_number'))
    )
    op.create_index(('ix_vendor_payments_paid_on'), 'vendor_payments', ['paid_on'], unique=False)
    op.create_index(('ix_vendor_payments_vendor_bill_id'), 'vendor_payments', ['vendor_bill_id'], unique=False)
    op.create_index(('ix_vendor_payments_vendor_id'), 'vendor_payments', ['vendor_id'], unique=False)


    op.execute("CREATE SEQUENCE po_number_seq START 1")
    op.execute("CREATE SEQUENCE bill_number_seq START 1")
    op.execute("CREATE SEQUENCE vendor_payment_number_seq START 1")
    # Financial and approval records are never deleted.
    op.execute("CREATE TRIGGER vendors_no_delete BEFORE DELETE ON vendors FOR EACH ROW EXECUTE FUNCTION billing_no_delete()")
    op.execute("CREATE TRIGGER purchase_orders_no_delete BEFORE DELETE ON purchase_orders FOR EACH ROW EXECUTE FUNCTION billing_no_delete()")
    op.execute("CREATE TRIGGER vendor_bills_no_delete BEFORE DELETE ON vendor_bills FOR EACH ROW EXECUTE FUNCTION billing_no_delete()")
    op.execute("CREATE TRIGGER vendor_payments_no_delete BEFORE DELETE ON vendor_payments FOR EACH ROW EXECUTE FUNCTION billing_no_delete()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS vendors_no_delete ON vendors")
    op.execute("DROP TRIGGER IF EXISTS purchase_orders_no_delete ON purchase_orders")
    op.execute("DROP TRIGGER IF EXISTS vendor_bills_no_delete ON vendor_bills")
    op.execute("DROP TRIGGER IF EXISTS vendor_payments_no_delete ON vendor_payments")
    op.execute("DROP SEQUENCE IF EXISTS po_number_seq")
    op.execute("DROP SEQUENCE IF EXISTS bill_number_seq")
    op.execute("DROP SEQUENCE IF EXISTS vendor_payment_number_seq")
    op.drop_table('vendor_payments')
    op.drop_table('vendor_bill_lines')
    op.drop_table('vendor_bills')
    op.drop_table('purchase_order_lines')
    op.drop_table('purchase_orders')
    op.drop_table('vendors')
