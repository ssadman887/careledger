"""billing: invoices, invoice_lines, payments, refunds

Revision ID: 0007_billing
Revises: 0006_catalog
Create Date: 2026-11-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql  # noqa: F401

revision: str = "0007_billing"
down_revision: str | None = "0006_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('invoices',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('invoice_number', sa.String(length=20), nullable=False),
    sa.Column('patient_id', sa.BigInteger(), nullable=False),
    sa.Column('visit_id', sa.BigInteger(), nullable=True),
    sa.Column('price_list_id', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('invoice_date', sa.Date(), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('subtotal', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('discount_total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('tax_total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('amount_paid', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('notes', sa.Text(), server_default='', nullable=False),
    sa.Column('issue_entry_id', sa.BigInteger(), nullable=True),
    sa.Column('void_entry_id', sa.BigInteger(), nullable=True),
    sa.Column('issued_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('voided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('void_reason', sa.Text(), nullable=True),
    sa.Column('created_by_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('draft','issued','partially_paid','paid','void')", name=('ck_invoices_valid_status')),
    sa.CheckConstraint('amount_paid >= 0 AND amount_paid <= total', name=('ck_invoices_paid_within_total')),
    sa.CheckConstraint('subtotal >= 0 AND discount_total >= 0 AND tax_total >= 0 AND total >= 0', name=('ck_invoices_non_negative_totals')),
    sa.CheckConstraint('total = subtotal - discount_total + tax_total', name=('ck_invoices_total_formula')),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=('fk_invoices_created_by_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['issue_entry_id'], ['journal_entries.id'], name=('fk_invoices_issue_entry_id_journal_entries'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], name=('fk_invoices_patient_id_patients'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['price_list_id'], ['price_lists.id'], name=('fk_invoices_price_list_id_price_lists'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['visit_id'], ['visits.id'], name=('fk_invoices_visit_id_visits'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['void_entry_id'], ['journal_entries.id'], name=('fk_invoices_void_entry_id_journal_entries'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_invoices')),
    sa.UniqueConstraint('invoice_number', name=('uq_invoices_invoice_number'))
    )
    op.create_index(('ix_invoices_due_date'), 'invoices', ['due_date'], unique=False)
    op.create_index(('ix_invoices_invoice_date'), 'invoices', ['invoice_date'], unique=False)
    op.create_index(('ix_invoices_patient_id'), 'invoices', ['patient_id'], unique=False)
    op.create_index(('ix_invoices_status'), 'invoices', ['status'], unique=False)
    op.create_index('ix_invoices_status_date', 'invoices', ['status', 'invoice_date'], unique=False)
    op.create_index(('ix_invoices_visit_id'), 'invoices', ['visit_id'], unique=False)
    op.create_table('invoice_lines',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('invoice_id', sa.BigInteger(), nullable=False),
    sa.Column('line_no', sa.Integer(), nullable=False),
    sa.Column('service_id', sa.BigInteger(), nullable=True),
    sa.Column('description', sa.String(length=300), nullable=False),
    sa.Column('department_id', sa.BigInteger(), nullable=False),
    sa.Column('service_date', sa.Date(), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('gross_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('discount_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('tax_rate', sa.Numeric(precision=5, scale=4), nullable=False),
    sa.Column('tax_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('line_total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('discount_amount >= 0 AND discount_amount <= gross_amount', name=('ck_invoice_lines_valid_discount')),
    sa.CheckConstraint('line_total = gross_amount - discount_amount + tax_amount', name=('ck_invoice_lines_total_formula')),
    sa.CheckConstraint('quantity > 0', name=('ck_invoice_lines_positive_quantity')),
    sa.CheckConstraint('tax_rate >= 0 AND tax_rate < 1', name=('ck_invoice_lines_valid_tax_rate')),
    sa.CheckConstraint('unit_price >= 0', name=('ck_invoice_lines_non_negative_price')),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=('fk_invoice_lines_department_id_departments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=('fk_invoice_lines_invoice_id_invoices'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['service_id'], ['services.id'], name=('fk_invoice_lines_service_id_services'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_invoice_lines')),
    sa.UniqueConstraint('invoice_id', 'line_no', name='uq_invoice_lines_invoice_line')
    )
    op.create_index(('ix_invoice_lines_department_id'), 'invoice_lines', ['department_id'], unique=False)
    op.create_index(('ix_invoice_lines_invoice_id'), 'invoice_lines', ['invoice_id'], unique=False)
    op.create_index(('ix_invoice_lines_service_id'), 'invoice_lines', ['service_id'], unique=False)
    op.create_table('payments',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('payment_number', sa.String(length=20), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('patient_id', sa.BigInteger(), nullable=False),
    sa.Column('invoice_id', sa.BigInteger(), nullable=True),
    sa.Column('method', sa.String(length=20), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('refunded_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('received_on', sa.Date(), nullable=False),
    sa.Column('reference', sa.String(length=100), server_default='', nullable=False),
    sa.Column('notes', sa.Text(), server_default='', nullable=False),
    sa.Column('journal_entry_id', sa.BigInteger(), nullable=True),
    sa.Column('created_by_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(kind = 'invoice') = (invoice_id IS NOT NULL)", name=('ck_payments_kind_matches_invoice')),
    sa.CheckConstraint("NOT (kind = 'deposit' AND method = 'deposit')", name=('ck_payments_deposit_not_from_deposit')),
    sa.CheckConstraint("kind IN ('invoice','deposit')", name=('ck_payments_valid_kind')),
    sa.CheckConstraint("method IN ('cash','card','bank_transfer','deposit','insurance')", name=('ck_payments_valid_method')),
    sa.CheckConstraint('amount > 0', name=('ck_payments_positive_amount')),
    sa.CheckConstraint('refunded_amount >= 0 AND refunded_amount <= amount', name=('ck_payments_refund_within_amount')),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=('fk_payments_created_by_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=('fk_payments_invoice_id_invoices'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entries.id'], name=('fk_payments_journal_entry_id_journal_entries'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], name=('fk_payments_patient_id_patients'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_payments')),
    sa.UniqueConstraint('payment_number', name=('uq_payments_payment_number'))
    )
    op.create_index(('ix_payments_invoice_id'), 'payments', ['invoice_id'], unique=False)
    op.create_index('ix_payments_method_date', 'payments', ['method', 'received_on'], unique=False)
    op.create_index(('ix_payments_patient_id'), 'payments', ['patient_id'], unique=False)
    op.create_index(('ix_payments_received_on'), 'payments', ['received_on'], unique=False)
    op.create_table('refunds',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('refund_number', sa.String(length=20), nullable=False),
    sa.Column('payment_id', sa.BigInteger(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('refunded_on', sa.Date(), nullable=True),
    sa.Column('journal_entry_id', sa.BigInteger(), nullable=True),
    sa.Column('requested_by_id', sa.BigInteger(), nullable=True),
    sa.Column('decided_by_id', sa.BigInteger(), nullable=True),
    sa.Column('decision_note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('pending_approval','completed','rejected')", name=('ck_refunds_valid_status')),
    sa.CheckConstraint('amount > 0', name=('ck_refunds_positive_amount')),
    sa.ForeignKeyConstraint(['decided_by_id'], ['users.id'], name=('fk_refunds_decided_by_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entries.id'], name=('fk_refunds_journal_entry_id_journal_entries'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], name=('fk_refunds_payment_id_payments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['requested_by_id'], ['users.id'], name=('fk_refunds_requested_by_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_refunds')),
    sa.UniqueConstraint('refund_number', name=('uq_refunds_refund_number'))
    )
    op.create_index(('ix_refunds_payment_id'), 'refunds', ['payment_id'], unique=False)
    op.create_index(('ix_refunds_status'), 'refunds', ['status'], unique=False)



    for seq in ("invoice_number_seq", "payment_number_seq", "refund_number_seq"):
        op.execute(f"CREATE SEQUENCE {seq} START 1")

    # Invoice lines can only change while the invoice is a draft.
    op.execute(
        """
        CREATE FUNCTION billing_lines_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE st text; inv bigint;
        BEGIN
            IF TG_OP = 'DELETE' THEN inv := OLD.invoice_id; ELSE inv := NEW.invoice_id; END IF;
            SELECT status INTO st FROM invoices WHERE id = inv;
            IF st IS DISTINCT FROM 'draft' THEN
                RAISE EXCEPTION 'invoice lines are frozen once the invoice is %', st USING ERRCODE = 'P0001';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        "CREATE TRIGGER invoice_lines_frozen BEFORE INSERT OR UPDATE OR DELETE ON invoice_lines "
        "FOR EACH ROW EXECUTE FUNCTION billing_lines_frozen()"
    )

    # Issued invoices keep their amounts; void invoices never change; nothing is deleted.
    op.execute(
        """
        CREATE FUNCTION billing_invoices_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'invoices cannot be deleted (void them instead)' USING ERRCODE = 'P0001';
            END IF;
            IF OLD.status = 'void' THEN
                RAISE EXCEPTION 'void invoices are immutable' USING ERRCODE = 'P0001';
            END IF;
            IF OLD.status <> 'draft' AND (
                NEW.subtotal <> OLD.subtotal OR NEW.discount_total <> OLD.discount_total OR
                NEW.tax_total <> OLD.tax_total OR NEW.total <> OLD.total OR
                NEW.patient_id <> OLD.patient_id OR NEW.invoice_date IS DISTINCT FROM OLD.invoice_date
            ) THEN
                RAISE EXCEPTION 'issued invoice amounts are immutable' USING ERRCODE = 'P0001';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        "CREATE TRIGGER invoices_guard BEFORE UPDATE OR DELETE ON invoices "
        "FOR EACH ROW EXECUTE FUNCTION billing_invoices_guard()"
    )
    op.execute(
        """
        CREATE FUNCTION billing_no_delete() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% rows cannot be deleted', TG_TABLE_NAME USING ERRCODE = 'P0001';
        END;
        $$;
        """
    )
    for table in ("payments", "refunds"):
        op.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION billing_no_delete()"
        )


def downgrade() -> None:

    for table in ("payments", "refunds"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete ON {table}")
    op.execute("DROP TRIGGER IF EXISTS invoices_guard ON invoices")
    op.execute("DROP TRIGGER IF EXISTS invoice_lines_frozen ON invoice_lines")
    op.drop_table('refunds')
    op.drop_table('payments')
    op.drop_table('invoice_lines')
    op.drop_table('invoices')
    for fn in ("billing_no_delete", "billing_invoices_guard", "billing_lines_frozen"):
        op.execute(f"DROP FUNCTION IF EXISTS {fn}()")
    for seq in ("refund_number_seq", "payment_number_seq", "invoice_number_seq"):
        op.execute(f"DROP SEQUENCE IF EXISTS {seq}")
