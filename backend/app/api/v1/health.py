from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.core.db import engine
from app.schemas.common import Health

router = APIRouter(tags=["health"])


@router.get("/health", response_model=Health, summary="Liveness and database check")
def health() -> Health:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "ok"
    except SQLAlchemyError:
        db_status = "unavailable"
    return Health(status="ok", database=db_status, version=__version__)
