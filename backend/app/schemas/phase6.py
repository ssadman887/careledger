"""Schemas for dashboards, notifications and global search."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import OrmModel

Format = Literal["money", "count", "percent", "text", "date"]


class KpiOut(BaseModel):
    key: str
    label: str
    value: str  # money and percents are decimal strings
    format: Format
    hint: str
    href: str
    tone: Literal["default", "good", "warning", "bad"]


class SeriesKeyOut(BaseModel):
    key: str
    label: str
    format: Format


class ChartRowOut(BaseModel):
    label: str
    values: dict[str, str]


class ChartOut(BaseModel):
    id: str
    title: str
    kind: Literal["bar", "line", "area", "donut", "hbar"]
    keys: list[SeriesKeyOut]
    rows: list[ChartRowOut]
    description: str


class TableColumnOut(BaseModel):
    key: str
    label: str
    format: Format


class SmallTableOut(BaseModel):
    id: str
    title: str
    columns: list[TableColumnOut]
    rows: list[dict[str, str]]


class SectionOut(BaseModel):
    id: Literal["finance", "revenue", "insurance", "administration"]
    title: str
    description: str
    kpis: list[KpiOut]
    charts: list[ChartOut]
    tables: list[SmallTableOut]


class DashboardOut(BaseModel):
    as_of: date
    sections: list[SectionOut]


class NotificationOut(OrmModel):
    id: int
    kind: str
    level: Literal["info", "success", "warning", "action"]
    title: str
    body: str
    link: str
    read_at: datetime | None
    created_at: datetime


class UnreadCountOut(BaseModel):
    unread: int


class MarkedOut(BaseModel):
    marked: int


class SearchHitOut(BaseModel):
    id: int
    title: str
    subtitle: str
    href: str


class SearchGroupOut(BaseModel):
    type: str
    label: str
    hits: list[SearchHitOut]


class SearchOut(BaseModel):
    query: str
    groups: list[SearchGroupOut]
