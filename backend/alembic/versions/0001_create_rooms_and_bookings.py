"""create rooms and bookings tables

Revision ID: 0001
Revises:
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rooms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("building", sa.String(80), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("name", name="uq_rooms_name"),
        sa.CheckConstraint("capacity > 0", name="ck_rooms_capacity_positive"),
        sa.CheckConstraint("kind IN ('lab', 'classroom', 'seminar')", name="ck_rooms_kind"),
    )

    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "room_id",
            sa.Integer(),
            sa.ForeignKey("rooms.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(120), nullable=False),
        sa.Column("booked_by", sa.String(80), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="confirmed"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("end_time > start_time", name="ck_bookings_end_after_start"),
        sa.CheckConstraint("status IN ('confirmed', 'cancelled')", name="ck_bookings_status"),
    )
    op.create_index("ix_bookings_room_start", "bookings", ["room_id", "start_time"])
    op.create_index("ix_bookings_start_time", "bookings", ["start_time"])


def downgrade() -> None:
    op.drop_index("ix_bookings_start_time", table_name="bookings")
    op.drop_index("ix_bookings_room_start", table_name="bookings")
    op.drop_table("bookings")
    op.drop_table("rooms")
