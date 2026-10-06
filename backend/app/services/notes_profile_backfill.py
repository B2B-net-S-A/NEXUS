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
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.services.notes_insights_extractor import load_note_rows_bulk
from app.services.notes_profile_fill import (
    AVAILABILITY_MARKER,
    NotesDays,
    apply_profile_fill,
    fill_languages_from_notes,
    languages_to_add,
    notes_days,
    plan_profile_fill,
)

logger = logging.getLogger(__name__)

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

_LANGUAGE_CODES_SQL = text(
    "SELECT candidate_id, language_code FROM candidate_languages "
    "WHERE candidate_id = ANY(:ids)"
)


def _insights(value: Any) -> dict:
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}


async def _note_days(db: AsyncSession, ids: list[int]) -> dict[int, NotesDays]:
    """Dni notatek liczone na TYM SAMYM zbiorze, który czyta odczyt AI.

    ``load_note_rows_bulk`` to ten sam wybór co ``load_note_rows`` nocnej
    ekstrakcji, a ``notes_days`` ta sama funkcja — obie drogi wpisują tę samą
    datę dostępności i ten sam „stan na”.
    """
    rows = await load_note_rows_bulk(db, ids)
    return {cid: notes_days(rows.get(cid, [])) for cid in ids}


async def _language_codes(db: AsyncSession, ids: list[int]) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {}
    for row in await db.execute(_LANGUAGE_CODES_SQL, {"ids": ids}):
        out.setdefault(row.candidate_id, set()).add(row.language_code)
    return out


_NO_DAYS = NotesDays(availability=None, latest=None)


def _plan_one(
    view: Any, insights: dict, *, days: NotesDays, codes: set[str]
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    changes, markers = plan_profile_fill(
        view,
        insights,
        prior=insights,
        as_of=days.availability,
        latest_note_day=days.latest,
        include_status=False,
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
        days = await _note_days(db, ids)
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
                view,
                insights,
                days=days.get(row.id, _NO_DAYS),
                codes=codes.get(row.id, set()),
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


APPLY_BATCH = 200


async def apply_plan(
    db: AsyncSession, plan: list[PlannedFill], counts: dict[str, int], *, user_id: int
) -> dict[str, Any]:
    """Zapisz plan. Kandydat, któremu ktoś w międzyczasie wpisał pole, zostaje.

    Plan liczony od nowa pod blokadą wierszy kandydatów — zapisujemy tylko to,
    co nadal jest puste (ta sama reguła co nocna ścieżka).

    Paczkami po ``APPLY_BATCH`` kandydatów, każda we własnej transakcji
    (blokady ``FOR UPDATE`` nie wiszą na tysiącach wierszy do końca biegu),
    kandydat w savepoincie (błąd jednego nie cofa paczki). Paragon jest
    JEDEN na bieg: wpis biegu i szczegóły dopisywane po każdej paczce w jej
    transakcji, więc przerwany bieg zostawia ślad tego, co zapisał.
    ``expected`` sprawdza wołający przed pierwszą paczką.
    """
    from app.models.candidate import Candidate
    from app.services.match_score_cache import mark_stale_for_candidates

    filled_ids: list[int] = []
    field_counts: Counter[str] = Counter()
    errors = 0
    now = datetime.now(timezone.utc).isoformat()
    run: dict[str, Any] = {
        "applied_at": now,
        "applied_by": user_id,
        "counts": {**counts, "filled": 0},
        "candidate_ids": [],
    }
    for start in range(0, len(plan), APPLY_BATCH):
        # Blokada doradcza żyje do końca transakcji — bierzemy ją w każdej
        # paczce (pierwszą wziął wołający razem z liczeniem planu).
        await lock_for_apply(db)
        ids = [item.candidate_id for item in plan[start : start + APPLY_BATCH]]
        days = await _note_days(db, ids)
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
        batch_ids: list[int] = []
        batch_details: list[dict[str, Any]] = []
        for candidate in candidates:
            candidate_id = candidate.id
            try:
                async with db.begin_nested():
                    outcome = await _apply_one(
                        db,
                        candidate,
                        days=days.get(candidate_id, _NO_DAYS),
                        codes=codes.get(candidate_id, set()),
                    )
            except Exception:  # noqa: BLE001 — jeden kandydat nie zatrzymuje biegu
                logger.exception(
                    "notes-profile-fill: kandydat id=%s padł", candidate_id
                )
                errors += 1
                continue
            if outcome is None:
                continue
            changes, langs, added, before = outcome
            for name in changes:
                field_counts[_FIELD_COUNTS[name]] += 1
            if added:
                field_counts["languages_candidates"] += 1
                field_counts["languages_codes"] += added
            batch_ids.append(candidate_id)
            batch_details.append(
                {
                    "candidate_id": candidate_id,
                    "before": before,
                    "languages_added": list(langs) if added else [],
                    "applied_at": now,
                }
            )
        await db.flush()
        if batch_ids:
            await mark_stale_for_candidates(db, batch_ids)
            filled_ids.extend(batch_ids)
            run = {
                **run,
                "counts": {
                    **counts,
                    "filled": len(filled_ids),
                    "errors": errors,
                    **dict(field_counts),
                },
                "candidate_ids": list(filled_ids),
            }
            await _write_receipt(db, run, batch_details)
        await db.commit()
    run = {
        **run,
        "counts": {
            **counts,
            "filled": len(filled_ids),
            "errors": errors,
            **dict(field_counts),
        },
        "candidate_ids": list(filled_ids),
    }
    return run


async def _apply_one(
    db: AsyncSession, candidate: Any, *, days: NotesDays, codes: set[str]
) -> Optional[tuple[dict[str, Any], list[str], int, dict[str, Any]]]:
    """Zapis jednego kandydata (w savepoincie wołającego) albo ``None``."""
    extracted = (
        dict(candidate.cv_extracted_data)
        if isinstance(candidate.cv_extracted_data, dict)
        else {}
    )
    insights = extracted.get("_notes_insights")
    if not isinstance(insights, dict):
        return None
    changes, markers, langs = _plan_one(candidate, insights, days=days, codes=codes)
    if not changes and not langs:
        return None
    before = _before(candidate, changes)
    apply_profile_fill(candidate, changes)
    if markers:
        extracted["_notes_insights"] = {**insights, **markers}
        candidate.cv_extracted_data = extracted
        flag_modified(candidate, "cv_extracted_data")
    added = await fill_languages_from_notes(db, candidate.id, insights) if langs else 0
    await db.flush()
    if not changes and not added:
        return None
    return changes, langs, added, before


async def _write_receipt(
    db: AsyncSession, run: dict[str, Any], details_rows: list[dict[str, Any]]
) -> None:
    """Jeden wpis biegu (po ``applied_at``) + dopisane szczegóły paczki."""
    receipt = await _stored(db, RECEIPT_KEY)
    details = await _stored(db, DETAILS_KEY)
    runs = [
        item
        for item in receipt.get("runs", [])
        if not (
            isinstance(item, dict)
            and item.get("applied_at") == run["applied_at"]
            and item.get("applied_by") == run["applied_by"]
        )
    ]
    receipt["runs"] = [*runs, run]
    details["rows"] = [*details.get("rows", []), *details_rows]
    await db.execute(_WRITE_SQL, {"key": RECEIPT_KEY, "value": json.dumps(receipt)})
    await db.execute(_WRITE_SQL, {"key": DETAILS_KEY, "value": json.dumps(details)})
