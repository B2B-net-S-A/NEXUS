"""Publiczny formularz warunków kandydata (link z maila, bez logowania).

Decyzje Artura 16–17.11.2026. Reguła:
``docs/claude/kandydaci-wyszukiwanie/warunki-od-kandydata-formularz-po-aplikacji.md``.

Bezpieczeństwo:
- token z maila, w bazie tylko jego SHA-256; ważny 14 dni, wiele zapisów
  (kandydat może poprawić odpowiedź), otwarcie niczego nie zmienia, więc
  skanery linków w poczcie go nie zużyją;
- odpowiedź GET nie zawiera danych z profilu (rekruter mógł tam wpisać
  stawkę z rozmowy) — tylko tytuł ogłoszenia i ostatnią odpowiedź kandydata;
- ``@limiter.limit`` na każdej trasie.

Ten moduł NIE MOŻE dostać ``from __future__ import annotations`` — PEP 563 +
slowapi #579 zamieniają ciało żądania w parametry query (422).
"""

from datetime import date as Date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.scheduling import DEFAULT_TZ
from app.models.candidate import Candidate
from app.models.candidate_terms_request import CandidateTermsRequest
from app.services import candidate_terms as rules
from app.services.candidate_terms_apply import TermsAnswer, apply_answer

router = APIRouter()

_NOT_FOUND = "Ten link jest nieprawidłowy. Sprawdź, czy skopiowałeś go w całości."
_EXPIRED = "Ten link wygasł. Gdy znowu u nas zaaplikujesz, wyślemy nowy."


class TermsRate(BaseModel):
    amount: Decimal = Field(gt=0, le=Decimal("100000"))
    unit: Literal["hour", "month"] = "hour"
    currency: Literal["PLN", "EUR"] = "PLN"

    @model_validator(mode="after")
    def _range(self):  # type: ignore[no-untyped-def]
        hourly = rules.hourly_rate(self.amount, self.unit)
        if not (rules.RATE_MIN_HOURLY <= hourly <= rules.RATE_MAX_HOURLY):
            raise ValueError("rate_out_of_range")
        return self


class TermsStart(BaseModel):
    kind: Literal["now", "date", "notice"]
    date: Optional[Date] = None
    value: Optional[int] = Field(default=None, ge=0, le=26)
    unit: Optional[Literal["weeks", "months"]] = None

    @model_validator(mode="after")
    def _complete(self):  # type: ignore[no-untyped-def]
        if self.kind == "date" and self.date is None:
            raise ValueError("start_date_missing")
        if self.kind == "notice" and (self.value is None or self.unit is None):
            raise ValueError("notice_missing")
        if self.kind == "notice" and self.unit == "months" and (self.value or 0) > 6:
            raise ValueError("notice_too_long")
        return self


class TermsSubmit(BaseModel):
    rate: Optional[TermsRate] = None
    modes: list[Literal["remote", "hybrid", "onsite"]] = Field(
        default_factory=list, max_length=3
    )
    onsite_days: Optional[int] = Field(default=None, ge=1, le=5)
    cities: list[str] = Field(default_factory=list, max_length=5)
    start: Optional[TermsStart] = None
    future_consent: Optional[bool] = None

    @field_validator("cities")
    @classmethod
    def _cities(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for city in value:
            city = " ".join(str(city).split())
            if not 2 <= len(city) <= 60:
                raise ValueError("city_invalid")
            if city.casefold() not in {c.casefold() for c in out}:
                out.append(city)
        return out

    @model_validator(mode="after")
    def _not_empty(self):  # type: ignore[no-untyped-def]
        if not (self.rate or self.modes or self.cities or self.start) and (
            self.future_consent is None
        ):
            raise ValueError("empty_answer")
        return self


class TermsView(BaseModel):
    job_title: Optional[str]
    expires_at: datetime
    answered_at: Optional[datetime]
    answers: Optional[dict]
    opted_out: bool


class TermsSaved(BaseModel):
    saved_at: datetime
    saved: list[str]
    kept: list[str]


async def _resolve(token: str, db: AsyncSession, *, allow_expired: bool = False):
    if not 16 <= len(token) <= 128:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    row = await db.scalar(
        select(CandidateTermsRequest).where(
            CandidateTermsRequest.token_sha256 == rules.token_hash(token)
        )
    )
    if row is None or row.expires_at is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if not allow_expired and row.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail=_EXPIRED)
    return row


async def _last_answers(db: AsyncSession, candidate_id: int) -> Optional[dict]:
    return await db.scalar(
        select(CandidateTermsRequest.answers)
        .where(
            CandidateTermsRequest.candidate_id == candidate_id,
            CandidateTermsRequest.answers.is_not(None),
        )
        .order_by(CandidateTermsRequest.answered_at.desc())
        .limit(1)
    )


@router.get("/public/candidate-terms/{token}", response_model=TermsView)
@limiter.limit("30/minute")
async def get_terms_form(
    token: str,
    request: Request,  # wymagane przez slowapi
    db: AsyncSession = Depends(get_db),
):
    row = await _resolve(token, db)
    from app.services.application_confirmation_email import public_job_title

    return TermsView(
        job_title=await public_job_title(db, row.job_id) or row.ad_title,
        expires_at=row.expires_at,
        answered_at=row.answered_at,
        answers=await _last_answers(db, row.candidate_id),
        opted_out=row.opted_out_at is not None,
    )


@router.post("/public/candidate-terms/{token}", response_model=TermsSaved)
@limiter.limit("10/minute; 40/hour")
async def submit_terms_form(
    token: str,
    request: Request,  # wymagane przez slowapi
    data: TermsSubmit,
    db: AsyncSession = Depends(get_db),
):
    row = await _resolve(token, db)
    candidate = await db.get(Candidate, row.candidate_id, with_for_update=True)
    if candidate is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    now = datetime.now(timezone.utc)
    if data.start and data.start.kind == "date":
        today = now.astimezone(ZoneInfo(DEFAULT_TZ)).date()
        if not today <= data.start.date <= today + timedelta(days=730):
            raise HTTPException(
                status_code=422, detail="Podaj datę od dziś do dwóch lat."
            )
    modes = tuple(m for m in ("remote", "hybrid", "onsite") if m in data.modes)
    answer = TermsAnswer(
        rate_amount=data.rate.amount if data.rate else None,
        rate_unit=data.rate.unit if data.rate else "hour",
        rate_currency=data.rate.currency if data.rate else "PLN",
        modes=modes,
        onsite_days=data.onsite_days if "hybrid" in modes else None,
        cities=tuple(data.cities) if modes and modes != ("remote",) else (),
        start_kind=data.start.kind if data.start else None,
        start_date=data.start.date if data.start else None,
        notice_value=data.start.value if data.start else None,
        notice_unit=data.start.unit if data.start else None,
        future_consent=data.future_consent,
    )
    result = await apply_answer(db, candidate, answer, now=now, request_id=row.id)
    row.answers = answer.as_json()
    row.answered_at = now
    row.answer_count = (row.answer_count or 0) + 1
    await db.commit()
    return TermsSaved(saved_at=now, saved=result["saved"], kept=result["kept"])


@router.post("/public/candidate-terms/{token}/opt-out", response_model=TermsView)
@limiter.limit("10/minute")
async def opt_out_terms(
    token: str,
    request: Request,  # wymagane przez slowapi
    db: AsyncSession = Depends(get_db),
):
    """„Nie chcę dostawać takich pytań” — działa także po terminie linku."""
    row = await _resolve(token, db, allow_expired=True)
    if row.opted_out_at is None:
        row.opted_out_at = datetime.now(timezone.utc)
        await db.commit()
    return TermsView(
        job_title=None,
        expires_at=row.expires_at,
        answered_at=row.answered_at,
        answers=None,
        opted_out=True,
    )
