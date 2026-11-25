"""Strona tokenu z maila z raportem kompetencji: zmiana warunków i wypis.

Decyzje Artura 25.11.2026 (plan: b2bnetwork-www ``docs/raport-24h-wdrozenie.md``).
Bliźniak formularza warunków z maila (``public_candidate_terms``): link
``/raport/<token>`` i wypis jednym kliknięciem (RFC 8058) z nagłówka maila.

Bezpieczeństwo:
- w bazie tylko SHA-256 tokenu (``competence_report_tokens``), ważny 60 dni;
  otwarcie niczego nie zmienia, więc skaner linków w poczcie go nie zużyje;
- nieznany i wygasły token dostają tę samą odpowiedź 404 (bez wyroczni);
- odpowiedzi nie niosą danych profilu, imion ani adresu — tylko warunki,
  które kandydat sam podał, stan wypisu i dzień wysyłki raportu;
- ``@limiter.limit`` na każdej trasie.

Ten moduł NIE MOŻE dostać ``from __future__ import annotations`` — PEP 563 +
slowapi #579 zamieniają ciało żądania w parametry query (422).
"""

from datetime import date as Date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, model_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.scheduling import business_date
from app.models.candidate import Candidate
from app.models.competence_report import CompetenceReport
from app.services import candidate_audit
from app.services.competence_report_schema import ReportConditions
from app.services.competence_report_tokens import token_hash
from app.services.website_application_terms import WebsiteTerms, apply_terms

router = APIRouter()

_NOT_FOUND = "Ten link jest nieprawidłowy albo wygasł."
#: Raport jeszcze niewysłany — wypis przestawia go na ``opted_out``.
_UNSENT = ("waiting_cv", "ready", "failed")
#: Jak formularz strony (``website_applications``): do 10 miast, każde do 120 znaków.
_MAX_CITIES = 10
_CITY_MAX = 120
OPTED_OUT = "competence_report_opted_out"


class ConditionsSubmit(ReportConditions):
    """Warunki ze strony tokenu: kształt ``ReportConditions`` i reguły formularza strony."""

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        modes = out.get("modes")
        if isinstance(modes, (list, tuple)):
            order = ("remote", "hybrid", "onsite")
            out["modes"] = [m for m in order if m in modes] + [
                m for m in modes if m not in order
            ]
        cities = out.get("office_cities")
        if isinstance(cities, (list, tuple)):
            seen: set[str] = set()
            clean: list[Any] = []
            for city in cities:
                if not isinstance(city, str):
                    clean.append(city)  # typ odrzuci walidacja pola
                    continue
                city = " ".join(city.split())
                if city and city.casefold() not in seen:
                    seen.add(city.casefold())
                    clean.append(city)
            out["office_cities"] = clean
        return out

    @model_validator(mode="after")
    def _rules(self):  # type: ignore[no-untyped-def]
        if not self.modes:
            raise ValueError("modes_missing")
        if self.start is None:
            raise ValueError("start_missing")
        if len(self.office_cities) > _MAX_CITIES:
            raise ValueError("too_many_cities")
        if any(len(c) > _CITY_MAX for c in self.office_cities):
            raise ValueError("city_too_long")
        if self.modes != ("remote",):
            if self.office_days_max is None:
                raise ValueError("office_days_missing")
            if not self.office_cities:
                raise ValueError("cities_missing")
        return self

    def stored(self) -> ReportConditions:
        """Do raportu: przy pracy tylko zdalnej bez dni w biurze i miast (jak strona)."""
        fields = self.model_dump()
        if self.modes == ("remote",):
            fields.update(office_days_max=None, office_cities=())
        return ReportConditions(**fields)


class ReportPageView(BaseModel):
    conditions: ReportConditions
    opted_out: bool
    sent_at: Optional[Date]


class OptOutView(BaseModel):
    opted_out: bool


async def _resolve(
    token: str, db: AsyncSession, *, allow_expired: bool = False
) -> CompetenceReport:
    if not 16 <= len(token) <= 128:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    row = await db.scalar(
        select(CompetenceReport).where(CompetenceReport.token_hash == token_hash(token))
    )
    if row is None or row.token_expires_at is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if not allow_expired and row.token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return row


def _view(row: CompetenceReport) -> ReportPageView:
    return ReportPageView(
        conditions=ReportConditions.model_validate(row.conditions),
        opted_out=row.opted_out_at is not None,
        sent_at=business_date(row.sent_at) if row.sent_at else None,
    )


@router.get("/public/competence-report/{token}", response_model=ReportPageView)
@limiter.limit("30/minute")
async def get_report_page(
    token: str,
    request: Request,  # wymagane przez slowapi
    db: AsyncSession = Depends(get_db),
):
    return _view(await _resolve(token, db))


@router.post(
    "/public/competence-report/{token}/conditions", response_model=ReportPageView
)
@limiter.limit("10/minute; 40/hour")
async def save_report_conditions(
    token: str,
    request: Request,  # wymagane przez slowapi
    data: ConditionsSubmit,
    db: AsyncSession = Depends(get_db),
):
    row = await _resolve(token, db)
    candidate = await db.get(Candidate, row.candidate_id, with_for_update=True)
    if candidate is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    now = datetime.now(timezone.utc)
    conditions = data.stored()
    # Te same writery i ta sama ochrona 14 dni co przyjęcie zgłoszenia ze strony.
    result = await apply_terms(
        db,
        candidate,
        WebsiteTerms(
            rate_hourly=Decimal(conditions.rate),
            contract=conditions.contract,
            modes=conditions.modes,
            office_days_max=conditions.office_days_max,
            cities=conditions.office_cities,
            start=conditions.start,
        ),
        now=now,
        protect=True,
    )
    row.conditions = conditions.model_dump(mode="json")
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.TERMS_ANSWERED,
        user_id=None,
        entity_id=candidate.id,
        details={
            "via": "competence_report",
            "report_id": row.id,
            "saved": result["saved"],
            "kept": result["kept"],
            "answer": row.conditions,
        },
    )
    await db.commit()
    return _view(row)


@router.post("/public/competence-report/{token}/opt-out", response_model=OptOutView)
@limiter.limit("10/minute")
async def opt_out_competence_report(
    token: str,
    request: Request,  # wymagane przez slowapi
    db: AsyncSession = Depends(get_db),
):
    """Wypis z raportów — także z nagłówka maila (One-Click) i po terminie linku."""
    row = await _resolve(token, db, allow_expired=True)
    now = datetime.now(timezone.utc)
    marked = await db.execute(
        update(CompetenceReport)
        .where(
            CompetenceReport.candidate_id == row.candidate_id,
            CompetenceReport.opted_out_at.is_(None),
        )
        .values(opted_out_at=now)
    )
    stopped = await db.execute(
        update(CompetenceReport)
        .where(
            CompetenceReport.candidate_id == row.candidate_id,
            CompetenceReport.sent_at.is_(None),
            CompetenceReport.status.in_(_UNSENT),
        )
        .values(status="opted_out")
    )
    if marked.rowcount or stopped.rowcount:
        candidate_audit.record_candidate_audit(
            db,
            action=OPTED_OUT,
            user_id=None,
            entity_id=row.candidate_id,
            details={"report_id": row.id, "stopped": stopped.rowcount},
        )
    await db.commit()
    return OptOutView(opted_out=True)
