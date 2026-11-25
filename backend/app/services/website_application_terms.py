"""Warunki z formularza strony → profil kandydata (decyzje Artura 25.11.2026).

Te same drogi zapisu co formularz warunków z maila
(``services/candidate_terms_apply.py``), żeby „Stawka od”, dopasowania
i bramki widziały wpis strony tak samo jak wpis rekrutera:
stawka → ``update_candidate_profile_rate``, tryb i dni →
``set_profile_work_mode``, miasta → ``preferences.office_cities``,
forma współpracy → ``b2b_willingness`` + ``preferences.contract_types``,
start → ``availability_date`` / ``notice_period`` / ``availability_status``.

Osoba już w bazie (``protect=True``): pole, które człowiek zmienił w ostatnich
14 dniach, zostaje — wartość strony leży wtedy w zgłoszeniu i w raporcie.
Poza dziennikiem ``apply_answer`` (stawka, tryb pracy) liczy się też zwykła
edycja profilu (``activities.action = 'updated'``), bo nią rekruter zmienia
miasta, formę współpracy i dostępność.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.scheduling import business_date
from app.models.activity import Activity
from app.models.candidate import AvailabilityStatus, Candidate
from app.services import candidate_audit
from app.services.candidate_terms_apply import (
    HUMAN_EDIT_WINDOW_DAYS,
    _recent_human_edits,
)

SOURCE = "website"

#: Forma współpracy ze strony → ``b2b_willingness`` (``any`` nie zmienia pola).
_WILLINGNESS = {"b2b": "b2b", "uop": "employment_only"}
_CONTRACT_TYPES = {"b2b": ["b2b"], "uop": ["uop"], "any": ["b2b", "uop"]}
#: Start ze strony jako okres wypowiedzenia w miesiącach (dolna granica).
_NOTICE_MONTHS = {"1m": 1, "2-3m": 2}

#: Klucze zwykłej edycji profilu (``details`` wpisu ``updated``) → pole warunków.
_UPDATED_KEYS = {
    "max_onsite_days_per_week": "work_mode",
    "b2b_willingness": "contract",
    "availability_date": "start",
    "notice_period": "start",
    "notice_period_unit": "start",
    "availability_status": "start",
}
_PREFERENCE_KEYS = {
    "remote_modes": "work_mode",
    "office_cities": "cities",
    "contract_types": "contract",
}


@dataclass(frozen=True)
class WebsiteTerms:
    rate_hourly: Optional[Decimal] = None
    contract: Optional[str] = None  # b2b | uop | any
    modes: tuple[str, ...] = ()
    office_days_max: Optional[int] = None
    cities: tuple[str, ...] = ()
    start: Optional[str] = None  # now | 1m | 2-3m | browsing


async def _recent_profile_edits(
    db: AsyncSession, candidate_id: int, now: datetime
) -> set[str]:
    rows = await db.scalars(
        select(Activity.details).where(
            Activity.entity_type == "candidate",
            Activity.entity_id == candidate_id,
            Activity.action == "updated",
            Activity.user_id.is_not(None),
            Activity.created_at > now - timedelta(days=HUMAN_EDIT_WINDOW_DAYS),
        )
    )
    fields: set[str] = set()
    for details in rows:
        if not isinstance(details, dict):
            continue
        fields |= {_UPDATED_KEYS[k] for k in details if k in _UPDATED_KEYS}
        prefs = details.get("preferences")
        if isinstance(prefs, dict):
            fields |= {_PREFERENCE_KEYS[k] for k in prefs if k in _PREFERENCE_KEYS}
    return fields


def _office_days(terms: WebsiteTerms) -> Optional[int]:
    """Dni w biurze jak w ``apply_answer``: samo zdalnie = 0."""
    if terms.modes == ("remote",):
        return 0
    if {"hybrid", "onsite"} & set(terms.modes):
        return terms.office_days_max
    return None


def _modes(terms: WebsiteTerms) -> list[str]:
    if terms.modes:
        return list(terms.modes)
    if terms.office_days_max is not None:
        from app.services.candidate_notes_facts import modes_for_office_days

        return modes_for_office_days(terms.office_days_max)
    return []


async def apply_terms(
    db: AsyncSession,
    candidate: Candidate,
    terms: WebsiteTerms,
    *,
    now: datetime,
    protect: bool,
    write_rate: bool = True,
) -> dict:
    """Zapisz warunki. Zwraca ``{"saved": [...], "kept": [...]}``. Bez commitu.

    ``write_rate=False``: nowy kandydat ma stawkę już w konstruktorze
    (kontrakt writera etapów, patrz ``public_apply._create_candidate``).
    """
    saved: list[str] = []
    kept: list[str] = []
    protected: set[str] = set()
    if protect:
        protected = await _recent_human_edits(
            db, candidate.id, now
        ) | await _recent_profile_edits(db, candidate.id, now)

    def _guard(field: str) -> bool:
        if field in protected:
            kept.append(field)
            return False
        saved.append(field)
        return True

    if write_rate and terms.rate_hourly is not None and _guard("rate"):
        from app.services.candidate_profile_facts import update_candidate_profile_rate

        await update_candidate_profile_rate(
            db,
            candidate_id=candidate.id,
            amount=terms.rate_hourly,
            expected_version=candidate.profile_rate_version,
            actor_id=None,
            meaning="expectation",
            source=SOURCE,
        )

    modes = _modes(terms)
    if modes and _guard("work_mode"):
        from app.services.candidate_notes_facts import set_profile_work_mode

        change = set_profile_work_mode(
            candidate, modes=modes, max_onsite_days=_office_days(terms)
        )
        candidate_audit.record_candidate_audit(
            db,
            action=candidate_audit.WORK_MODE_CHANGED,
            user_id=None,
            entity_id=candidate.id,
            details={**change, "source": SOURCE},
        )

    if terms.cities and _guard("cities"):
        _set_preference(candidate, "office_cities", list(terms.cities))

    if terms.contract in _CONTRACT_TYPES and _guard("contract"):
        if terms.contract in _WILLINGNESS:
            candidate.b2b_willingness = _WILLINGNESS[terms.contract]
        _set_preference(
            candidate, "contract_types", list(_CONTRACT_TYPES[terms.contract])
        )

    if terms.start is not None and _guard("start"):
        _apply_start(candidate, terms.start, now)

    if saved:
        from app.services.match_score_cache import mark_stale_for_candidate

        await mark_stale_for_candidate(db, candidate.id)
    return {"saved": saved, "kept": kept}


def _set_preference(candidate: Candidate, key: str, value: list[str]) -> None:
    prefs = (
        dict(candidate.preferences) if isinstance(candidate.preferences, dict) else {}
    )
    prefs[key] = value
    candidate.preferences = prefs
    flag_modified(candidate, "preferences")


def _apply_start(candidate: Candidate, start: str, now: datetime) -> None:
    if start == "now":
        # „Od zaraz” to dziś w kalendarzu firmy (jak ``apply_answer``).
        candidate.availability_date = business_date(now)
        candidate.notice_period, candidate.notice_period_unit = 0, "days"
    elif start in _NOTICE_MONTHS:
        candidate.notice_period = _NOTICE_MONTHS[start]
        candidate.notice_period_unit = "months"
        candidate.availability_date = None
    elif start == "browsing":
        # „Rozglądam się”: bez daty, tylko postawa — nie nadpisuje deklaracji
        # z rozmowy (aktywnie szuka / nie szuka).
        if candidate.availability_status in (None, AvailabilityStatus.unknown):
            candidate.availability_status = AvailabilityStatus.open_to_offers
