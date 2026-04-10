from pydantic import BaseModel, Field, field_validator

MIN_POLL_SLOTS = 2
MAX_POLL_SLOTS = 25


class WhenIsGoodPollSchema(BaseModel):
    """Schema for creating a lightweight availability poll."""

    title: str = Field(title="Poll Title", description="Short name for the availability poll", max_length=100)
    description: str = Field(
        title="Description",
        description="Optional context or instructions for voters",
        default="",
        max_length=500,
    )
    slots: str = Field(
        title="Time Slots",
        description="Enter one possible time per line, like 'Fri 6:00 PM' or 'Apr 14 7:30 PM'",
        max_length=1500,
    )

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            msg = "Poll title cannot be empty."
            raise ValueError(msg)
        return value

    @field_validator("slots")
    @classmethod
    def _validate_slots(cls, value: str) -> str:
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        if len(lines) < MIN_POLL_SLOTS:
            msg = f"Please provide at least {MIN_POLL_SLOTS} time slots."
            raise ValueError(msg)
        if len(lines) > MAX_POLL_SLOTS:
            msg = f"Please limit availability polls to {MAX_POLL_SLOTS} time slots."
            raise ValueError(msg)
        return "\n".join(lines)
