from pydantic import BaseModel, Field


class EventFeedbackSchema(BaseModel):
    """Pydantic model defining the Event Feedback schema and validation rules."""

    rating: int = Field(title="Rating", description="Event rating from 1 to 10", ge=1, le=10)
    improvement_suggestion: str | None = Field(
        title="Improvement Suggestion",
        description="What could the club do to make the event better?",
        max_length=1000,
        default=None,
    )
