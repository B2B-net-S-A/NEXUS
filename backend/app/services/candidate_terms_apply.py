"""Zapis odpowiedzi z formularza warunków do profilu kandydata.

Decyzja Artura 16.11.2026: odpowiedź kandydata nadpisuje wartość w profilu,
stara zostaje w historii (dziennik ``activities``). Wyjątek z analizy 17.11:
pole, które rekruter sam zmienił w ostatnich 14 dniach, zostaje — odpowiedź
kandydata leży wtedy obok (``answers`` prośby i ``details.kept`` w dzienniku).

Każdy zapis idzie istniejącą drogą profilu, żeby „Stawka od”, dopasowania
i bramki widziały go tak samo jak wpis rekrutera:
stawka → ``update_candidate_profile_rate(meaning="minimum")``,
tryb i dni → ``set_profile_work_mode``, miasta → ``preferences.office_cities``,
start → ``availability_date`` albo ``notice_period``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.scheduling import business_date
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.services import candidate_audit
from app.services import candidate_terms as rules

#: Pole zmienione przez człowieka w tym oknie nie jest nadpisywane.
HUMAN_EDIT_WINDOW_DAYS = 14

_FIELD_ACTIONS = {
    "rate": (candidate_audit.PROFILE_RATE_CHANGED,),
    "work_mode": (candidate_audit.WORK_MODE_CHANGED,),
}


@dataclass(frozen=True)
class TermsAnswer:
    rate_amount: Optional[Decimal] = None
    rate_unit: str = "hour"
    rate_currency: str = "PLN"
    modes: tuple[str, ...] = ()
    onsite_days: Optional[int] = None
    cities: tuple[str, ...] = ()
    start_kind: Optional[str] = None  # now | date | notice
    start_date: Optional[date] = None
    notice_value: Optional[int] = None
    notice_unit: Optional[str] = None  # weeks | months
    future_consent: Optional[bool] = None

    def as_json(self) -> dict:
        return {
            "rate": None
            if self.rate_amount is None
            else {
                "amount": str(self.rate_amount),
                "unit": self.rate_unit,
                "currency": self.rate_currency,
            },
            "modes": list(self.modes),
            "onsite_days": self.onsite_days,
            "cities": list(self.cities),
            "start": None
            if self.start_kind is None
            else {
                "kind": self.start_kind,
                "date": self.start_date.isoformat() if self.start_date else None,
                "value": self.notice_value,
                "unit": self.notice_unit,
            },
            "future_consent": self.future_consent,
        }


async def _recent_human_edits(
    db: AsyncSession, candidate_id: int, now: datetime
) -> set[str]:
    actions = {a for acts in _FIELD_ACTIONS.values() for a in acts}
    rows = await db.execute(
        select(Activity.action).where(
            Activity.entity_type == "candidate",
            Activity.entity_id == candidate_id,
            Activity.action.in_(actions),
            Activity.user_id.is_not(None),
            Activity.created_at > now - timedelta(days=HUMAN_EDIT_WINDOW_DAYS),
        )
    )
    seen = {r[0] for r in rows}
    return {field for field, acts in _FIELD_ACTIONS.items() if seen & set(acts)}


async def apply_answer(
    db: AsyncSession,
    candidate: Candidate,
    answer: TermsAnswer,
    *,
    now: datetime,
    request_id: int,
) -> dict:
    """Zapisz odpowiedź. Zwraca ``{"saved": [...], "kept": [...]}``. Bez commitu."""
    saved: list[str] = []
    kept: list[str] = []
    protected = await _recent_human_edits(db, candidate.id, now)

    if answer.rate_amount is not None:
        hourly = rules.hourly_rate(answer.rate_amount, answer.rate_unit)
        if answer.rate_currency != "PLN":
            # Profil trzyma wyłącznie PLN netto/h; inna waluta zostaje w odpowiedzi.
            kept.append("rate_currency")
        elif "rate" in protected:
            kept.append("rate")
        else:
            from app.services.candidate_profile_facts import (
                update_candidate_profile_rate,
            )

            await update_candidate_profile_rate(
                db,
                candidate_id=candidate.id,
                amount=hourly,
                expected_version=candidate.profile_rate_version,
                actor_id=None,
                meaning="minimum",
                source="candidate_terms",
            )
            saved.append("rate")

    if answer.modes:
        if "work_mode" in protected:
            kept.append("work_mode")
        else:
            from app.services.candidate_notes_facts import set_profile_work_mode

            days = answer.onsite_days if "hybrid" in answer.modes else None
            if answer.modes == ("remote",):
                days = 0
            change = set_profile_work_mode(
                candidate, modes=list(answer.modes), max_onsite_days=days
            )
            candidate_audit.record_candidate_audit(
                db,
                action=candidate_audit.WORK_MODE_CHANGED,
                user_id=None,
                entity_id=candidate.id,
                details={**change, "source": "candidate_terms"},
            )
            saved.append("work_mode")

    if answer.cities:
        prefs = (
            dict(candidate.preferences)
            if isinstance(candidate.preferences, dict)
            else {}
        )
        prefs["office_cities"] = list(answer.cities)
        candidate.preferences = prefs
        flag_modified(candidate, "preferences")
        saved.append("cities")

    if answer.start_kind == "now":
        # „Od zaraz” to dziś w kalendarzu firmy — `now` jest w UTC, a o 00:30
        # w Warszawie `now.date()` to jeszcze wczoraj.
        candidate.availability_date = business_date(now)
        candidate.notice_period, candidate.notice_period_unit = 0, "days"
        saved.append("start")
    elif answer.start_kind == "date" and answer.start_date is not None:
        # Odpowiedź o starcie zastępuje oba pola — stary okres wypowiedzenia
        # obok nowej daty mówiłby co innego.
        candidate.availability_date = answer.start_date
        candidate.notice_period, candidate.notice_period_unit = None, None
        saved.append("start")
    elif answer.start_kind == "notice" and answer.notice_value is not None:
        candidate.notice_period = answer.notice_value
        candidate.notice_period_unit = answer.notice_unit or "months"
        candidate.availability_date = None
        saved.append("start")

    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.TERMS_ANSWERED,
        user_id=None,
        entity_id=candidate.id,
        details={
            "request_id": request_id,
            "saved": saved,
            "kept": kept,
            "answer": answer.as_json(),
        },
    )
    if saved:
        from app.services.match_score_cache import mark_stale_for_candidate

        await mark_stale_for_candidate(db, candidate.id)
    return {"saved": saved, "kept": kept}
