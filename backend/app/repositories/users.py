"""User, role and refresh-token queries."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.pagination import PageParams
from app.models.identity import RefreshToken, Role, User

_USER_SORTS = {
    "id": User.id,
    "email": User.email,
    "username": User.username,
    "full_name": User.full_name,
    "created_at": User.created_at,
}


def get(session: Session, user_id: int) -> User | None:
    return session.get(User, user_id)


def get_by_login(session: Session, login: str) -> User | None:
    value = login.strip().lower()
    stmt = select(User).where(
        or_(func.lower(User.email) == value, func.lower(User.username) == value),
        User.deleted_at.is_(None),
    )
    return session.scalars(stmt).first()


def exists_email_or_username(session: Session, email: str, username: str) -> bool:
    stmt = select(User.id).where(
        or_(func.lower(User.email) == email.lower(), func.lower(User.username) == username.lower())
    )
    return session.scalars(stmt).first() is not None


def list_users(
    session: Session,
    params: PageParams,
    *,
    search: str | None,
    role: str | None,
    is_active: bool | None,
) -> tuple[Sequence[User], int]:
    stmt = select(User).where(User.deleted_at.is_(None))
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(User.email).like(like),
                func.lower(User.username).like(like),
                func.lower(User.full_name).like(like),
            )
        )
    if role:
        stmt = stmt.where(User.roles.any(Role.name == role))
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    column = _USER_SORTS.get((params.sort or "id").lstrip("-"), User.id)
    order = column.desc() if (params.sort or "").startswith("-") else column.asc()
    rows = session.scalars(stmt.order_by(order).offset(params.offset).limit(params.page_size)).all()
    return rows, total


def roles_by_names(session: Session, names: Sequence[str]) -> list[Role]:
    return list(session.scalars(select(Role).where(Role.name.in_(names))).all())


def all_roles(session: Session) -> list[Role]:
    return list(session.scalars(select(Role).order_by(Role.name)).all())


def get_refresh_token(session: Session, jti: str) -> RefreshToken | None:
    return session.scalars(select(RefreshToken).where(RefreshToken.jti == jti)).first()


def add_refresh_token(session: Session, jti: str, user_id: int, expires_at: datetime) -> None:
    session.add(RefreshToken(jti=jti, user_id=user_id, expires_at=expires_at))
