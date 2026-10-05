from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Booking, Room
from ..schemas import RoomCreate, RoomRead, RoomUpdate

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


def _get_room_or_404(db: Session, room_id: int) -> Room:
    room = db.get(Room, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


@router.get("", response_model=list[RoomRead], summary="List rooms")
def list_rooms(
    active_only: bool = Query(False, description="Hide rooms that are switched off"),
    db: Session = Depends(get_db),
):
    stmt = select(Room).order_by(Room.building, Room.name)
    if active_only:
        stmt = stmt.where(Room.is_active.is_(True))
    return db.scalars(stmt).all()


@router.post("", response_model=RoomRead, status_code=201, summary="Create a room")
def create_room(payload: RoomCreate, db: Session = Depends(get_db)):
    room = Room(**payload.model_dump())
    db.add(room)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A room with this name already exists") from exc
    return room


@router.get("/{room_id}", response_model=RoomRead, summary="Get one room")
def get_room(room_id: int, db: Session = Depends(get_db)):
    return _get_room_or_404(db, room_id)


@router.put("/{room_id}", response_model=RoomRead, summary="Replace a room")
def update_room(room_id: int, payload: RoomUpdate, db: Session = Depends(get_db)):
    room = _get_room_or_404(db, room_id)
    for field, value in payload.model_dump().items():
        setattr(room, field, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A room with this name already exists") from exc
    return room


@router.delete("/{room_id}", status_code=204, summary="Delete a room")
def delete_room(room_id: int, db: Session = Depends(get_db)):
    room = _get_room_or_404(db, room_id)
    booking_count = db.scalar(
        select(func.count()).select_from(Booking).where(Booking.room_id == room_id)
    )
    if booking_count:
        raise HTTPException(
            status_code=409,
            detail="Room still has bookings; switch it off with is_active=false instead",
        )
    db.delete(room)
    db.commit()
    return Response(status_code=204)
