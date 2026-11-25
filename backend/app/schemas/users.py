from datetime import datetime

from pydantic import Field

from app.models.identity import RoleName
from app.schemas.common import OrmModel

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
USERNAME_PATTERN = r"^[a-zA-Z0-9_.-]{3,64}$"


class RoleOut(OrmModel):
    name: str
    description: str


class UserOut(OrmModel):
    id: int
    email: str
    username: str
    full_name: str
    is_active: bool
    roles: list[str] = Field(validation_alias="role_names")
    last_login_at: datetime | None
    created_at: datetime


class UserCreate(OrmModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=255)
    username: str = Field(pattern=USERNAME_PATTERN)
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=255)
    roles: list[RoleName] = Field(min_length=1)


class UserUpdate(OrmModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    roles: list[RoleName] | None = Field(default=None, min_length=1)
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=255)
