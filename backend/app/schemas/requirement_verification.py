from datetime import datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class VerifyRequirementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    requirement_index: int = Field(ge=0, le=99)
    requirements_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    candidate_version: str = Field(min_length=1, max_length=100)
    status: Literal["met", "not_met", "unknown"]
    evidence: str = Field(min_length=1, max_length=4000)
    usage_context: str = Field(min_length=1, max_length=2000)
    verified_at: AwareDatetime

    @field_validator("verified_at")
    @classmethod
    def not_in_future(cls, value):
        if value > datetime.now(timezone.utc):
            raise ValueError("Verification date cannot be in the future")
        return value
