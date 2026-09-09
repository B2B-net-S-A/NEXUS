"""Versioned, reviewable AND-of-OR requirements shared by search surfaces."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SkillRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    any_of: list[str] = Field(min_length=1, max_length=20)
    level: Literal["must", "nice", "excluded", "uncertain"] = "must"
    source: Literal["manual", "request", "champion", "title"] = "manual"
    evidence: str = Field(default="", max_length=4000)

    @field_validator("any_of")
    @classmethod
    def normalize_names(cls, value):
        names = list(dict.fromkeys(name.strip().lower() for name in value))
        if any(not name or len(name) > 100 for name in names):
            raise ValueError("Skill names must contain 1–100 characters")
        return names


class MatchingRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    reviewed: bool = False
    # Every must group is required; any alternative within it is sufficient.
    all_of: list[SkillRequirement] = Field(default_factory=list, max_length=100)
    missing_evidence_policy: Literal["review", "exclude"] = "review"
