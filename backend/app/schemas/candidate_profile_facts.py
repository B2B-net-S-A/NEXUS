"""Typed API contracts for deterministic candidate-profile facts."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.models.recruitment_pipeline import PipelineStage

CefrLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]
LanguageProvenance = Literal[
    "manual",
    "cv",
    "traffit",
    "talent_radar",
    "csv",
    "legacy",
    "unknown",
]

_LANGUAGE_CODE_RE = re.compile(r"^[a-z][a-z0-9-]{1,15}$")
_LANGUAGE_NAME_TRANSLITERATION = str.maketrans(
    {
        "ł": "l",
        "Ł": "L",
        "đ": "d",
        "Đ": "D",
        "ð": "d",
        "Ð": "D",
        "ø": "o",
        "Ø": "O",
        "æ": "ae",
        "Æ": "AE",
        "œ": "oe",
        "Œ": "OE",
        "ß": "ss",
    }
)


def _language_name_identity(value: str) -> str:
    """Return a comparison-only key for duplicate display names."""

    translated = value.translate(_LANGUAGE_NAME_TRANSLITERATION)
    decomposed = unicodedata.normalize("NFKD", translated)
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(without_marks.casefold().split())


class CandidateLanguageWrite(BaseModel):
    """One item in the full replacement list accepted from profile editing."""

    model_config = ConfigDict(extra="forbid")

    language_code: str = Field(min_length=2, max_length=16)
    language_name: str = Field(min_length=1, max_length=100)
    cefr_level: Optional[CefrLevel] = None
    is_native: bool = False
    is_level_unknown: bool = True

    @field_validator("language_code", mode="before")
    @classmethod
    def normalize_language_code(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower().replace("_", "-")
            if not _LANGUAGE_CODE_RE.fullmatch(normalized):
                raise ValueError(
                    "language_code must be a 2-16 character lowercase language code"
                )
            return normalized
        return value

    @field_validator("language_name", mode="before")
    @classmethod
    def normalize_language_name(cls, value: object) -> object:
        if isinstance(value, str):
            return " ".join(value.split())
        return value

    @field_validator("cefr_level", mode="before")
    @classmethod
    def normalize_cefr_level(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper() or None
        return value

    @model_validator(mode="after")
    def validate_proficiency_state(self) -> "CandidateLanguageWrite":
        selected_states = sum(
            (
                self.cefr_level is not None,
                self.is_native,
                self.is_level_unknown,
            )
        )
        if selected_states != 1:
            raise ValueError(
                "exactly one proficiency state is required: CEFR, native, or unknown"
            )
        return self


class CandidateLanguagesPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    languages: list[CandidateLanguageWrite] = Field(
        default_factory=list,
        max_length=20,
    )

    @model_validator(mode="after")
    def validate_unique_languages(self) -> "CandidateLanguagesPut":
        codes = [language.language_code for language in self.languages]
        if len(codes) != len(set(codes)):
            raise ValueError("language_code must be unique within a candidate profile")
        names = [
            _language_name_identity(language.language_name)
            for language in self.languages
        ]
        if len(names) != len(set(names)):
            raise ValueError("language_name must be unique within a candidate profile")
        return self


class CandidateLanguageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    language_code: str
    language_name: str
    cefr_level: Optional[CefrLevel] = None
    is_native: bool
    is_level_unknown: bool
    provenance: LanguageProvenance
    manual_lock: bool
    version: int


class CandidateLanguagesResponse(BaseModel):
    candidate_id: int
    version: int
    languages: list[CandidateLanguageOut]


ProfileRateAmount = Annotated[
    Decimal,
    Field(ge=0, max_digits=10, decimal_places=2),
]


class CandidateProfileRatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Required-but-nullable: only an explicit {"amount": null} clears the fact.
    amount: Optional[ProfileRateAmount]


class CandidateProfileRateResponse(BaseModel):
    candidate_id: int
    amount: Optional[Decimal]
    currency: Literal["PLN"] = "PLN"
    unit: Literal["hour"] = "hour"
    tax_basis: Literal["net"] = "net"
    contract_type: Literal["b2b"] = "b2b"
    version: int
    updated_at: Optional[datetime] = None

    @field_serializer("amount", when_used="json")
    def serialize_amount(self, amount: Optional[Decimal]) -> Optional[str]:
        return f"{amount:.2f}" if amount is not None else None


class RecentRecruitmentItem(BaseModel):
    job_id: int
    job_title: str
    client_id: int
    client_name: Optional[str] = None
    latest_stage_id: int
    stage: PipelineStage
    stage_label: str
    last_activity_at: datetime


class CandidateRecentRecruitmentsResponse(BaseModel):
    candidate_id: int
    items: list[RecentRecruitmentItem]
