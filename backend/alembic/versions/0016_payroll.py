"""payroll: employees, tax slabs, runs, payslips

Revision ID: 0016_payroll
Revises: 0015_bill_void
Create Date: 2026-11-25 17:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0016_payroll'
down_revision: str | None = '0015_bill_void'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('tax_slabs',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('lower_bound', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('upper_bound', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('rate', sa.Numeric(precision=5, scale=4), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('lower_bound >= 0', name=op.f('ck_tax_slabs_non_negative_lower')),
    sa.CheckConstraint('rate >= 0 AND rate < 1', name=op.f('ck_tax_slabs_valid_rate')),
    sa.CheckConstraint('upper_bound IS NULL OR upper_bound > lower_bound', name=op.f('ck_tax_slabs_valid_band')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tax_slabs')),
    sa.UniqueConstraint('year', 'lower_bound', name='uq_tax_slabs_year_lower')
    )
    op.create_index(op.f('ix_tax_slabs_year'), 'tax_slabs', ['year'], unique=False)
    op.create_table('employees',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('employee_number', sa.String(length=20), nullable=False),
    sa.Column('first_name', sa.String(length=80), nullable=False),
    sa.Column('last_name', sa.String(length=80), nullable=False),
    sa.Column('email', sa.String(length=255), server_default='', nullable=False),
    sa.Column('department_id', sa.BigInteger(), nullable=False),
    sa.Column('position', sa.String(length=120), nullable=False),
    sa.Column('hire_date', sa.Date(), nullable=False),
    sa.Column('termination_date', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('bank_reference', sa.String(length=80), server_default='', nullable=False),
    sa.Column('basic_salary', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('housing_allowance', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('transport_allowance', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('other_allowance', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('pension_rate', sa.Numeric(precision=5, scale=4), nullable=False),
    sa.Column('other_deduction', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('active','terminated')", name=op.f('ck_employees_valid_status')),
    sa.CheckConstraint('basic_salary >= 0 AND housing_allowance >= 0 AND transport_allowance >= 0 AND other_allowance >= 0 AND other_deduction >= 0', name=op.f('ck_employees_non_negative_pay')),
    sa.CheckConstraint('pension_rate >= 0 AND pension_rate <= 0.2', name=op.f('ck_employees_valid_pension_rate')),
    sa.CheckConstraint('termination_date IS NULL OR termination_date >= hire_date', name=op.f('ck_employees_valid_dates')),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_employees_department_id_departments'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_employees')),
    sa.UniqueConstraint('employee_number', name=op.f('uq_employees_employee_number'))
    )
    op.create_index(op.f('ix_employees_department_id'), 'employees', ['department_id'], unique=False)
    op.create_index(op.f('ix_employees_status'), 'employees', ['status'], unique=False)
    op.create_table('payroll_runs',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('run_number', sa.String(length=20), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('month', sa.Integer(), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('pay_date', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('employee_count', sa.Integer(), nullable=False),
    sa.Column('gross_total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('pension_total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('tax_total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('other_deduction_total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('net_total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('calculated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('posting_entry_id', sa.BigInteger(), nullable=True),
    sa.Column('funding_entry_id', sa.BigInteger(), nullable=True),
    sa.Column('payment_entry_id', sa.BigInteger(), nullable=True),
    sa.Column('approved_by_id', sa.BigInteger(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('queued','calculated','pending_approval','posted','paid','failed')", name=op.f('ck_payroll_runs_valid_status')),
    sa.CheckConstraint('month BETWEEN 1 AND 12', name=op.f('ck_payroll_runs_valid_month')),
    sa.CheckConstraint('net_total = gross_total - pension_total - tax_total - other_deduction_total', name=op.f('ck_payroll_runs_net_balances')),
    sa.ForeignKeyConstraint(['approved_by_id'], ['users.id'], name=op.f('fk_payroll_runs_approved_by_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_payroll_runs_created_by_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['funding_entry_id'], ['journal_entries.id'], name=op.f('fk_payroll_runs_funding_entry_id_journal_entries'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['payment_entry_id'], ['journal_entries.id'], name=op.f('fk_payroll_runs_payment_entry_id_journal_entries'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['posting_entry_id'], ['journal_entries.id'], name=op.f('fk_payroll_runs_posting_entry_id_journal_entries'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_runs')),
    sa.UniqueConstraint('run_number', name=op.f('uq_payroll_runs_run_number')),
    sa.UniqueConstraint('year', 'month', name='uq_payroll_runs_year_month')
    )
    op.create_index(op.f('ix_payroll_runs_status'), 'payroll_runs', ['status'], unique=False)
    op.create_table('payslips',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('payroll_run_id', sa.BigInteger(), nullable=False),
    sa.Column('employee_id', sa.BigInteger(), nullable=False),
    sa.Column('employee_number', sa.String(length=20), nullable=False),
    sa.Column('employee_name', sa.String(length=170), nullable=False),
    sa.Column('position', sa.String(length=120), nullable=False),
    sa.Column('department_id', sa.BigInteger(), nullable=False),
    sa.Column('days_in_month', sa.Integer(), nullable=False),
    sa.Column('days_worked', sa.Integer(), nullable=False),
    sa.Column('basic', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('housing', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('transport', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('other_allowance', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('gross', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('pension', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('taxable', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('income_tax', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('other_deduction', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('net', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('days_worked BETWEEN 1 AND days_in_month', name=op.f('ck_payslips_valid_days')),
    sa.CheckConstraint('gross = basic + housing + transport + other_allowance', name=op.f('ck_payslips_gross_balances')),
    sa.CheckConstraint('net = gross - pension - income_tax - other_deduction AND net >= 0', name=op.f('ck_payslips_net_balances')),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_payslips_department_id_departments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_payslips_employee_id_employees'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['payroll_run_id'], ['payroll_runs.id'], name=op.f('fk_payslips_payroll_run_id_payroll_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payslips')),
    sa.UniqueConstraint('payroll_run_id', 'employee_id', name='uq_payslips_run_employee')
    )
    op.create_index(op.f('ix_payslips_department_id'), 'payslips', ['department_id'], unique=False)
    op.create_index('ix_payslips_employee', 'payslips', ['employee_id'], unique=False)
    op.create_index(op.f('ix_payslips_payroll_run_id'), 'payslips', ['payroll_run_id'], unique=False)

    op.execute("CREATE TRIGGER employees_no_delete BEFORE DELETE ON employees FOR EACH ROW EXECUTE FUNCTION billing_no_delete()")
    op.execute("CREATE TRIGGER payroll_runs_no_delete BEFORE DELETE ON payroll_runs FOR EACH ROW EXECUTE FUNCTION billing_no_delete()")
    # Once a run is posted its figures are frozen; only payment fields may change.
    op.execute("""
CREATE OR REPLACE FUNCTION payroll_run_frozen() RETURNS trigger AS $$
BEGIN
  IF OLD.status IN ('posted','paid') AND (
       NEW.gross_total <> OLD.gross_total OR NEW.net_total <> OLD.net_total
       OR NEW.tax_total <> OLD.tax_total OR NEW.pension_total <> OLD.pension_total
       OR NEW.other_deduction_total <> OLD.other_deduction_total
       OR NEW.employee_count <> OLD.employee_count
       OR NEW.status NOT IN ('posted','paid')
       OR NEW.posting_entry_id IS DISTINCT FROM OLD.posting_entry_id) THEN
    RAISE EXCEPTION 'payroll run % is posted and cannot be changed', OLD.run_number
      USING ERRCODE = 'P0001';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql
""")
    op.execute("CREATE TRIGGER payroll_runs_frozen BEFORE UPDATE ON payroll_runs FOR EACH ROW EXECUTE FUNCTION payroll_run_frozen()")
    op.execute("""
CREATE OR REPLACE FUNCTION payslip_frozen() RETURNS trigger AS $$
DECLARE run_status text;
BEGIN
  SELECT status INTO run_status FROM payroll_runs WHERE id = OLD.payroll_run_id;
  IF run_status IN ('posted','paid') THEN
    RAISE EXCEPTION 'payslips of a posted payroll run cannot be changed' USING ERRCODE = 'P0001';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql
""")
    op.execute("CREATE TRIGGER payslips_frozen BEFORE UPDATE OR DELETE ON payslips FOR EACH ROW EXECUTE FUNCTION payslip_frozen()")
    op.execute("CREATE SEQUENCE employee_number_seq START 1")


def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS employee_number_seq")
    op.execute("DROP TRIGGER IF EXISTS payslips_frozen ON payslips")
    op.execute("DROP FUNCTION IF EXISTS payslip_frozen()")
    op.execute("DROP TRIGGER IF EXISTS payroll_runs_frozen ON payroll_runs")
    op.execute("DROP FUNCTION IF EXISTS payroll_run_frozen()")
    op.execute("DROP TRIGGER IF EXISTS payroll_runs_no_delete ON payroll_runs")
    op.execute("DROP TRIGGER IF EXISTS employees_no_delete ON employees")
    op.drop_index(op.f('ix_payslips_payroll_run_id'), table_name='payslips')
    op.drop_index('ix_payslips_employee', table_name='payslips')
    op.drop_index(op.f('ix_payslips_department_id'), table_name='payslips')
    op.drop_table('payslips')
    op.drop_index(op.f('ix_payroll_runs_status'), table_name='payroll_runs')
    op.drop_table('payroll_runs')
    op.drop_index(op.f('ix_employees_status'), table_name='employees')
    op.drop_index(op.f('ix_employees_department_id'), table_name='employees')
    op.drop_table('employees')
    op.drop_index(op.f('ix_tax_slabs_year'), table_name='tax_slabs')
    op.drop_table('tax_slabs')
