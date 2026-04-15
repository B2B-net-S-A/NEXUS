from datetime import date, datetime
from typing import Any, List, Optional

from pydantic import BaseModel, EmailStr

from app.models.candidate import CandidateStatus, CandidateSource


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
    ai_summary: Optional[str] = None
    tags: Optional[List[Any]] = None
    skills: Optional[List[Any]] = None
    experience: Optional[List[Any]] = None
    education: Optional[List[Any]] = None
    languages: Optional[List[Any]] = None


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
    ai_summary: Optional[str] = None
    tags: Optional[List[Any]] = None
    skills: Optional[List[Any]] = None
    experience: Optional[List[Any]] = None
    education: Optional[List[Any]] = None
    languages: Optional[List[Any]] = None


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
    ai_summary: Optional[str] = None
    status: CandidateStatus
    tags: Optional[Any]
    skills: Optional[Any]
    experience: Optional[Any]
    education: Optional[Any]
    languages: Optional[Any]
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
