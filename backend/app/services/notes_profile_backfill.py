"""Jednorazowe domknięcie historii: fakty z notatek do pustych pól (07.10.2026).

Nocna ekstrakcja (``notes_insights_sync``) wypełnia puste pola profilu tylko
przy NOWYM odczycie notatek. Kandydaci odczytani wcześniej mają fakty
w ``cv_extracted_data._notes_insights``, ale pola zostały puste — do 07.10.2026
data dostępności powstawała wyłącznie z pełnej daty ISO, a języków z notatek
nikt nie zapisywał (pomiar: 6 327 osób z dostępnością w notatkach i pustą
datą, 2 648 z językami w notatkach i bez języków w profilu).

Ten moduł stosuje do zapisanych faktów TĘ SAMĄ regułę co nocna ścieżka
(``notes_profile_fill.plan_profile_fill`` i ``fill_languages_from_notes``),
bez wywołania modelu:

* próba liczy plan i nic nie zapisuje (liczby + ≤ 20 przykładów z samymi ID),
* zapis wymaga ``expected`` równego liczbie kandydatów z próby, idzie pod
  blokadą doradczą, przelicza plan pod blokadą wierszy i DOPISUJE paragon
  (liczby, ID) oraz szczegóły (wartości sprzed zmiany — jedyna droga
  odwrócenia) pod kluczem innego kształtu.

Status „szuka aktywnie” z „od zaraz” zostaje przy nocnej ścieżce — tu nie
podnosimy statusu z historycznych notatek.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.services import note_kinds
from app.services.notes_profile_fill import (
    AVAILABILITY_MARKER,
    apply_profile_fill,
    fill_languages_from_notes,
    languages_to_add,
    plan_profile_fill,
)

RECEIPT_KEY = "notes_profile_fill_backfill_2026_10"
# Wartości sprzed zmiany (daty, tryby pracy) leżą pod kluczem innego kształtu —
# publiczny odczyt paragonów migracji go nie drukuje.
DETAILS_KEY = "repair_details_notes_profile_fill_backfill_2026_10"

BATCH = 500
SAMPLE = 20
_FIELD_COUNTS = {
    "years_it_experience": "years",
    "notice_period": "notice_period",
    "availability_date": "availability_date",
    "remote_modes": "remote_modes",
    "max_onsite_days_per_week": "onsite_days",
}


@dataclass(frozen=True)
class PlannedFill:
    candidate_id: int
    fields: tuple[str, ...]
    languages: tuple[str, ...] = field(default_factory=tuple)


_ROWS_SQL = text(
    "SELECT id, years_it_experience, notice_period, notice_period_unit, "
    "availability_date, preferences, max_onsite_days_per_week, "
    "cv_extracted_data->'_notes_insights' AS insights "
    "FROM candidates "
    "WHERE jsonb_typeof(cv_extracted_data) = 'object' "
    "AND jsonb_typeof(cv_extracted_data->'_notes_insights') = 'object' "
    "AND id > :after ORDER BY id LIMIT :limit"
)

_AS_OF_SQL = text(
    "SELECT candidate_id, "
    "max((COALESCE(source_created_at, created_at) AT TIME ZONE 'Europe/Warsaw')"
    "::date) AS note_day "
    "FROM notes WHERE candidate_id = ANY(:ids) "
    f"AND {note_kinds.facts_readable_sql()} GROUP BY candidate_id"
)

_LANGUAGE_CODES_SQL = text(
    "SELECT candidate_id, language_code FROM candidate_languages "
    "WHERE candidate_id = ANY(:ids)"
)


def _insights(value: Any) -> dict:
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}


async def _as_of(db: AsyncSession, ids: list[int]) -> dict[int, date]:
    rows = await db.execute(_AS_OF_SQL, {"ids": ids})
    return {row.candidate_id: row.note_day for row in rows}


async def _language_codes(db: AsyncSession, ids: list[int]) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {}
    for row in await db.execute(_LANGUAGE_CODES_SQL, {"ids": ids}):
        out.setdefault(row.candidate_id, set()).add(row.language_code)
    return out


def _plan_one(
    view: Any, insights: dict, *, as_of: Optional[date], codes: set[str]
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    changes, markers = plan_profile_fill(
        view, insights, prior=insights, as_of=as_of, include_status=False
    )
    return changes, markers, languages_to_add(insights, codes)


async def build_plan(db: AsyncSession) -> tuple[list[PlannedFill], dict[str, int]]:
    """(kandydaci do uzupełnienia, liczniki). Czysty odczyt, paczkami po id."""
    counts: Counter[str] = Counter()
    plan: list[PlannedFill] = []
    after = 0
    while True:
        rows = (await db.execute(_ROWS_SQL, {"after": after, "limit": BATCH})).all()
        if not rows:
            break
        after = rows[-1].id
        ids = [row.id for row in rows]
        as_of = await _as_of(db, ids)
        codes = await _language_codes(db, ids)
        for row in rows:
            counts["candidates_with_facts"] += 1
            insights = _insights(row.insights)
            view = SimpleNamespace(
                years_it_experience=row.years_it_experience,
                notice_period=row.notice_period,
                notice_period_unit=row.notice_period_unit,
                availability_date=row.availability_date,
                preferences=row.preferences,
                max_onsite_days_per_week=row.max_onsite_days_per_week,
            )
            changes, markers, langs = _plan_one(
                view, insights, as_of=as_of.get(row.id), codes=codes.get(row.id, set())
            )
            if not changes and not langs:
                continue
            for name in changes:
                counts[_FIELD_COUNTS[name]] += 1
            if "availability_date" in changes:
                basis = markers[AVAILABILITY_MARKER]["basis"]
                counts[f"availability_date_{basis}"] += 1
            if langs:
                counts["languages_candidates"] += 1
                counts["languages_codes"] += len(langs)
            plan.append(PlannedFill(row.id, tuple(sorted(changes)), tuple(langs)))
    counts["to_fill"] = len(plan)
    return plan, dict(counts)


def sample(plan: list[PlannedFill]) -> list[dict[str, Any]]:
    """≤ 20 przykładów z samymi ID i nazwami pól — bez wartości i nazwisk."""
    return [
        {
            "candidate_id": item.candidate_id,
            "fields": list(item.fields),
            "languages": list(item.languages),
        }
        for item in plan[:SAMPLE]
    ]


_LOCK_SQL = text("SELECT pg_advisory_xact_lock(hashtext(:key))")
_READ_SQL = text("SELECT value FROM app_settings WHERE key = :key")
_WRITE_SQL = text(
    """
    INSERT INTO app_settings (key, value, updated_at)
    VALUES (:key, CAST(:value AS jsonb), now())
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
    """
)


async def lock_for_apply(db: AsyncSession) -> None:
    """Jeden zapis naraz — plan liczymy dopiero pod tą blokadą."""
    await db.execute(_LOCK_SQL, {"key": RECEIPT_KEY})


async def _stored(db: AsyncSession, key: str) -> dict[str, Any]:
    value = await db.scalar(_READ_SQL, {"key": key})
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}


def _before(candidate: Any, fields: dict[str, Any]) -> dict[str, Any]:
    prefs = candidate.preferences if isinstance(candidate.preferences, dict) else {}
    out: dict[str, Any] = {}
    if "years_it_experience" in fields:
        out["years_it_experience"] = candidate.years_it_experience
    if "notice_period" in fields:
        out["notice_period"] = [candidate.notice_period, candidate.notice_period_unit]
    if "availability_date" in fields:
        current = candidate.availability_date
        out["availability_date"] = current.isoformat() if current else None
    if "remote_modes" in fields:
        out["remote_modes"] = prefs.get("remote_modes")
    if "max_onsite_days_per_week" in fields:
        out["max_onsite_days_per_week"] = candidate.max_onsite_days_per_week
    return out


async def apply_plan(
    db: AsyncSession, plan: list[PlannedFill], counts: dict[str, int], *, user_id: int
) -> dict[str, Any]:
    """Zapisz plan. Kandydat, któremu ktoś w międzyczasie wpisał pole, zostaje.

    Plan liczony od nowa pod blokadą wierszy kandydatów — zapisujemy tylko to,
    co nadal jest puste (ta sama reguła co nocna ścieżka).
    """
    from app.models.candidate import Candidate
    from app.services.match_score_cache import mark_stale_for_candidates

    filled_ids: list[int] = []
    details_rows: list[dict[str, Any]] = []
    field_counts: Counter[str] = Counter()
    now = datetime.now(timezone.utc).isoformat()
    for start in range(0, len(plan), 200):
        ids = [item.candidate_id for item in plan[start : start + 200]]
        as_of = await _as_of(db, ids)
        codes = await _language_codes(db, ids)
        candidates = (
            await db.scalars(
                select(Candidate)
                .where(Candidate.id.in_(ids))
                .order_by(Candidate.id)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
        ).all()
        for candidate in candidates:
            extracted = (
                dict(candidate.cv_extracted_data)
                if isinstance(candidate.cv_extracted_data, dict)
                else {}
            )
            insights = extracted.get("_notes_insights")
            if not isinstance(insights, dict):
                continue
            changes, markers, langs = _plan_one(
                candidate,
                insights,
                as_of=as_of.get(candidate.id),
                codes=codes.get(candidate.id, set()),
            )
            if not changes and not langs:
                continue
            before = _before(candidate, changes)
            apply_profile_fill(candidate, changes)
            if markers:
                extracted["_notes_insights"] = {**insights, **markers}
                candidate.cv_extracted_data = extracted
                flag_modified(candidate, "cv_extracted_data")
            added = (
                await fill_languages_from_notes(db, candidate.id, insights)
                if langs
                else 0
            )
            if not changes and not added:
                continue
            for name in changes:
                field_counts[_FIELD_COUNTS[name]] += 1
            if added:
                field_counts["languages_candidates"] += 1
                field_counts["languages_codes"] += added
            filled_ids.append(candidate.id)
            details_rows.append(
                {
                    "candidate_id": candidate.id,
                    "before": before,
                    "languages_added": list(langs) if added else [],
                    "applied_at": now,
                }
            )
        await db.flush()
    if filled_ids:
        await mark_stale_for_candidates(db, filled_ids)
    run = {
        "applied_at": now,
        "applied_by": user_id,
        "counts": {**counts, "filled": len(filled_ids), **dict(field_counts)},
        "candidate_ids": filled_ids,
    }
    if not filled_ids:
        return run
    receipt = await _stored(db, RECEIPT_KEY)
    details = await _stored(db, DETAILS_KEY)
    receipt["runs"] = [*receipt.get("runs", []), run]
    details["rows"] = [*details.get("rows", []), *details_rows]
    await db.execute(_WRITE_SQL, {"key": RECEIPT_KEY, "value": json.dumps(receipt)})
    await db.execute(_WRITE_SQL, {"key": DETAILS_KEY, "value": json.dumps(details)})
    return run
