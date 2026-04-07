from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field


class UserProfileIdentitySchema(BaseModel):
    """First-step profile fields that fit within a single Discord modal."""

    preferred_name: str = Field(title="Preferred Name", description="First and Last Name", max_length=50, default="")
    student_id: str = Field(
        title="Student ID",
        description="Your 9-digit Student ID",
        min_length=9,
        max_length=9,
        pattern=r"^\d+$",
        default="",
    )
    school_email: str = Field(
        title="School Email", description="ending in .edu", max_length=100, pattern=r".+\.edu$", default=""
    )
    graduation_year: int = Field(
        title="Graduation Year", description="YYYY", ge=1900, le=2100, default=datetime.now(ZoneInfo("UTC")).year + 4
    )
    major: str = Field(title="Major(s)", description="Comma separated (e.g. CS, ITWS)", max_length=100, default="")


class UserProfileDetailsSchema(BaseModel):
    """Second-step profile fields that complete the full profile."""

    minor: str = Field(title="Minor(s)", description="Comma separated (e.g. CS, ITWS)", max_length=100, default="")
    description: str = Field(title="Description", description="Something about you", max_length=500, default="")


class UserProfileSchema(BaseModel):
    """Pydantic model defining the User Profile schema and validation rules."""

    preferred_name: str = Field(title="Preferred Name", description="First and Last Name", max_length=50, default="")
    student_id: str = Field(
        title="Student ID",
        description="Your 9-digit Student ID",
        min_length=9,
        max_length=9,
        pattern=r"^\d+$",
        default="",
    )
    school_email: str = Field(
        title="School Email", description="ending in .edu", max_length=100, pattern=r".+\.edu$", default=""
    )
    graduation_year: int = Field(
        title="Graduation Year", description="YYYY", ge=1900, le=2100, default=datetime.now(ZoneInfo("UTC")).year + 4
    )
    major: str = Field(title="Major(s)", description="Comma separated (e.g. CS, ITWS)", max_length=100, default="")
    minor: str = Field(title="Minor(s)", description="Comma separated (e.g. CS, ITWS)", max_length=100, default="")
    description: str = Field(title="Description(s)", description="Something about you", max_length=500, default="")
