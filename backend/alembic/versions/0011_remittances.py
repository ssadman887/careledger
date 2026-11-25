"""remittances: remittances, remittance_lines

Revision ID: 0011_remittances
Revises: 0010_claims
Create Date: 2026-11-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_remittances"
down_revision: str | None = "0010_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('remittances',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('remittance_number', sa.String(length=20), nullable=False),
    sa.Column('insurer_id', sa.BigInteger(), nullable=False),
    sa.Column('reference', sa.String(length=80), nullable=False),
    sa.Column('payment_date', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('total_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('posted_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('source_filename', sa.String(length=255), server_default='', nullable=False),
    sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('imported_by_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('imported', 'posted')", name=('ck_remittances_valid_status')),
    sa.CheckConstraint('total_amount >= 0 AND posted_amount >= 0', name=('ck_remittances_non_negative')),
    sa.ForeignKeyConstraint(['imported_by_id'], ['users.id'], name=('fk_remittances_imported_by_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['insurer_id'], ['insurers.id'], name=('fk_remittances_insurer_id_insurers'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_remittances')),
    sa.UniqueConstraint('insurer_id', 'reference', name='uq_remittances_insurer_reference'),
    sa.UniqueConstraint('remittance_number', name=('uq_remittances_remittance_number'))
    )
    op.create_index(('ix_remittances_insurer_id'), 'remittances', ['insurer_id'], unique=False)
    op.create_index(('ix_remittances_payment_date'), 'remittances', ['payment_date'], unique=False)
    op.create_index(('ix_remittances_status'), 'remittances', ['status'], unique=False)
    op.create_table('remittance_lines',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('remittance_id', sa.BigInteger(), nullable=False),
    sa.Column('line_no', sa.Integer(), nullable=False),
    sa.Column('claim_number', sa.String(length=40), nullable=False),
    sa.Column('claim_id', sa.BigInteger(), nullable=True),
    sa.Column('paid_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('expected_amount', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('match_status', sa.String(length=20), nullable=False),
    sa.Column('message', sa.Text(), server_default='', nullable=False),
    sa.Column('remark', sa.String(length=255), server_default='', nullable=False),
    sa.Column('payment_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("match_status IN ('matched', 'short_paid', 'overpaid', 'unmatched')", name=('ck_remittance_lines_valid_match_status')),
    sa.CheckConstraint('paid_amount >= 0', name=('ck_remittance_lines_non_negative')),
    sa.ForeignKeyConstraint(['claim_id'], ['claims.id'], name=('fk_remittance_lines_claim_id_claims'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], name=('fk_remittance_lines_payment_id_payments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['remittance_id'], ['remittances.id'], name=('fk_remittance_lines_remittance_id_remittances'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_remittance_lines')),
    sa.UniqueConstraint('remittance_id', 'line_no', name='uq_remittance_lines_remit_line')
    )
    op.create_index(('ix_remittance_lines_claim_id'), 'remittance_lines', ['claim_id'], unique=False)
    op.create_index(('ix_remittance_lines_match_status'), 'remittance_lines', ['match_status'], unique=False)
    op.create_index(('ix_remittance_lines_remittance_id'), 'remittance_lines', ['remittance_id'], unique=False)

    op.execute("CREATE SEQUENCE remittance_number_seq START 1")
    for table in ("remittances", "remittance_lines"):
        op.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION billing_no_delete()"
        )


def downgrade() -> None:
    op.drop_table('remittance_lines')
    op.drop_table('remittances')

    for table in ("remittances", "remittance_lines"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete ON {table}")
    op.execute("DROP SEQUENCE IF EXISTS remittance_number_seq")
