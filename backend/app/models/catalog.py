"""Service catalog and price lists with effective dates."""

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IntPK, TimestampMixin
from app.models.org import Department


class Service(TimestampMixin, Base):
    __tablename__ = "services"
    __table_args__ = (CheckConstraint("tax_rate >= 0 AND tax_rate < 1", name="valid_tax_rate"),)

    id: Mapped[IntPK]
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    department_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    # Fraction, e.g. 0.0500 = 5%. Most clinical services are tax-exempt (0).
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    department: Mapped[Department] = relationship(lazy="joined")


class PriceList(TimestampMixin, Base):
    __tablename__ = "price_lists"
    __table_args__ = (
        Index(
            "uq_price_lists_one_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id: Mapped[IntPK]
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class PriceListItem(TimestampMixin, Base):
    """A service's price on a list from `effective_from` to `effective_to` (inclusive, open-ended
    when null). Overlapping ranges for the same list+service are rejected by an exclusion
    constraint (migration 0006)."""

    __tablename__ = "price_list_items"
    __table_args__ = (
        CheckConstraint("unit_price >= 0", name="non_negative_price"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from", name="valid_range"
        ),
        UniqueConstraint(
            "price_list_id", "service_id", "effective_from", name="uq_price_list_items_start"
        ),
    )

    id: Mapped[IntPK]
    price_list_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("price_lists.id", ondelete="RESTRICT"), index=True
    )
    service_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("services.id", ondelete="RESTRICT"), index=True
    )
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
