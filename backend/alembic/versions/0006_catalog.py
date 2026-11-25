"""catalog: services, price_lists, price_list_items

Revision ID: 0006_catalog
Revises: 0005_patients
Create Date: 2026-11-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql  # noqa: F401

revision: str = "0006_catalog"
down_revision: str | None = "0005_patients"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('services',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('department_id', sa.BigInteger(), nullable=False),
    sa.Column('tax_rate', sa.Numeric(precision=5, scale=4), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('tax_rate >= 0 AND tax_rate < 1', name=('ck_services_valid_tax_rate')),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=('fk_services_department_id_departments'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_services')),
    sa.UniqueConstraint('code', name=('uq_services_code'))
    )
    op.create_index(('ix_services_department_id'), 'services', ['department_id'], unique=False)
    op.create_table('price_lists',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('is_default', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=('pk_price_lists')),
    sa.UniqueConstraint('code', name=('uq_price_lists_code'))
    )
    op.create_table('price_list_items',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('price_list_id', sa.BigInteger(), nullable=False),
    sa.Column('service_id', sa.BigInteger(), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('effective_to', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('effective_to IS NULL OR effective_to >= effective_from', name=('ck_price_list_items_valid_range')),
    sa.CheckConstraint('unit_price >= 0', name=('ck_price_list_items_non_negative_price')),
    sa.ForeignKeyConstraint(['price_list_id'], ['price_lists.id'], name=('fk_price_list_items_price_list_id_price_lists'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['service_id'], ['services.id'], name=('fk_price_list_items_service_id_services'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=('pk_price_list_items')),
    sa.UniqueConstraint('price_list_id', 'service_id', 'effective_from', name='uq_price_list_items_start')
    )
    op.create_index(('ix_price_list_items_price_list_id'), 'price_list_items', ['price_list_id'], unique=False)
    op.create_index(('ix_price_list_items_service_id'), 'price_list_items', ['service_id'], unique=False)

    # Only one default price list.
    op.create_index("uq_price_lists_one_default", "price_lists", ["is_default"], unique=True,
                    postgresql_where=sa.text("is_default"))
    # No overlapping effective-date ranges for the same service on the same list.
    # btree_gist is a trusted extension (PG 13+): the database owner may create it.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        "ALTER TABLE price_list_items ADD CONSTRAINT price_list_items_no_overlap "
        "EXCLUDE USING gist (price_list_id WITH =, service_id WITH =, "
        "daterange(effective_from, effective_to, '[]') WITH &&)"
    )


def downgrade() -> None:

    op.execute("ALTER TABLE price_list_items DROP CONSTRAINT IF EXISTS price_list_items_no_overlap")
    op.drop_index("uq_price_lists_one_default", table_name="price_lists")
    op.drop_table('price_list_items')
    op.drop_table('price_lists')
    op.drop_table('services')
