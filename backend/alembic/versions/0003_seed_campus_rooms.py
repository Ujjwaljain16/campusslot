"""seed the campus rooms so a fresh install is usable immediately

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

SEED_ROOMS = [
    {"name": "Computing Lab 1", "building": "Block A", "capacity": 40, "kind": "lab"},
    {"name": "Computing Lab 2", "building": "Block A", "capacity": 40, "kind": "lab"},
    {"name": "Electronics Lab", "building": "Block B", "capacity": 30, "kind": "lab"},
    {"name": "Classroom 101", "building": "Block A", "capacity": 60, "kind": "classroom"},
    {"name": "Classroom 102", "building": "Block A", "capacity": 60, "kind": "classroom"},
    {"name": "Seminar Hall", "building": "Main Building", "capacity": 120, "kind": "seminar"},
]

rooms = sa.table(
    "rooms",
    sa.column("name", sa.String),
    sa.column("building", sa.String),
    sa.column("capacity", sa.Integer),
    sa.column("kind", sa.String),
    sa.column("is_active", sa.Boolean),
)


def upgrade() -> None:
    connection = op.get_bind()
    existing = {row[0] for row in connection.execute(sa.text("SELECT name FROM rooms"))}
    new_rows = [{**room, "is_active": True} for room in SEED_ROOMS if room["name"] not in existing]
    if new_rows:
        op.bulk_insert(rooms, new_rows)


def downgrade() -> None:
    names = ", ".join(f"'{room['name']}'" for room in SEED_ROOMS)
    # Never delete a seeded room that people have already booked.
    op.execute(
        f"DELETE FROM rooms WHERE name IN ({names}) AND id NOT IN (SELECT room_id FROM bookings)"
    )
