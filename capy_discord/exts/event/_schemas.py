from datetime import date, datetime, time

from pydantic import BaseModel, Field, field_validator


class EventSchema(BaseModel):
    """Pydantic model defining the Event schema and validation rules."""

    event_name: str = Field(title="Event Name", description="Name of the event", max_length=100)
    event_date: date = Field(
        title="Event Date",
        description="Date of the event (MM-DD-YYYY)",
        default_factory=date.today,
    )
    event_time: time = Field(
        title="Event Time",
        description="Time of the event (HH:MM, 24-hour) or (HH:MM AM/PM)",
        default_factory=lambda: datetime.now().astimezone().time(),
    )
    location: str = Field(title="Location", description="Location of the event", max_length=200, default="")
    description: str = Field(
        title="Description", description="Detailed description of the event", max_length=1000, default=""
    )

    @field_validator("event_date", mode="before")
    @classmethod
    def _parse_event_date(cls, value: object) -> date | object:
        if isinstance(value, str):
            value = value.strip()
            return datetime.strptime(f"{value} +0000", "%m-%d-%Y %z").date()
        return value

    @field_validator("event_time", mode="before")
    @classmethod
    def _parse_event_time(cls, value: object) -> time | object:
        if isinstance(value, str):
            value = value.strip()
            if " " in value:
                # Handle 00:XX AM/PM by converting to 12:XX AM/PM
                if value.lower().startswith("00:"):
                    value = "12:" + value[3:]
                parsed = datetime.strptime(f"{value} +0000", "%I:%M %p %z")
            else:
                parsed = datetime.strptime(f"{value} +0000", "%H:%M %z")
            return parsed.timetz().replace(tzinfo=None)
        return value
