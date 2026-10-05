"""prevent overlapping confirmed bookings at the database level

The application checks for overlaps first so it can explain which booking is in the way, but two
requests can still pass that check at the same instant. This PostgreSQL EXCLUDE constraint is the
final safety net: the database itself refuses two confirmed bookings for one room that overlap.
Ranges are half-open ('[)') so a booking ending at 11:00 and another starting at 11:00 are allowed.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-05
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

CONSTRAINT = "ex_bookings_no_overlap"


def upgrade() -> None:
    # The constraint relies on PostgreSQL range types. The fast SQLite test database skips it,
    # and the application level check still protects it.
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        f"""
        ALTER TABLE bookings
        ADD CONSTRAINT {CONSTRAINT}
        EXCLUDE USING gist (
            room_id WITH =,
            tstzrange(start_time, end_time, '[)') WITH &&
        )
        WHERE (status = 'confirmed')
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE bookings DROP CONSTRAINT IF EXISTS {CONSTRAINT}")
