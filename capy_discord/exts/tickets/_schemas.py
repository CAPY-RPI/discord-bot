"""Pydantic schemas for ticket forms."""

from pydantic import BaseModel, Field


class FeedbackForm(BaseModel):
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
