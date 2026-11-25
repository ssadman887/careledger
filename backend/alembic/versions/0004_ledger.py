"""ledger: accounts, fiscal_periods, journal_entries, journal_lines + accounting safeguards

Revision ID: 0004_ledger
Revises: 0003_org
Create Date: 2026-11-25

Database-level safeguards (defence in depth; the service layer validates first):
  * journal_balanced          deferred constraint triggers: every posted entry has >= 2 lines and
                              sum(debit) = sum(credit), checked at commit.
  * journal_lines_immutable   rejects UPDATE/DELETE of lines belonging to a posted entry.
  * journal_entries_guard     rejects DELETE of any entry and UPDATE of a posted entry.
  * journal_entries_period    rejects posting dated outside an open fiscal period (row lock on
                              the period serialises against a concurrent close).
  * fiscal_periods_guard      closed periods cannot be reopened; periods cannot be deleted.
  * fiscal_periods_no_overlap exclusion constraint on the date range.
All raise SQLSTATE P0001, mapped by the API to 409 ledger_violation.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_ledger"
down_revision: str | None = "0003_org"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


MONEY = sa.Numeric(precision=14, scale=2)


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("cost_center_id", sa.BigInteger(), nullable=True),
        sa.Column("is_header", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        *_timestamps(),
        sa.CheckConstraint("type IN ('asset','liability','equity','revenue','expense')", name="ck_accounts_valid_type"),
        sa.CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_accounts_not_own_parent"),
        sa.ForeignKeyConstraint(["cost_center_id"], ["cost_centers.id"], name="fk_accounts_cost_center_id_cost_centers", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parent_id"], ["accounts.id"], name="fk_accounts_parent_id_accounts", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_accounts"),
        sa.UniqueConstraint("code", name="uq_accounts_code"),
    )
    op.create_index("ix_accounts_cost_center_id", "accounts", ["cost_center_id"])
    op.create_index("ix_accounts_parent_id", "accounts", ["parent_id"])
    op.create_index("ix_accounts_type", "accounts", ["type"])
    op.create_foreign_key(
        "fk_departments_revenue_account_id_accounts", "departments", "accounts",
        ["revenue_account_id"], ["id"], ondelete="RESTRICT",
    )

    op.create_table(
        "fiscal_periods",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=20), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by_id", sa.BigInteger(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("status IN ('open','closed')", name="ck_fiscal_periods_valid_status"),
        sa.CheckConstraint("end_date >= start_date", name="ck_fiscal_periods_valid_range"),
        sa.ForeignKeyConstraint(["closed_by_id"], ["users.id"], name="fk_fiscal_periods_closed_by_id_users", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_fiscal_periods"),
        sa.UniqueConstraint("name", name="uq_fiscal_periods_name"),
        sa.UniqueConstraint("start_date", name="uq_fiscal_periods_start_date"),
    )
    op.create_index("ix_fiscal_periods_status", "fiscal_periods", ["status"])
    op.execute(
        "ALTER TABLE fiscal_periods ADD CONSTRAINT fiscal_periods_no_overlap "
        "EXCLUDE USING gist (daterange(start_date, end_date, '[]') WITH &&)"
    )

    op.execute("CREATE SEQUENCE journal_entry_number_seq START 1")
    op.create_table(
        "journal_entries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("entry_number", sa.String(length=20), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("memo", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total", MONEY, nullable=False),
        sa.Column("reversal_of_id", sa.BigInteger(), nullable=True),
        sa.Column("reversal_reason", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.BigInteger(), nullable=True),
        sa.Column("approved_by_id", sa.BigInteger(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("(status = 'posted') = (posted_at IS NOT NULL)", name="ck_journal_entries_posted_at_matches_status"),
        sa.CheckConstraint("status IN ('pending_approval','posted','rejected')", name="ck_journal_entries_valid_status"),
        sa.CheckConstraint("total >= 0", name="ck_journal_entries_non_negative_total"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], name="fk_journal_entries_approved_by_id_users", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], name="fk_journal_entries_created_by_id_users", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reversal_of_id"], ["journal_entries.id"], name="fk_journal_entries_reversal_of_id_journal_entries", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_journal_entries"),
        sa.UniqueConstraint("entry_number", name="uq_journal_entries_entry_number"),
        sa.UniqueConstraint("reversal_of_id", name="uq_journal_entries_reversal_of_id"),
    )
    op.create_index("ix_journal_entries_created_by_id", "journal_entries", ["created_by_id"])
    op.create_index("ix_journal_entries_entry_date", "journal_entries", ["entry_date"])
    op.create_index("ix_journal_entries_source", "journal_entries", ["source_type", "source_id"])
    op.create_index("ix_journal_entries_status", "journal_entries", ["status"])

    op.create_table(
        "journal_lines",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("entry_id", sa.BigInteger(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("debit", MONEY, nullable=False),
        sa.Column("credit", MONEY, nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("department_id", sa.BigInteger(), nullable=True),
        sa.Column("cost_center_id", sa.BigInteger(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("(debit > 0) <> (credit > 0)", name="ck_journal_lines_one_sided"),
        sa.CheckConstraint("debit >= 0 AND credit >= 0", name="ck_journal_lines_non_negative"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_journal_lines_account_id_accounts", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cost_center_id"], ["cost_centers.id"], name="fk_journal_lines_cost_center_id_cost_centers", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], name="fk_journal_lines_department_id_departments", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["entry_id"], ["journal_entries.id"], name="fk_journal_lines_entry_id_journal_entries", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_journal_lines"),
        sa.UniqueConstraint("entry_id", "line_no", name="uq_journal_lines_entry_line"),
    )
    op.create_index("ix_journal_lines_account_id", "journal_lines", ["account_id"])
    op.create_index("ix_journal_lines_cost_center_id", "journal_lines", ["cost_center_id"])
    op.create_index("ix_journal_lines_department_id", "journal_lines", ["department_id"])
    op.create_index("ix_journal_lines_entry_id", "journal_lines", ["entry_id"])

    # ---- Safeguard 1: posted entries balance (checked at commit) ----
    op.execute(
        """
        CREATE FUNCTION ledger_check_entry_balance() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            eid bigint;
            st text;
            n integer;
            d numeric;
            c numeric;
        BEGIN
            IF TG_TABLE_NAME = 'journal_lines' THEN
                IF TG_OP = 'DELETE' THEN eid := OLD.entry_id; ELSE eid := NEW.entry_id; END IF;
            ELSE
                eid := NEW.id;
            END IF;
            SELECT status INTO st FROM journal_entries WHERE id = eid;
            IF st IS DISTINCT FROM 'posted' THEN
                RETURN NULL;
            END IF;
            SELECT count(*), coalesce(sum(debit), 0), coalesce(sum(credit), 0)
              INTO n, d, c FROM journal_lines WHERE entry_id = eid;
            IF n < 2 THEN
                RAISE EXCEPTION 'journal entry % must have at least 2 lines', eid USING ERRCODE = 'P0001';
            END IF;
            IF d <> c THEN
                RAISE EXCEPTION 'journal entry % is unbalanced: debits % <> credits %', eid, d, c
                    USING ERRCODE = 'P0001';
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER journal_lines_balanced
        AFTER INSERT OR UPDATE OR DELETE ON journal_lines
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION ledger_check_entry_balance();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER journal_entries_balanced
        AFTER INSERT OR UPDATE ON journal_entries
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION ledger_check_entry_balance();
        """
    )

    # ---- Safeguard 2: posted lines are immutable ----
    op.execute(
        """
        CREATE FUNCTION ledger_lines_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE st text;
        BEGIN
            SELECT status INTO st FROM journal_entries WHERE id = OLD.entry_id;
            IF st = 'posted' THEN
                RAISE EXCEPTION 'posted journal lines are immutable: % rejected (post a reversing entry instead)', TG_OP
                    USING ERRCODE = 'P0001';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER journal_lines_immutable
        BEFORE UPDATE OR DELETE ON journal_lines
        FOR EACH ROW EXECUTE FUNCTION ledger_lines_immutable();
        """
    )

    # ---- Safeguard 3: entries are never deleted; posted entries never change ----
    op.execute(
        """
        CREATE FUNCTION ledger_entries_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'journal entries cannot be deleted' USING ERRCODE = 'P0001';
            END IF;
            IF OLD.status = 'posted' THEN
                RAISE EXCEPTION 'posted journal entries are immutable (post a reversing entry instead)'
                    USING ERRCODE = 'P0001';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER journal_entries_guard
        BEFORE UPDATE OR DELETE ON journal_entries
        FOR EACH ROW EXECUTE FUNCTION ledger_entries_guard();
        """
    )

    # ---- Safeguard 4: postings only into open periods ----
    op.execute(
        """
        CREATE FUNCTION ledger_entries_open_period() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE pstatus text;
        BEGIN
            SELECT status INTO pstatus FROM fiscal_periods
             WHERE NEW.entry_date BETWEEN start_date AND end_date
             FOR SHARE;
            IF pstatus IS NULL THEN
                RAISE EXCEPTION 'no fiscal period covers %', NEW.entry_date USING ERRCODE = 'P0001';
            END IF;
            IF pstatus <> 'open' THEN
                RAISE EXCEPTION 'fiscal period for % is closed', NEW.entry_date USING ERRCODE = 'P0001';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER journal_entries_open_period
        BEFORE INSERT OR UPDATE ON journal_entries
        FOR EACH ROW WHEN (NEW.status = 'posted')
        EXECUTE FUNCTION ledger_entries_open_period();
        """
    )

    # ---- Safeguard 5: closed periods stay closed; periods are never deleted ----
    op.execute(
        """
        CREATE FUNCTION ledger_periods_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'fiscal periods cannot be deleted' USING ERRCODE = 'P0001';
            END IF;
            IF OLD.status = 'closed' THEN
                RAISE EXCEPTION 'fiscal period % is closed and locked', OLD.name USING ERRCODE = 'P0001';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER fiscal_periods_guard
        BEFORE UPDATE OR DELETE ON fiscal_periods
        FOR EACH ROW EXECUTE FUNCTION ledger_periods_guard();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS fiscal_periods_guard ON fiscal_periods")
    op.execute("DROP TRIGGER IF EXISTS journal_entries_open_period ON journal_entries")
    op.execute("DROP TRIGGER IF EXISTS journal_entries_guard ON journal_entries")
    op.execute("DROP TRIGGER IF EXISTS journal_lines_immutable ON journal_lines")
    op.execute("DROP TRIGGER IF EXISTS journal_entries_balanced ON journal_entries")
    op.execute("DROP TRIGGER IF EXISTS journal_lines_balanced ON journal_lines")
    op.drop_table("journal_lines")
    op.drop_table("journal_entries")
    op.execute("DROP SEQUENCE IF EXISTS journal_entry_number_seq")
    op.drop_table("fiscal_periods")
    op.drop_constraint("fk_departments_revenue_account_id_accounts", "departments", type_="foreignkey")
    op.drop_table("accounts")
    for fn in (
        "ledger_periods_guard", "ledger_entries_open_period", "ledger_entries_guard",
        "ledger_lines_immutable", "ledger_check_entry_balance",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {fn}()")
