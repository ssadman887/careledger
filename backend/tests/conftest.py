"""Test fixtures.

Integration tests need PostgreSQL (`docker compose up -d db`). The test database
(`careledger_test` by default) is recreated from migrations once per session; every test then
runs inside an outer transaction that is rolled back, so tests are isolated and fast.
"""

import os
from collections.abc import Iterator

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://careledger:careledger@localhost:5432/careledger_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import Connection, Engine, make_url  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _recreate_database(url: str) -> None:
    parsed = make_url(url)
    admin = create_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :d AND pid <> pg_backend_pid()"
            ),
            {"d": parsed.database},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{parsed.database}"'))
        conn.execute(text(f'CREATE DATABASE "{parsed.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    _recreate_database(TEST_DATABASE_URL)
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(cfg, "head")

    from app.core.db import engine as app_engine
    from app.core.db import session_scope
    from seed.billing import seed_catalog, seed_patients, seed_visits
    from seed.insurance import seed_insurance_registry
    from seed.ledger import seed_ledger
    from seed.users import seed_roles, seed_users

    with session_scope() as s:
        seed_users(s, seed_roles(s))
        seed_ledger(s)
        # Catalog, patients and visits only: no sample invoices, so ledger/report tests stay exact.
        seed_catalog(s)
        seed_visits(s, seed_patients(s))
        seed_insurance_registry(s)  # denial codes, insurers, policies (no claims)
    yield app_engine
    app_engine.dispose()


@pytest.fixture
def connection(engine: Engine) -> Iterator[Connection]:
    conn = engine.connect()
    outer = conn.begin()
    try:
        yield conn
    finally:
        if outer.is_active:
            outer.rollback()
        conn.close()


@pytest.fixture
def db(connection: Connection) -> Iterator[Session]:
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        yield session
    finally:
        session.close()


def check_deferred(session: Session) -> None:
    """Fire pending deferred constraint triggers now (tests never really COMMIT)."""
    session.flush()
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    session.execute(text("SET CONSTRAINTS ALL DEFERRED"))


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    from app.core.db import get_db
    from app.main import app

    def _override() -> Iterator[Session]:
        try:
            yield db
            check_deferred(db)  # run deferred ledger triggers as a real COMMIT would
            db.commit()  # releases the savepoint; outer transaction still rolls back
        except Exception:
            db.rollback()
            raise

    app.dependency_overrides[get_db] = _override
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def demo_password() -> str:
    from app.core.config import get_settings

    return get_settings().demo_password


@pytest.fixture
def login(client: TestClient, demo_password: str):  # type: ignore[no-untyped-def]
    """Return a function that logs in a demo user and returns auth headers."""

    def _login(username: str) -> dict[str, str]:
        resp = client.post(
            "/api/v1/auth/login", json={"login": username, "password": demo_password}
        )
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    return _login


@pytest.fixture
def actor_for(db: Session):  # type: ignore[no-untyped-def]
    """Build a service-layer Actor for a seeded demo user."""
    from sqlalchemy import select

    from app.models.identity import User
    from app.services.auth import actor_for as make_actor

    def _actor(username: str):  # type: ignore[no-untyped-def]
        user = db.scalars(select(User).where(User.username == username)).one()
        return make_actor(user)

    return _actor


@pytest.fixture
def acct(db: Session):  # type: ignore[no-untyped-def]
    """Look up seeded account ids by code."""
    from sqlalchemy import select

    from app.models.ledger import Account

    ids = {a.code: a.id for a in db.scalars(select(Account)).all()}
    return lambda code: ids[code]
