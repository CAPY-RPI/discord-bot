from __future__ import annotations

from datetime import date, time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Use pydantic-core's ValidationInfo for validator `info` typing
    from pydantic_core.core_schema import ValidationInfo as FieldValidationInfo
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT = "%H:%M"


class CreateMeetingSchema(BaseModel):
    """Schema used to create a scheduling event."""

    title: str = Field(title="Event Name", description="Short meeting name", max_length=100)
    start_date: date = Field(title="Start Date", description="YYYY-MM-DD")
    end_date: date = Field(title="End Date", description="YYYY-MM-DD")
    daily_hours: str = Field(
        title="Daily Hours",
        description="24-hour range like 09:00-22:00",
        max_length=20,
    )
    timezone: str = Field(
        title="Time Zone",
        description="IANA timezone like America/New_York",
        default="America/New_York",
        max_length=64,
    )

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            msg = "Event name cannot be empty."
            raise ValueError(msg)
        return cleaned

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _parse_date(cls, value: object) -> date | object:
        if isinstance(value, str):
            # Accept ISO date strings like YYYY-MM-DD
            return date.fromisoformat(value.strip())
        return value

    @field_validator("end_date")
    @classmethod
    def _validate_date_order(cls, value: date, info: FieldValidationInfo) -> date:
        start_date = info.data.get("start_date")
        if isinstance(start_date, date) and value < start_date:
            msg = "End date must be on or after start date."
            raise ValueError(msg)
        return value

    @field_validator("daily_hours")
    @classmethod
    def _validate_daily_hours(cls, value: str) -> str:
        cleaned = value.strip()
        try:
            start_raw, end_raw = cleaned.split("-", maxsplit=1)
            # Use time.fromisoformat for HH:MM parsing to avoid naive datetime creation
            start_time = time.fromisoformat(start_raw.strip())
            end_time = time.fromisoformat(end_raw.strip())
        except ValueError as exc:
            msg = "Use a range like 09:00-22:00."
            raise ValueError(msg) from exc

        if end_time <= start_time:
            msg = "End time must be later than start time."
            raise ValueError(msg)
        return cleaned

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        cleaned = value.strip()
        try:
            ZoneInfo(cleaned)
        except Exception as exc:  # pragma: no cover - zoneinfo raises multiple error shapes
            msg = "Enter a valid IANA timezone, like America/New_York."
            raise ValueError(msg) from exc
        return cleaned

    def parse_daily_hours(self) -> tuple[time, time]:
        """Return the configured daily start and end times."""
        start_raw, end_raw = self.daily_hours.split("-", maxsplit=1)
        start_time = time.fromisoformat(start_raw.strip())
        end_time = time.fromisoformat(end_raw.strip())
        return start_time, end_time


class ParticipantNameSchema(BaseModel):
    """Schema used when a participant joins an event."""

    display_name: str = Field(title="Your Name", description="Name shown on the schedule", max_length=50)

    @field_validator("display_name")
    @classmethod
    def _validate_display_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            msg = "Name cannot be empty."
            raise ValueError(msg)
        return cleaned
