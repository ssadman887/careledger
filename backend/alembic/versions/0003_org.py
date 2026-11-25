"""org: departments, cost_centers

Revision ID: 0003_org
Revises: 0002_audit_log
Create Date: 2026-11-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_org"
down_revision: str | None = "0002_audit_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        # FK to accounts is added in 0004_ledger (accounts do not exist yet).
        sa.Column("revenue_account_id", sa.BigInteger(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_departments"),
        sa.UniqueConstraint("code", name="uq_departments_code"),
    )
    op.create_index("ix_departments_revenue_account_id", "departments", ["revenue_account_id"])
    op.create_table(
        "cost_centers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("department_id", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], name="fk_cost_centers_department_id_departments", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_cost_centers"),
        sa.UniqueConstraint("code", name="uq_cost_centers_code"),
    )
    op.create_index("ix_cost_centers_department_id", "cost_centers", ["department_id"])


def downgrade() -> None:
    op.drop_table("cost_centers")
    op.drop_table("departments")
