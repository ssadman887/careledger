"""patients: patients, visits

Revision ID: 0005_patients
Revises: 0004_ledger
Create Date: 2026-11-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql  # noqa: F401

revision: str = "0005_patients"
down_revision: str | None = "0004_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('patients',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('mrn', sa.String(length=20), nullable=False),
    sa.Column('first_name', sa.String(length=80), nullable=False),
    sa.Column('last_name', sa.String(length=80), nullable=False),
    sa.Column('date_of_birth', sa.Date(), nullable=False),
    sa.Column('sex', sa.String(length=10), nullable=False),
    sa.Column('phone', sa.String(length=40), server_default='', nullable=False),
    sa.Column('email', sa.String(length=255), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("sex IN ('female','male','other','unknown')", name=('ck_patients_valid_sex')),
    sa.PrimaryKeyConstraint('id', name=('pk_patients')),
    sa.UniqueConstraint('mrn', name=('uq_patients_mrn'))
    )
    op.create_index('ix_patients_name', 'patients', ['last_name', 'first_name'], unique=False)
    op.create_table('visits',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('visit_number', sa.String(length=20), nullable=False),
    sa.Column('patient_id', sa.BigInteger(), nullable=False),
    sa.Column('department_id', sa.BigInteger(), nullable=False),
    sa.Column('visit_type', sa.String(length=20), nullable=False),
    sa.Column('admit_date', sa.Date(), nullable=False),
    sa.Column('discharge_date', sa.Date(), nullable=True),
    sa.Column('attending_physician', sa.String(length=120), server_default='', nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('open','closed','cancelled')", name=('ck_visits_valid_status')),
    sa.CheckConstraint("visit_type IN ('outpatient','inpatient','emergency')", name=('ck_visits_valid_type')),
    sa.CheckConstraint('discharge_date IS NULL OR discharge_date >= admit_date', name=('ck_visits_valid_dates')),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=('fk_visits_department_id_departments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], name=('fk_visits_patient_id_patients'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_visits')),
    sa.UniqueConstraint('visit_number', name=('uq_visits_visit_number'))
    )
    op.create_index(('ix_visits_admit_date'), 'visits', ['admit_date'], unique=False)
    op.create_index(('ix_visits_department_id'), 'visits', ['department_id'], unique=False)
    op.create_index(('ix_visits_patient_id'), 'visits', ['patient_id'], unique=False)
    op.create_index(('ix_visits_status'), 'visits', ['status'], unique=False)

    op.execute("CREATE SEQUENCE patient_mrn_seq START 1")
    op.execute("CREATE SEQUENCE visit_number_seq START 1")


def downgrade() -> None:

    op.execute("DROP SEQUENCE IF EXISTS visit_number_seq")
    op.execute("DROP SEQUENCE IF EXISTS patient_mrn_seq")
    op.drop_table('visits')
    op.drop_table('patients')
