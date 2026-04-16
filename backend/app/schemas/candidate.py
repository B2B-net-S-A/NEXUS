from datetime import date, datetime
from typing import Any, List, Optional

from pydantic import BaseModel, EmailStr, field_validator

from app.models.candidate import CandidateStatus


_VALID_SKILL_LEVELS = {"expert", "senior", "mid", "junior", None}


def _normalize_skill_list(value: Any) -> Optional[List[dict]]:
    """
    Normalize a skills list into structured form:
      [{"name": str, "level": str|None, "years": int|None, "category": str|None}, ...]

    Accepts:
      - None → None
      - list of strings → wrapped as {name:str, level:None}
      - list of dicts → validated/passed through
    """
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("skills must be a list")

    normalized: List[dict] = []
    for item in value:
        if isinstance(item, str):
            normalized.append({"name": item.strip(), "level": None})
        elif isinstance(item, dict):
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(
                    f"skill item requires non-empty 'name' string, got {item!r}"
                )
            level = item.get("level")
            if level is not None and level not in _VALID_SKILL_LEVELS:
                raise ValueError(
                    f"skill level must be one of {sorted(v for v in _VALID_SKILL_LEVELS if v)}, got {level!r}"
                )
            entry = {"name": name.strip(), "level": level}
            if "years" in item and item["years"] is not None:
                entry["years"] = int(item["years"])
            if "category" in item and item["category"] is not None:
                entry["category"] = str(item["category"]).strip()
            normalized.append(entry)
        else:
            raise ValueError(
                f"skill item must be str or dict, got {type(item).__name__}"
            )
    return normalized


class CandidateCreate(BaseModel):
    name: str
    lastname: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin: Optional[str] = None
    salary_expectation: Optional[int] = None
    salary_currency: Optional[str] = "PLN"
    availability_date: Optional[date] = None
    notice_period: Optional[int] = None
    source: Optional[str] = None
    status: CandidateStatus = CandidateStatus.active
    avatar_url: Optional[str] = None
    competence_category: Optional[str] = None
    years_it_experience: Optional[int] = None
    ai_summary: Optional[str] = None
    tags: Optional[List[Any]] = None
    skills: Optional[List[Any]] = None
    experience: Optional[List[Any]] = None
    education: Optional[List[Any]] = None
    languages: Optional[List[Any]] = None
    preferences: Optional[dict] = None
    champion: bool = False
    verifier_id: Optional[int] = None
    verified_tech: Optional[List[Any]] = None

    @field_validator("skills", "verified_tech", mode="before")
    @classmethod
    def _normalize_skills(cls, v: Any) -> Any:
        return _normalize_skill_list(v)


class CandidateUpdate(BaseModel):
    name: Optional[str] = None
    lastname: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin: Optional[str] = None
    salary_expectation: Optional[int] = None
    salary_currency: Optional[str] = None
    availability_date: Optional[date] = None
    notice_period: Optional[int] = None
    source: Optional[str] = None
    status: Optional[CandidateStatus] = None
    avatar_url: Optional[str] = None
    competence_category: Optional[str] = None
    years_it_experience: Optional[int] = None
    ai_summary: Optional[str] = None
    tags: Optional[List[Any]] = None
    skills: Optional[List[Any]] = None
    experience: Optional[List[Any]] = None
    education: Optional[List[Any]] = None
    languages: Optional[List[Any]] = None
    preferences: Optional[dict] = None
    champion: Optional[bool] = None
    verifier_id: Optional[int] = None
    verified_tech: Optional[List[Any]] = None

    @field_validator("skills", "verified_tech", mode="before")
    @classmethod
    def _normalize_skills(cls, v: Any) -> Any:
        return _normalize_skill_list(v)


class CandidateResponse(BaseModel):
    id: int
    name: str
    lastname: str
    email: Optional[str]
    phone: Optional[str]
    location: Optional[str]
    linkedin: Optional[str]
    avatar_url: Optional[str] = None
    salary_expectation: Optional[int]
    salary_currency: Optional[str] = "PLN"
    availability_date: Optional[date]
    notice_period: Optional[int] = None
    source: Optional[str]
    competence_category: Optional[str] = None
    years_it_experience: Optional[int] = None
    ai_summary: Optional[str] = None
    status: CandidateStatus
    tags: Optional[Any]
    skills: Optional[Any]
    experience: Optional[Any]
    education: Optional[Any]
    languages: Optional[Any]
    preferences: Optional[Any] = None
    champion: bool = False
    verifier_id: Optional[int] = None
    verified_tech: Optional[Any] = None
    cv_filename: Optional[str]
    cv_parsed_at: Optional[datetime]
    notes_count: int
    last_contacted_at: Optional[datetime]
    embedding_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CandidateList(BaseModel):
    items: list[CandidateResponse]
    total: int
    page: int
    page_size: int
