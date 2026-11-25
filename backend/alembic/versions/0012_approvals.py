"""approvals: approval_policies, approvals, approval_comments

Revision ID: 0012_approvals
Revises: 0011_remittances
Create Date: 2026-11-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_approvals"
down_revision: str | None = "0011_remittances"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('approval_policies',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('threshold', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('approver_role', sa.String(length=50), nullable=False),
    sa.Column('description', sa.String(length=255), server_default='', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('threshold >= 0', name=('ck_approval_policies_non_negative_threshold')),
    sa.PrimaryKeyConstraint('id', name=('pk_approval_policies')),
    sa.UniqueConstraint('kind', name=('uq_approval_policies_kind'))
    )
    op.create_table('approvals',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('entity_type', sa.String(length=40), nullable=False),
    sa.Column('entity_id', sa.BigInteger(), nullable=False),
    sa.Column('reference', sa.String(length=40), nullable=False),
    sa.Column('summary', sa.String(length=500), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('threshold', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('approver_role', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('requested_by_id', sa.BigInteger(), nullable=True),
    sa.Column('requested_by_label', sa.String(length=255), nullable=False),
    sa.Column('decided_by_id', sa.BigInteger(), nullable=True),
    sa.Column('decided_by_label', sa.String(length=255), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('pending','approved','rejected')", name=('ck_approvals_valid_status')),
    sa.CheckConstraint('amount >= 0', name=('ck_approvals_non_negative_amount')),
    sa.ForeignKeyConstraint(['decided_by_id'], ['users.id'], name=('fk_approvals_decided_by_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['requested_by_id'], ['users.id'], name=('fk_approvals_requested_by_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_approvals')),
    sa.UniqueConstraint('kind', 'entity_id', name='uq_approvals_kind_entity')
    )
    op.create_index(('ix_approvals_requested_by_id'), 'approvals', ['requested_by_id'], unique=False)
    op.create_index(('ix_approvals_status'), 'approvals', ['status'], unique=False)
    op.create_index('ix_approvals_status_kind', 'approvals', ['status', 'kind'], unique=False)
    op.create_table('approval_comments',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('approval_id', sa.BigInteger(), nullable=False),
    sa.Column('author_id', sa.BigInteger(), nullable=True),
    sa.Column('author_label', sa.String(length=255), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['approval_id'], ['approvals.id'], name=('fk_approval_comments_approval_id_approvals'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], name=('fk_approval_comments_author_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_approval_comments'))
    )
    op.create_index(('ix_approval_comments_approval_id'), 'approval_comments', ['approval_id'], unique=False)

    # Financial and approval records are never deleted.
    op.execute("CREATE TRIGGER approvals_no_delete BEFORE DELETE ON approvals FOR EACH ROW EXECUTE FUNCTION billing_no_delete()")
    op.execute("CREATE TRIGGER approval_comments_no_delete BEFORE DELETE ON approval_comments FOR EACH ROW EXECUTE FUNCTION billing_no_delete()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS approvals_no_delete ON approvals")
    op.execute("DROP TRIGGER IF EXISTS approval_comments_no_delete ON approval_comments")

    op.drop_table('approval_comments')
    op.drop_table('approvals')
    op.drop_table('approval_policies')
