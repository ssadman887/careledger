"""platform: idempotency_keys

Revision ID: 0008_idempotency
Revises: 0007_billing
Create Date: 2026-11-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql  # noqa: F401

revision: str = "0008_idempotency"
down_revision: str | None = "0007_billing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('idempotency_keys',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('scope', sa.String(length=80), nullable=False),
    sa.Column('actor_key', sa.String(length=40), nullable=False),
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('response_status', sa.Integer(), nullable=True),
    sa.Column('response_body', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('actor_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=('fk_idempotency_keys_actor_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_idempotency_keys')),
    sa.UniqueConstraint('scope', 'actor_key', 'key', name='uq_idempotency_keys_scope_actor_key')
    )
    op.create_index(('ix_idempotency_keys_actor_id'), 'idempotency_keys', ['actor_id'], unique=False)



def downgrade() -> None:

    op.drop_table('idempotency_keys')
