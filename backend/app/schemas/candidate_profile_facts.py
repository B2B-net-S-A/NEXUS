"""Typed API contracts for deterministic candidate-profile facts."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
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
    "tr_legacy",
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


# ── Fakty z notatek rekruterów (22.09.2026) ────────────────────────────────

WorkMode = Literal["remote", "hybrid", "onsite"]
NotesFactField = Literal[
    "rate", "work_mode", "contract_form", "availability", "office_cities"
]


class NotesRateFact(BaseModel):
    value: Decimal
    currency: Optional[str] = None
    period: Optional[Literal["h", "md", "month"]] = None
    raw: Optional[str] = None
    as_of: Optional[str] = None
    hourly_pln: Optional[Decimal] = None
    flexibility: Optional[str] = None
    profile_amount: Optional[Decimal] = None
    profile_rate_version: int = 0
    can_apply: bool = False


class NotesWorkModeFact(BaseModel):
    modes: list[WorkMode]
    max_onsite_days: Optional[int] = None
    profile_modes: list[WorkMode]
    profile_max_onsite_days: Optional[int] = None
    can_apply: bool = False


class NotesContractFormFact(BaseModel):
    value: Literal["b2b", "uop", "any"]
    profile_contract_types: list[str]
    can_apply: bool = False


class NotesAvailabilityFact(BaseModel):
    raw: Optional[str] = None
    notice_period_text: Optional[str] = None
    available_from_text: Optional[str] = None
    notice_period: Optional[int] = None
    notice_period_unit: Optional[str] = None
    available_from: Optional[date] = None
    profile_notice_period: Optional[int] = None
    profile_notice_period_unit: Optional[str] = None
    profile_availability_date: Optional[date] = None
    can_apply: bool = False


class NotesOfficeCitiesFact(BaseModel):
    cities: list[str]
    profile_office_cities: list[str]
    can_apply: bool = False


class NotesRelocationFact(BaseModel):
    willing: Optional[bool] = None
    targets: list[str] = Field(default_factory=list)


class NotesEngagementFact(BaseModel):
    employer: Optional[str] = None
    project: Optional[str] = None
    ends_at: Optional[str] = None
    raw: Optional[str] = None


class NotesLanguageFact(BaseModel):
    name: str
    level: Optional[str] = None


class NotesClientVetoFact(BaseModel):
    client: str
    reason: Optional[str] = None


class CandidateNotesFactsResponse(BaseModel):
    """Co notatki rekruterów mówią o kandydacie, obok stanu profilu."""

    candidate_id: int
    extracted_at: Optional[str] = None
    has_facts: bool = False
    rate: Optional[NotesRateFact] = None
    work_mode: Optional[NotesWorkModeFact] = None
    contract_form: Optional[NotesContractFormFact] = None
    availability: Optional[NotesAvailabilityFact] = None
    office_cities: Optional[NotesOfficeCitiesFact] = None
    relocation: Optional[NotesRelocationFact] = None
    current_engagement: Optional[NotesEngagementFact] = None
    not_looking_until: Optional[str] = None
    languages: list[NotesLanguageFact] = Field(default_factory=list)
    sectors_prefer: list[str] = Field(default_factory=list)
    sectors_avoid: list[str] = Field(default_factory=list)
    client_vetoes: list[NotesClientVetoFact] = Field(default_factory=list)
    matching_facts: Optional[str] = None


class CandidateNotesFactApply(BaseModel):
    """Zapisz w profilu jedno pole wyliczone przez serwer z notatek.

    Przy stawce `expected_profile_rate_version` jest wymagane — to ta sama
    ochrona przed nadpisaniem cudzej, świeższej poprawki co w If-Match.
    """

    model_config = ConfigDict(extra="forbid")

    field: NotesFactField
    expected_profile_rate_version: Optional[int] = Field(default=None, ge=0)


class CandidateWorkModeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    remote_modes: list[WorkMode] = Field(default_factory=list)
    max_onsite_days_per_week: Optional[int] = Field(default=None, ge=0, le=7)

    @model_validator(mode="after")
    def _coherent(self) -> "CandidateWorkModeUpdate":
        modes = set(self.remote_modes)
        days = self.max_onsite_days_per_week
        if days is not None and modes:
            if modes == {"remote"} and days > 0:
                raise ValueError(
                    "Tylko zdalnie oznacza 0 dni w biurze — popraw tryb albo liczbę dni."
                )
            if days == 0 and modes - {"remote"}:
                raise ValueError(
                    "0 dni w biurze oznacza pracę wyłącznie zdalną — odznacz "
                    "hybrydę i pracę stacjonarną albo podaj liczbę dni."
                )
        return self


class CandidateWorkModeResponse(BaseModel):
    candidate_id: int
    remote_modes: list[WorkMode]
    max_onsite_days_per_week: Optional[int] = None
