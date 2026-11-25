"""claims: claims, claim_lines, claim_events, claim_attachments; invoice AR fields

Revision ID: 0010_claims
Revises: 0009_insurance
Create Date: 2026-11-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_claims"
down_revision: str | None = "0009_insurance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('invoices', sa.Column('adjusted_amount', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False))
    op.add_column('invoices', sa.Column('insurance_pending', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False))
    op.create_table('claims',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('claim_number', sa.String(length=20), nullable=False),
    sa.Column('invoice_id', sa.BigInteger(), nullable=False),
    sa.Column('policy_id', sa.BigInteger(), nullable=False),
    sa.Column('patient_id', sa.BigInteger(), nullable=False),
    sa.Column('insurer_id', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('service_date', sa.Date(), nullable=False),
    sa.Column('billed_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('copay_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('deductible_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('coinsurance_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('over_limit_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('insurer_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('patient_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('approved_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('paid_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('adjustment_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('denial_code', sa.String(length=20), nullable=True),
    sa.Column('denial_note', sa.Text(), nullable=True),
    sa.Column('appeal_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('adjudicated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('transfer_entry_id', sa.BigInteger(), nullable=True),
    sa.Column('created_by_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('draft', 'submitted', 'under_review', 'approved', 'partially_approved', 'denied', 'appealed', 'paid', 'closed', 'cancelled')", name=('ck_claims_valid_status')),
    sa.CheckConstraint('approved_amount <= insurer_amount', name=('ck_claims_approved_within_claimed')),
    sa.CheckConstraint('billed_amount >= 0 AND insurer_amount >= 0 AND patient_amount >= 0 AND approved_amount >= 0 AND paid_amount >= 0 AND adjustment_amount >= 0', name=('ck_claims_non_negative')),
    sa.CheckConstraint('insurer_amount + patient_amount = billed_amount', name=('ck_claims_split_formula')),
    sa.CheckConstraint('paid_amount + adjustment_amount <= insurer_amount', name=('ck_claims_settled_within_claimed')),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=('fk_claims_created_by_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['insurer_id'], ['insurers.id'], name=('fk_claims_insurer_id_insurers'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=('fk_claims_invoice_id_invoices'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], name=('fk_claims_patient_id_patients'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['policy_id'], ['policies.id'], name=('fk_claims_policy_id_policies'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['transfer_entry_id'], ['journal_entries.id'], name=('fk_claims_transfer_entry_id_journal_entries'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_claims')),
    sa.UniqueConstraint('claim_number', name=('uq_claims_claim_number'))
    )
    op.create_index(('ix_claims_adjudicated_at'), 'claims', ['adjudicated_at'], unique=False)
    op.create_index(('ix_claims_insurer_id'), 'claims', ['insurer_id'], unique=False)
    op.create_index(('ix_claims_invoice_id'), 'claims', ['invoice_id'], unique=False)
    op.create_index(('ix_claims_patient_id'), 'claims', ['patient_id'], unique=False)
    op.create_index(('ix_claims_policy_id'), 'claims', ['policy_id'], unique=False)
    op.create_index(('ix_claims_service_date'), 'claims', ['service_date'], unique=False)
    op.create_index(('ix_claims_status'), 'claims', ['status'], unique=False)
    op.create_index('ix_claims_status_insurer', 'claims', ['status', 'insurer_id'], unique=False)
    op.create_table('claim_lines',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('claim_id', sa.BigInteger(), nullable=False),
    sa.Column('line_no', sa.Integer(), nullable=False),
    sa.Column('invoice_line_id', sa.BigInteger(), nullable=False),
    sa.Column('service_code', sa.String(length=30), server_default='', nullable=False),
    sa.Column('description', sa.String(length=300), nullable=False),
    sa.Column('service_date', sa.Date(), nullable=False),
    sa.Column('billed_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('insurer_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('billed_amount >= 0 AND insurer_amount >= 0', name=('ck_claim_lines_non_negative')),
    sa.CheckConstraint('insurer_amount <= billed_amount', name=('ck_claim_lines_insurer_within_billed')),
    sa.ForeignKeyConstraint(['claim_id'], ['claims.id'], name=('fk_claim_lines_claim_id_claims'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['invoice_line_id'], ['invoice_lines.id'], name=('fk_claim_lines_invoice_line_id_invoice_lines'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_claim_lines')),
    sa.UniqueConstraint('claim_id', 'line_no', name='uq_claim_lines_claim_line')
    )
    op.create_index(('ix_claim_lines_claim_id'), 'claim_lines', ['claim_id'], unique=False)
    op.create_table('claim_events',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('claim_id', sa.BigInteger(), nullable=False),
    sa.Column('event_type', sa.String(length=30), nullable=False),
    sa.Column('from_status', sa.String(length=30), nullable=True),
    sa.Column('to_status', sa.String(length=30), nullable=True),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('denial_code', sa.String(length=20), nullable=True),
    sa.Column('note', sa.Text(), server_default='', nullable=False),
    sa.Column('actor_id', sa.BigInteger(), nullable=True),
    sa.Column('actor_label', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=('fk_claim_events_actor_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['claim_id'], ['claims.id'], name=('fk_claim_events_claim_id_claims'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_claim_events'))
    )
    op.create_index(('ix_claim_events_claim_id'), 'claim_events', ['claim_id'], unique=False)
    op.create_table('claim_attachments',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('claim_id', sa.BigInteger(), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('data', sa.LargeBinary(), nullable=False),
    sa.Column('uploaded_by_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('size_bytes > 0 AND size_bytes <= 5242880', name=('ck_claim_attachments_valid_size')),
    sa.ForeignKeyConstraint(['claim_id'], ['claims.id'], name=('fk_claim_attachments_claim_id_claims'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['uploaded_by_id'], ['users.id'], name=('fk_claim_attachments_uploaded_by_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_claim_attachments'))
    )
    op.create_index(('ix_claim_attachments_claim_id'), 'claim_attachments', ['claim_id'], unique=False)

    # Invoices now track insurer-pending amounts and cash-less adjustments.
    op.drop_constraint("ck_invoices_paid_within_total", "invoices", type_="check")
    op.create_check_constraint(
        "ck_invoices_settled_within_total", "invoices",
        "amount_paid >= 0 AND adjusted_amount >= 0 AND amount_paid + adjusted_amount <= total")
    op.create_check_constraint(
        "ck_invoices_insurance_within_balance", "invoices",
        "insurance_pending >= 0 AND insurance_pending <= total - amount_paid - adjusted_amount")
    op.execute("CREATE SEQUENCE claim_number_seq START 1")

    # Claim timeline is append-only.
    op.execute(
        """
        CREATE FUNCTION claim_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'claim_events is append-only: % rejected', TG_OP USING ERRCODE = 'P0001';
        END;
        $$;
        """
    )
    op.execute(
        "CREATE TRIGGER claim_events_append_only BEFORE UPDATE OR DELETE ON claim_events "
        "FOR EACH ROW EXECUTE FUNCTION claim_events_append_only()"
    )
    # Claims are never deleted (cancel or close them).
    op.execute(
        "CREATE TRIGGER claims_no_delete BEFORE DELETE ON claims "
        "FOR EACH ROW EXECUTE FUNCTION billing_no_delete()"
    )


def downgrade() -> None:
    op.drop_table('claim_attachments')
    op.drop_table('claim_events')
    op.drop_table('claim_lines')
    op.drop_table('claims')

    op.execute("DROP TRIGGER IF EXISTS claims_no_delete ON claims")
    op.execute("DROP TRIGGER IF EXISTS claim_events_append_only ON claim_events")
    op.execute("DROP FUNCTION IF EXISTS claim_events_append_only()")
    op.execute("DROP SEQUENCE IF EXISTS claim_number_seq")
    op.drop_constraint("ck_invoices_insurance_within_balance", "invoices", type_="check")
    op.drop_constraint("ck_invoices_settled_within_total", "invoices", type_="check")
    op.create_check_constraint("ck_invoices_paid_within_total", "invoices",
                               "amount_paid >= 0 AND amount_paid <= total")
    op.drop_column("invoices", "insurance_pending")
    op.drop_column("invoices", "adjusted_amount")
