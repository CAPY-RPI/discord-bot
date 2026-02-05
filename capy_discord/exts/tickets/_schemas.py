"""Pydantic schemas for ticket forms."""

from pydantic import BaseModel, Field


class TicketSchema(BaseModel):
    """Base schema for all ticket forms.

    Provides a typed contract ensuring all ticket cogs have:
    - title: Brief summary field
    - description: Detailed description field
    """

    title: str
    description: str


class FeedbackForm(TicketSchema):
    """Schema for feedback submission form."""

    title: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Brief summary of your feedback",
    )

    description: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Please provide your detailed feedback...",
    )
