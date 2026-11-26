"""Drop and recreate the application database, then migrate it (python -m seed --reset).

Connects to the server's `postgres` maintenance database with the application role, which owns
the CareLedger database. Refuses to run outside development.
"""

import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from alembic import command
from alembic.config import Config
from app.core.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]


def reset_database() -> None:
    settings = get_settings()
    if settings.environment != "development":
        sys.exit("Refusing to reset a non-development database (ENVIRONMENT != development).")
    url = make_url(settings.database_url)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :d AND pid <> pg_backend_pid()"
            ),
            {"d": url.database},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}"'))
        conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")
    print(f"Recreated and migrated database {url.database}.")
