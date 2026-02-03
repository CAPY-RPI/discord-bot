from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field


class EventSchema(BaseModel):
    """Pydantic model defining the Event schema and validation rules."""

    event_name: str = Field(title="Event Name", description="Name of the event", max_length=100)
    event_date: datetime = Field(
        title="Event Date",
        description="Date and time of the event in UTC",
        default_factory=lambda: datetime.now(tz=ZoneInfo("UTC")),
    )
    location: str = Field(title="Location", description="Location of the event", max_length=200, default="")
    description: str = Field(
        title="Description", description="Detailed description of the event", max_length=1000, default=""
    )
