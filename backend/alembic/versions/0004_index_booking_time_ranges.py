"""index the time range of bookings so that "what overlaps this period" stays fast

The day view, the statistics and the overlap check all ask which bookings overlap a period. Written
as two comparisons (start before the end and end after the start) the question matches almost every
old row, so PostgreSQL scans the whole table and the cost grows with it: 32 ms for the overlap check
and 78 ms for the daily statistics at 200 thousand rows, against 0.05 ms at 1 thousand. Written with
the range overlap operator, the same question is answered from this GiST index in under a
millisecond. Measurements: docs/engineering/data-scale.md

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-06
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

INDEX = "ix_bookings_time_range"


def upgrade() -> None:
    # Range types exist only in PostgreSQL. The SQLite test database keeps the two comparisons.
    # On a large production table use CREATE INDEX CONCURRENTLY, which cannot run in a transaction.
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {INDEX} ON bookings "
        "USING gist (tstzrange(start_time, end_time, '[)'))"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DROP INDEX IF EXISTS {INDEX}")
