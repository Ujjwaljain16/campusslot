from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..metrics import BOOKING_CONFLICTS, BOOKING_OPERATIONS
from ..models import Booking, Room
from ..schemas import (
    BookingCreate,
    BookingRead,
    BookingStats,
    BookingStatus,
    BookingUpdate,
    RoomUtilisation,
)

router = APIRouter(prefix="/api/bookings", tags=["bookings"])

# SQLSTATE raised by PostgreSQL when an EXCLUDE constraint is violated.
EXCLUSION_VIOLATION = "23P01"


def _local_day_start_utc(day: date, tz_offset_minutes: int) -> datetime:
    """Midnight of `day` in the caller's timezone, expressed in UTC."""
    midnight = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return midnight - timedelta(minutes=tz_offset_minutes)


def _find_conflict(
    db: Session,
    room_id: int,
    start: datetime,
    end: datetime,
    exclude_id: int | None = None,
) -> Booking | None:
    """Return a confirmed booking that overlaps [start, end), if one exists.

    The comparison is strict on both sides, so back-to-back bookings (one ending exactly when the
    next starts) are allowed.
    """
    stmt = select(Booking).where(
        Booking.room_id == room_id,
        Booking.status == "confirmed",
        Booking.start_time < end,
        Booking.end_time > start,
    )
    if exclude_id is not None:
        stmt = stmt.where(Booking.id != exclude_id)
    return db.scalars(stmt.limit(1)).first()


def _conflict_error(conflict: Booking | None, layer: str) -> HTTPException:
    BOOKING_CONFLICTS.labels(layer=layer).inc()
    detail: dict = {"message": "The room is already booked for part of this time"}
    if conflict is not None:
        detail["conflicting_booking"] = BookingRead.model_validate(conflict).model_dump(mode="json")
    return HTTPException(status_code=409, detail=detail)


def _is_exclusion_violation(exc: IntegrityError) -> bool:
    return getattr(exc.orig, "sqlstate", None) == EXCLUSION_VIOLATION


def _get_booking_or_404(db: Session, booking_id: int) -> Booking:
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking


def _require_room(db: Session, room_id: int, *, must_accept_bookings: bool) -> Room:
    room = db.get(Room, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    if must_accept_bookings and not room.is_active:
        raise HTTPException(status_code=409, detail="This room is switched off for bookings")
    return room


@router.get("", response_model=list[BookingRead], summary="List bookings")
def list_bookings(
    room_id: int | None = Query(None, ge=1),
    day: date | None = Query(None, description="Only bookings touching this local day"),
    tz_offset_minutes: int = Query(
        0, ge=-840, le=840, description="Minutes the caller is ahead of UTC"
    ),
    status: BookingStatus | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Booking).order_by(Booking.start_time, Booking.id)
    if room_id is not None:
        stmt = stmt.where(Booking.room_id == room_id)
    if status is not None:
        stmt = stmt.where(Booking.status == status)
    if day is not None:
        day_start = _local_day_start_utc(day, tz_offset_minutes)
        stmt = stmt.where(
            Booking.start_time < day_start + timedelta(days=1), Booking.end_time > day_start
        )
    return db.scalars(stmt.limit(limit).offset(offset)).all()


# Declared before "/{booking_id}" so that the word "stats" is never parsed as an id.
@router.get("/stats", response_model=BookingStats, summary="Utilisation for one day")
def booking_stats(
    day: date | None = Query(None, description="Defaults to today in the caller's timezone"),
    tz_offset_minutes: int = Query(0, ge=-840, le=840),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    now = datetime.now(UTC)
    if day is None:
        day = (now + timedelta(minutes=tz_offset_minutes)).date()

    midnight = _local_day_start_utc(day, tz_offset_minutes)
    window_start = midnight + timedelta(hours=settings.day_open_hour)
    window_end = midnight + timedelta(hours=settings.day_close_hour)
    window_minutes = int((window_end - window_start).total_seconds() // 60)

    rooms = db.scalars(select(Room).where(Room.is_active.is_(True)).order_by(Room.name)).all()
    day_bookings = db.scalars(
        select(Booking).where(
            Booking.status == "confirmed",
            Booking.start_time < midnight + timedelta(days=1),
            Booking.end_time > midnight,
        )
    ).all()

    booked: dict[int, int] = {room.id: 0 for room in rooms}
    for booking in day_bookings:
        if booking.room_id not in booked:
            continue
        overlap_start = max(booking.start_time, window_start)
        overlap_end = min(booking.end_time, window_end)
        if overlap_end > overlap_start:
            booked[booking.room_id] += int((overlap_end - overlap_start).total_seconds() // 60)

    per_room = [
        RoomUtilisation(
            room_id=room.id,
            name=room.name,
            booked_minutes=booked[room.id],
            utilisation_pct=round(booked[room.id] / window_minutes * 100, 1)
            if window_minutes
            else 0.0,
        )
        for room in rooms
    ]
    average = (
        round(sum(r.utilisation_pct for r in per_room) / len(per_room), 1) if per_room else 0.0
    )
    busiest = max(
        (r for r in per_room if r.booked_minutes > 0), key=lambda r: r.booked_minutes, default=None
    )

    total_confirmed = db.scalar(
        select(func.count()).select_from(Booking).where(Booking.status == "confirmed")
    )
    in_use_now = db.scalar(
        select(func.count(func.distinct(Booking.room_id))).where(
            Booking.status == "confirmed", Booking.start_time <= now, Booking.end_time > now
        )
    )

    return BookingStats(
        day=day,
        total_confirmed=total_confirmed or 0,
        day_confirmed=len(day_bookings),
        rooms_in_use_now=in_use_now or 0,
        average_utilisation_pct=average,
        busiest_room=busiest,
        rooms=per_room,
    )


@router.post("", response_model=BookingRead, status_code=201, summary="Create a booking")
def create_booking(payload: BookingCreate, db: Session = Depends(get_db)):
    _require_room(db, payload.room_id, must_accept_bookings=True)

    # Layer 1: friendly application check that explains which booking is in the way.
    conflict = _find_conflict(db, payload.room_id, payload.start_time, payload.end_time)
    if conflict is not None:
        raise _conflict_error(conflict, layer="application")

    booking = Booking(**payload.model_dump(), status="confirmed")
    db.add(booking)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # Layer 2: another request won the race between our check and our insert.
        if _is_exclusion_violation(exc):
            winner = _find_conflict(db, payload.room_id, payload.start_time, payload.end_time)
            raise _conflict_error(winner, layer="database") from exc
        raise
    BOOKING_OPERATIONS.labels(action="created").inc()
    return booking


@router.get("/{booking_id}", response_model=BookingRead, summary="Get one booking")
def get_booking(booking_id: int, db: Session = Depends(get_db)):
    return _get_booking_or_404(db, booking_id)


@router.put("/{booking_id}", response_model=BookingRead, summary="Replace a booking")
def update_booking(booking_id: int, payload: BookingUpdate, db: Session = Depends(get_db)):
    booking = _get_booking_or_404(db, booking_id)
    _require_room(db, payload.room_id, must_accept_bookings=payload.status == "confirmed")

    if payload.status == "confirmed":
        conflict = _find_conflict(
            db, payload.room_id, payload.start_time, payload.end_time, exclude_id=booking.id
        )
        if conflict is not None:
            raise _conflict_error(conflict, layer="application")

    for field, value in payload.model_dump().items():
        setattr(booking, field, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _is_exclusion_violation(exc):
            winner = _find_conflict(
                db, payload.room_id, payload.start_time, payload.end_time, exclude_id=booking_id
            )
            raise _conflict_error(winner, layer="database") from exc
        raise
    BOOKING_OPERATIONS.labels(action="updated").inc()
    return booking


@router.delete("/{booking_id}", status_code=204, summary="Delete a booking")
def delete_booking(booking_id: int, db: Session = Depends(get_db)):
    booking = _get_booking_or_404(db, booking_id)
    db.delete(booking)
    db.commit()
    BOOKING_OPERATIONS.labels(action="deleted").inc()
    return Response(status_code=204)
