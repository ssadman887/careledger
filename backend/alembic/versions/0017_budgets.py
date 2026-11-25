"""budgets, budget lines and alerts

Revision ID: 0017_budgets
Revises: 0016_payroll
Create Date: 2026-11-25 17:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0017_budgets'
down_revision: str | None = '0016_payroll'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('budgets',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('department_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('alert_threshold_percent', sa.Numeric(precision=5, scale=2), server_default='90.00', nullable=False),
    sa.Column('notes', sa.Text(), server_default='', nullable=False),
    sa.Column('created_by_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('draft','active','archived')", name=op.f('ck_budgets_valid_status')),
    sa.CheckConstraint('alert_threshold_percent > 0 AND alert_threshold_percent <= 100', name=op.f('ck_budgets_valid_threshold')),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_budgets_created_by_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_budgets_department_id_departments'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_budgets')),
    sa.UniqueConstraint('year', 'department_id', name='uq_budgets_year_department')
    )
    op.create_index(op.f('ix_budgets_department_id'), 'budgets', ['department_id'], unique=False)
    op.create_index(op.f('ix_budgets_status'), 'budgets', ['status'], unique=False)
    op.create_index(op.f('ix_budgets_year'), 'budgets', ['year'], unique=False)
    op.create_table('budget_alerts',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('budget_id', sa.BigInteger(), nullable=False),
    sa.Column('account_id', sa.BigInteger(), nullable=False),
    sa.Column('month', sa.Integer(), nullable=False),
    sa.Column('level', sa.String(length=20), nullable=False),
    sa.Column('budget_ytd', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('actual_ytd', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('percent_used', sa.Numeric(precision=7, scale=2), nullable=False),
    sa.Column('message', sa.String(length=300), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("level IN ('warning','exceeded')", name=op.f('ck_budget_alerts_valid_level')),
    sa.CheckConstraint('month BETWEEN 1 AND 12', name=op.f('ck_budget_alerts_valid_month')),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_budget_alerts_account_id_accounts'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['budget_id'], ['budgets.id'], name=op.f('fk_budget_alerts_budget_id_budgets'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_budget_alerts')),
    sa.UniqueConstraint('budget_id', 'account_id', 'month', 'level', name='uq_budget_alerts_once')
    )
    op.create_index(op.f('ix_budget_alerts_budget_id'), 'budget_alerts', ['budget_id'], unique=False)
    op.create_table('budget_lines',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('budget_id', sa.BigInteger(), nullable=False),
    sa.Column('account_id', sa.BigInteger(), nullable=False),
    sa.Column('month', sa.Integer(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('amount >= 0', name=op.f('ck_budget_lines_non_negative_amount')),
    sa.CheckConstraint('month BETWEEN 1 AND 12', name=op.f('ck_budget_lines_valid_month')),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_budget_lines_account_id_accounts'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['budget_id'], ['budgets.id'], name=op.f('fk_budget_lines_budget_id_budgets'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_budget_lines')),
    sa.UniqueConstraint('budget_id', 'account_id', 'month', name='uq_budget_lines_month')
    )
    op.create_index(op.f('ix_budget_lines_account_id'), 'budget_lines', ['account_id'], unique=False)
    op.create_index(op.f('ix_budget_lines_budget_id'), 'budget_lines', ['budget_id'], unique=False)

    op.execute("CREATE TRIGGER budgets_no_delete BEFORE DELETE ON budgets FOR EACH ROW EXECUTE FUNCTION billing_no_delete()")
    # Alerts are an append-only history.
    op.execute("CREATE TRIGGER budget_alerts_append_only BEFORE DELETE OR UPDATE ON budget_alerts FOR EACH ROW EXECUTE FUNCTION billing_no_delete()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS budget_alerts_append_only ON budget_alerts")
    op.execute("DROP TRIGGER IF EXISTS budgets_no_delete ON budgets")
    op.drop_index(op.f('ix_budget_lines_budget_id'), table_name='budget_lines')
    op.drop_index(op.f('ix_budget_lines_account_id'), table_name='budget_lines')
    op.drop_table('budget_lines')
    op.drop_index(op.f('ix_budget_alerts_budget_id'), table_name='budget_alerts')
    op.drop_table('budget_alerts')
    op.drop_index(op.f('ix_budgets_year'), table_name='budgets')
    op.drop_index(op.f('ix_budgets_status'), table_name='budgets')
    op.drop_index(op.f('ix_budgets_department_id'), table_name='budgets')
    op.drop_table('budgets')
