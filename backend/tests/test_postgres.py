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
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models import Booking
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
    assert version == "0004"
    with pg_engine.connect() as connection:
        range_index = connection.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_bookings_time_range'")
        ).scalar_one_or_none()
    assert range_index is not None and "gist" in range_index


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


def test_range_overlap_gives_the_same_answer_as_two_comparisons_at_every_boundary(pg_engine):
    """The faster predicate must not change what counts as an overlap, above all for bookings that
    only touch: one that ends at 11:00 and one that starts at 11:00 are allowed."""
    from datetime import UTC, datetime

    room_id = first_room_id(pg_engine)
    with pg_engine.begin() as connection:
        connection.execute(text("DELETE FROM bookings"))
        connection.execute(
            text(
                "INSERT INTO bookings (room_id, purpose, booked_by, start_time, end_time, status) "
                "VALUES (:room, 'x', 'y', '2026-10-06 10:00+00', "
                "'2026-10-06 11:00+00', 'confirmed')"
            ),
            {"room": room_id},
        )

    def at(hour, minute=0):
        return datetime(2026, 10, 6, hour, minute, tzinfo=UTC)

    cases = [  # (start, end, overlaps)
        (at(9), at(10), False),  # ends exactly when the booking starts
        (at(11), at(12), False),  # starts exactly when the booking ends
        (at(8), at(9), False),
        (at(12), at(13), False),
        (at(9), at(10, 1), True),
        (at(10, 59), at(12), True),
        (at(10, 15), at(10, 45), True),  # inside
        (at(9), at(12), True),  # around
        (at(10), at(11), True),  # identical
    ]
    factory = sessionmaker(bind=pg_engine, autoflush=False)
    with factory() as session:
        for start, end, expected in cases:
            ranged = session.scalar(
                select(func.count())
                .select_from(Booking)
                .where(bookings_routes._overlaps(session, start, end))
            )
            comparisons = session.scalar(
                select(func.count())
                .select_from(Booking)
                .where(Booking.start_time < end, Booking.end_time > start)
            )
            assert ranged == comparisons == (1 if expected else 0), (start, end)


def test_running_now_includes_the_start_and_excludes_the_end(pg_engine):
    from datetime import UTC, datetime

    room_id = first_room_id(pg_engine)
    with pg_engine.begin() as connection:
        connection.execute(text("DELETE FROM bookings"))
        connection.execute(
            text(
                "INSERT INTO bookings (room_id, purpose, booked_by, start_time, end_time, status) "
                "VALUES (:room, 'x', 'y', '2026-10-06 10:00+00', "
                "'2026-10-06 11:00+00', 'confirmed')"
            ),
            {"room": room_id},
        )
    factory = sessionmaker(bind=pg_engine, autoflush=False)
    with factory() as session:

        def running(hour, minute=0):
            instant = datetime(2026, 10, 6, hour, minute, tzinfo=UTC)
            return session.scalar(
                select(func.count())
                .select_from(Booking)
                .where(bookings_routes._contains(session, instant))
            )

        assert running(9, 59) == 0
        assert running(10, 0) == 1  # a booking that starts now is running
        assert running(10, 59) == 1
        assert running(11, 0) == 0  # a booking that ends now is over


def test_overlap_queries_are_answered_from_an_index_on_a_large_table(pg_engine):
    """A regression guard for the scaling problem: with many rows, the overlap check and the day
    view must not read the whole table (see docs/engineering/data-scale.md)."""
    from datetime import UTC, datetime, timedelta

    with pg_engine.begin() as connection:
        connection.execute(text("DELETE FROM bookings"))
        connection.execute(
            text(
                "INSERT INTO bookings (room_id, purpose, booked_by, start_time, end_time, status) "
                "SELECT r.id, 'scale', 'u' || g, "
                "  timestamptz '2020-01-01 08:00+00' + (g / 6) * interval '1 hour', "
                "  timestamptz '2020-01-01 08:00+00' + (g / 6) * interval '1 hour' "
                "    + interval '50 minutes', "
                "  'confirmed' "
                "FROM generate_series(0, 29999) g "
                "JOIN (SELECT id, row_number() OVER (ORDER BY id) - 1 AS ri FROM rooms LIMIT 6) r "
                "  ON r.ri = g % 6"
            )
        )
        connection.execute(text("ANALYZE bookings"))

    start = datetime(2024, 3, 1, 8, 20, tzinfo=UTC)
    factory = sessionmaker(bind=pg_engine, autoflush=False)
    with factory() as session:
        room_id = first_room_id(pg_engine)
        statements = {
            "overlap check": select(Booking).where(
                Booking.room_id == room_id,
                Booking.status == "confirmed",
                bookings_routes._overlaps(session, start, start + timedelta(minutes=10)),
            ),
            "day view": select(Booking).where(
                bookings_routes._overlaps(session, start, start + timedelta(days=1))
            ),
        }
        for name, statement in statements.items():
            sql = str(
                statement.compile(
                    dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
                )
            )
            plan = "\n".join(row[0] for row in session.execute(text("EXPLAIN " + sql)).all())
            assert "Seq Scan" not in plan, f"{name} reads the whole table:\n{plan}"

    with pg_engine.begin() as connection:
        connection.execute(text("DELETE FROM bookings"))
