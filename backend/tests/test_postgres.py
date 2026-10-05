"""PostgreSQL integration tests.

These run only when POSTGRES_TEST_URL points at a throw-away database (CI uses a service
container). They prove the things SQLite cannot: the Alembic chain on the real engine, the
EXCLUDE constraint, and the race between two requests that both pass the application check.
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.routes import bookings as bookings_routes

pytestmark = pytest.mark.postgres

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _test_url() -> str:
    url = os.environ.get("POSTGRES_TEST_URL")
    if not url:
        pytest.skip("POSTGRES_TEST_URL is not set")
    database = make_url(url).database or ""
    # The fixture drops every table, so refuse to run against anything that is not a test database.
    if "test" not in database:
        pytest.fail(f"refusing to wipe database {database!r}: its name must contain 'test'")
    return url


@pytest.fixture(scope="module")
def pg_engine():
    url = _test_url()
    engine = create_engine(url, pool_size=10)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(config, "head")
    if previous is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous
    get_settings.cache_clear()

    yield engine
    engine.dispose()


@pytest.fixture()
def pg_client(pg_engine):
    with pg_engine.begin() as connection:
        connection.execute(text("DELETE FROM bookings"))
    factory = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def first_room_id(pg_engine) -> int:
    with pg_engine.connect() as connection:
        return connection.execute(text("SELECT id FROM rooms ORDER BY id LIMIT 1")).scalar_one()


def payload(room_id: int, start: str, end: str) -> dict:
    return {
        "room_id": room_id,
        "purpose": "Concurrency test",
        "booked_by": "pytest",
        "start_time": f"2026-10-06T{start}:00Z",
        "end_time": f"2026-10-06T{end}:00Z",
    }


def test_migrations_create_the_schema_the_constraint_and_the_seed_rooms(pg_engine):
    with pg_engine.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        }
        constraint = connection.execute(
            text("SELECT contype FROM pg_constraint WHERE conname = 'ex_bookings_no_overlap'")
        ).scalar_one_or_none()
        seeded = connection.execute(text("SELECT count(*) FROM rooms")).scalar_one()
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    assert {"rooms", "bookings", "alembic_version"} <= tables
    assert constraint == "x"  # 'x' is PostgreSQL's code for an EXCLUDE constraint
    assert seeded >= 6
    assert version == "0003"


def test_database_rejects_overlapping_rows_even_without_the_application_check(pg_engine):
    room_id = first_room_id(pg_engine)
    insert = text(
        "INSERT INTO bookings (room_id, purpose, booked_by, start_time, end_time, status) "
        "VALUES (:room, 'x', 'y', :start, :end, :status)"
    )

    def row(start, end, status="confirmed"):
        return {"room": room_id, "start": start, "end": end, "status": status}

    with pg_engine.begin() as connection:
        connection.execute(text("DELETE FROM bookings"))
        connection.execute(insert, row("2026-10-06 10:00+00", "2026-10-06 11:00+00"))

    with pytest.raises(IntegrityError) as raised:
        with pg_engine.begin() as connection:
            connection.execute(insert, row("2026-10-06 10:30+00", "2026-10-06 11:30+00"))
    assert raised.value.orig.sqlstate == "23P01"  # exclusion_violation

    with pg_engine.begin() as connection:
        # Back-to-back is allowed, and a cancelled booking never blocks anything.
        connection.execute(insert, row("2026-10-06 11:00+00", "2026-10-06 12:00+00"))
        connection.execute(insert, row("2026-10-06 10:00+00", "2026-10-06 11:00+00", "cancelled"))


def test_api_returns_409_from_the_database_layer_when_the_application_check_is_bypassed(
    pg_client, pg_engine, monkeypatch
):
    room_id = first_room_id(pg_engine)
    assert (
        pg_client.post("/api/bookings", json=payload(room_id, "10:00", "11:00")).status_code == 201
    )

    real_find_conflict = bookings_routes._find_conflict
    calls = {"count": 0}

    def blind_first_call(*args, **kwargs):
        calls["count"] += 1
        # The first call is the application check, which we blind to simulate losing a race.
        return None if calls["count"] == 1 else real_find_conflict(*args, **kwargs)

    monkeypatch.setattr(bookings_routes, "_find_conflict", blind_first_call)
    response = pg_client.post("/api/bookings", json=payload(room_id, "10:30", "11:30"))

    assert response.status_code == 409
    assert "conflicting_booking" in response.json()["detail"]
    assert 'campusslot_booking_conflicts_total{layer="database"}' in pg_client.get("/metrics").text


def test_simultaneous_identical_requests_create_exactly_one_booking(pg_client, pg_engine):
    room_id = first_room_id(pg_engine)
    workers = 8
    barrier = threading.Barrier(workers)
    body = payload(room_id, "14:00", "15:00")

    def attempt(_):
        with TestClient(app) as client:
            barrier.wait()
            return client.post("/api/bookings", json=body).status_code

    with ThreadPoolExecutor(max_workers=workers) as pool:
        statuses = sorted(pool.map(attempt, range(workers)))

    assert statuses == [201] + [409] * (workers - 1)
    with pg_engine.connect() as connection:
        stored = connection.execute(
            text("SELECT count(*) FROM bookings WHERE room_id = :r"), {"r": room_id}
        ).scalar_one()
    assert stored == 1
