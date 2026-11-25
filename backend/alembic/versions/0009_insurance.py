"""insurance: insurers, policies, denial_codes

Revision ID: 0009_insurance
Revises: 0008_idempotency
Create Date: 2026-11-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_insurance"
down_revision: str | None = "0008_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('insurers',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('payer_id', sa.String(length=40), server_default='', nullable=False),
    sa.Column('contact_email', sa.String(length=255), server_default='', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('approval_rate', sa.Numeric(precision=5, scale=4), nullable=False),
    sa.Column('partial_rate', sa.Numeric(precision=5, scale=4), nullable=False),
    sa.Column('denial_rate', sa.Numeric(precision=5, scale=4), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('approval_rate >= 0 AND partial_rate >= 0 AND denial_rate >= 0 AND approval_rate + partial_rate + denial_rate = 1', name=('ck_insurers_valid_rates')),
    sa.PrimaryKeyConstraint('id', name=('pk_insurers')),
    sa.UniqueConstraint('code', name=('uq_insurers_code'))
    )
    op.create_table('policies',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('policy_number', sa.String(length=40), nullable=False),
    sa.Column('patient_id', sa.BigInteger(), nullable=False),
    sa.Column('insurer_id', sa.BigInteger(), nullable=False),
    sa.Column('plan_name', sa.String(length=120), nullable=False),
    sa.Column('coverage_percent', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('copay', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('deductible', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('annual_limit', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('effective_to', sa.Date(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('copay >= 0 AND deductible >= 0 AND annual_limit >= 0', name=('ck_policies_non_negative')),
    sa.CheckConstraint('coverage_percent >= 0 AND coverage_percent <= 100', name=('ck_policies_valid_coverage')),
    sa.CheckConstraint('effective_to IS NULL OR effective_to >= effective_from', name=('ck_policies_valid_range')),
    sa.ForeignKeyConstraint(['insurer_id'], ['insurers.id'], name=('fk_policies_insurer_id_insurers'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], name=('fk_policies_patient_id_patients'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_policies')),
    sa.UniqueConstraint('insurer_id', 'policy_number', name='uq_policies_insurer_number')
    )
    op.create_index(('ix_policies_insurer_id'), 'policies', ['insurer_id'], unique=False)
    op.create_index(('ix_policies_patient_id'), 'policies', ['patient_id'], unique=False)
    op.create_table('denial_codes',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.Column('patient_responsibility', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=('pk_denial_codes')),
    sa.UniqueConstraint('code', name=('uq_denial_codes_code'))
    )



def downgrade() -> None:
    op.drop_table('denial_codes')
    op.drop_table('policies')
    op.drop_table('insurers')

