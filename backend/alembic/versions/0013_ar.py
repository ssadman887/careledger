"""ar: write_offs, dunning_notices

Revision ID: 0013_ar
Revises: 0012_approvals
Create Date: 2026-11-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_ar"
down_revision: str | None = "0012_approvals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('write_offs',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('write_off_number', sa.String(length=20), nullable=False),
    sa.Column('invoice_id', sa.BigInteger(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('posted_on', sa.Date(), nullable=True),
    sa.Column('journal_entry_id', sa.BigInteger(), nullable=True),
    sa.Column('requested_by_id', sa.BigInteger(), nullable=True),
    sa.Column('decided_by_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('pending_approval','posted','rejected')", name=('ck_write_offs_valid_status')),
    sa.CheckConstraint('amount > 0', name=('ck_write_offs_positive_amount')),
    sa.ForeignKeyConstraint(['decided_by_id'], ['users.id'], name=('fk_write_offs_decided_by_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=('fk_write_offs_invoice_id_invoices'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entries.id'], name=('fk_write_offs_journal_entry_id_journal_entries'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['requested_by_id'], ['users.id'], name=('fk_write_offs_requested_by_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_write_offs')),
    sa.UniqueConstraint('write_off_number', name=('uq_write_offs_write_off_number'))
    )
    op.create_index(('ix_write_offs_invoice_id'), 'write_offs', ['invoice_id'], unique=False)
    op.create_index(('ix_write_offs_status'), 'write_offs', ['status'], unique=False)
    op.create_table('dunning_notices',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('invoice_id', sa.BigInteger(), nullable=False),
    sa.Column('patient_id', sa.BigInteger(), nullable=False),
    sa.Column('level', sa.Integer(), nullable=False),
    sa.Column('days_overdue', sa.Integer(), nullable=False),
    sa.Column('amount_due', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('channel', sa.String(length=20), server_default='email', nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('amount_due > 0', name=('ck_dunning_notices_positive_amount')),
    sa.CheckConstraint('level BETWEEN 1 AND 3', name=('ck_dunning_notices_valid_level')),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=('fk_dunning_notices_invoice_id_invoices'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], name=('fk_dunning_notices_patient_id_patients'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_dunning_notices')),
    sa.UniqueConstraint('invoice_id', 'level', name='uq_dunning_notices_invoice_level')
    )
    op.create_index(('ix_dunning_notices_invoice_id'), 'dunning_notices', ['invoice_id'], unique=False)
    op.create_index(('ix_dunning_notices_patient_id'), 'dunning_notices', ['patient_id'], unique=False)
    op.create_index(('ix_dunning_notices_sent_at'), 'dunning_notices', ['sent_at'], unique=False)
    op.execute("CREATE SEQUENCE write_off_number_seq START 1")
    # Financial and approval records are never deleted.
    op.execute("CREATE TRIGGER write_offs_no_delete BEFORE DELETE ON write_offs FOR EACH ROW EXECUTE FUNCTION billing_no_delete()")
    op.execute("CREATE TRIGGER dunning_notices_no_delete BEFORE DELETE ON dunning_notices FOR EACH ROW EXECUTE FUNCTION billing_no_delete()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS write_offs_no_delete ON write_offs")
    op.execute("DROP TRIGGER IF EXISTS dunning_notices_no_delete ON dunning_notices")
    op.execute("DROP SEQUENCE IF EXISTS write_off_number_seq")
    op.drop_table('dunning_notices')
    op.drop_table('write_offs')
