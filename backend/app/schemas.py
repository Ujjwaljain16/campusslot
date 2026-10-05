from datetime import UTC, date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import get_settings

RoomKind = Literal["lab", "classroom", "seminar"]
BookingStatus = Literal["confirmed", "cancelled"]


class RoomBase(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    building: str = Field(min_length=1, max_length=80)
    capacity: int = Field(ge=1, le=1000)
    kind: RoomKind
    is_active: bool = True


class RoomCreate(RoomBase):
    pass


class RoomUpdate(RoomBase):
    pass


class RoomRead(RoomBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


class BookingBase(BaseModel):
    room_id: int = Field(ge=1)
    purpose: str = Field(min_length=1, max_length=120)
    booked_by: str = Field(min_length=1, max_length=80)
    start_time: datetime
    end_time: datetime

    @field_validator("start_time", "end_time")
    @classmethod
    def normalise_to_utc(cls, value: datetime) -> datetime:
        # A timestamp without a zone is interpreted as UTC so comparisons are never ambiguous.
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def check_time_range(self) -> "BookingBase":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        longest = timedelta(hours=get_settings().max_booking_hours)
        if self.end_time - self.start_time > longest:
            raise ValueError(f"a booking cannot be longer than {longest}")
        return self


class BookingCreate(BookingBase):
    pass


class BookingUpdate(BookingBase):
    status: BookingStatus = "confirmed"


class BookingRead(BookingBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: BookingStatus
    created_at: datetime


class RoomUtilisation(BaseModel):
    room_id: int
    name: str
    booked_minutes: int
    utilisation_pct: float


class BookingStats(BaseModel):
    day: date
    total_confirmed: int
    day_confirmed: int
    rooms_in_use_now: int
    average_utilisation_pct: float
    busiest_room: RoomUtilisation | None
    rooms: list[RoomUtilisation]
