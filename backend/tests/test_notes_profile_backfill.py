"""Jednorazowe domknięcie historii: fakty z notatek do pustych pól (07.10.2026).

Trasa admina ``POST /api/admin/notes-insights/profile-fill``: próba nic nie
zapisuje, zapis wymaga liczby z próby, wartości człowieka i CV zostają.
Dane wyłącznie fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_language import CandidateLanguage
from app.models.note import Note
from app.services import notes_profile_backfill

URL = "/api/admin/notes-insights/profile-fill"


async def _seed(
    insights: dict,
    *,
    availability_date: date | None = None,
    note_day: datetime,
    content: str = "Rozmowa telefoniczna: okres wypowiedzenia miesiąc, dostępny po nim.",
    extra_notes: tuple[tuple[str, datetime], ...] = (),
) -> int:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Ola",
            lastname=f"Notatkowa{unique}",
            email=f"notes-fill-{unique}@x.com",
            availability_date=availability_date,
            cv_extracted_data={"_notes_insights": insights},
        )
        db.add(candidate)
        await db.flush()
        for text_value, day in ((content, note_day), *extra_notes):
            db.add(
                Note(
                    candidate_id=candidate.id,
                    content=text_value,
                    created_at=datetime.now(timezone.utc),
                    source_created_at=day,
                )
            )
        await db.commit()
        return candidate.id


async def _candidate(candidate_id: int) -> Candidate:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(select(Candidate).where(Candidate.id == candidate_id))
        ).scalar_one()


async def _languages(candidate_id: int) -> dict[str, tuple]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(CandidateLanguage).where(
                CandidateLanguage.candidate_id == candidate_id
            )
        )
        return {
            row.language_code: (row.provenance, row.cefr_level, row.deleted_at)
            for row in rows
        }


async def _planned_ids() -> set[int]:
    async with AsyncSessionLocal() as db:
        plan, _ = await notes_profile_backfill.build_plan(db)
    return {item.candidate_id for item in plan}


@pytest.mark.asyncio
async def test_dry_run_then_apply_fills_only_empty_fields(
    app_client: AsyncClient, app_auth_headers: dict
):
    fillable = await _seed(
        {
            "availability": {"notice_period": "1 miesiąc"},
            "languages_observed": [
                {"name": "angielski", "level": "B2"},
                {"name": "niemiecki", "level": "A2"},
            ],
            "preferences": {"work_modes": ["hybrid"], "max_onsite_days_per_week": 2},
        },
        note_day=datetime(2025, 3, 10, 12, tzinfo=timezone.utc),
    )
    # Data dostępności wpisana przez człowieka zostaje.
    human = await _seed(
        {"availability": {"raw": "od zaraz"}},
        availability_date=date(2026, 12, 1),
        note_day=datetime(2025, 3, 10, 12, tzinfo=timezone.utc),
    )
    async with AsyncSessionLocal() as db:
        # Angielski z CV (B1) — notatki go nie obniżają ani nie nadpisują.
        db.add(
            CandidateLanguage(
                candidate_id=fillable,
                language_code="en",
                language_name="English",
                cefr_level="B1",
                is_native=False,
                is_level_unknown=False,
                provenance="cv",
                manual_lock=False,
                version=1,
            )
        )
        await db.commit()

    report = await app_client.post(URL, headers=app_auth_headers)
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["dry_run"] is True
    assert body["counts"]["to_fill"] >= 1
    assert all(
        set(row) == {"candidate_id", "fields", "languages"} for row in body["sample"]
    )
    assert fillable in await _planned_ids()
    assert human not in await _planned_ids()
    # Próba niczego nie zapisuje.
    assert (await _candidate(fillable)).availability_date is None

    for params in ({"dry_run": "false"}, {"dry_run": "false", "expected": 0}):
        refused = await app_client.post(URL, params=params, headers=app_auth_headers)
        assert refused.status_code == 409, refused.text

    applied = await app_client.post(
        URL,
        params={"dry_run": "false", "expected": body["counts"]["to_fill"]},
        headers=app_auth_headers,
    )
    assert applied.status_code == 200, applied.text

    candidate = await _candidate(fillable)
    # Okres wypowiedzenia liczony od dnia notatki, nie od dziś.
    assert candidate.availability_date == date(2025, 4, 10)
    assert candidate.notice_period == 1 and candidate.notice_period_unit == "months"
    assert candidate.max_onsite_days_per_week == 2
    marker = candidate.cv_extracted_data["_notes_insights"]["_availability_from_notes"]
    assert marker["as_of"] == "2025-03-10" and marker["basis"] == "notice"
    languages = await _languages(fillable)
    assert languages["en"][:2] == ("cv", "B1")
    assert languages["de"][0] == "notes"
    assert (await _candidate(human)).availability_date == date(2026, 12, 1)

    # Paragon: liczby i ID; wartości sprzed zmiany pod osobnym kluczem.
    async with AsyncSessionLocal() as db:
        receipt = await db.scalar(
            text("SELECT value FROM app_settings WHERE key = :k"),
            {"k": notes_profile_backfill.RECEIPT_KEY},
        )
        details = await db.scalar(
            text("SELECT value FROM app_settings WHERE key = :k"),
            {"k": notes_profile_backfill.DETAILS_KEY},
        )
    assert fillable in receipt["runs"][-1]["candidate_ids"]
    row = next(r for r in details["rows"] if r["candidate_id"] == fillable)
    assert row["before"]["availability_date"] is None
    assert row["languages_added"] == ["de"]

    # Drugi przebieg nie ma już czego uzupełnić u tej osoby.
    assert fillable not in await _planned_ids()


@pytest.mark.asyncio
async def test_asap_counts_from_the_availability_note_like_the_nightly_path():
    """Przegląd #2062: „od zaraz” z 2023 + „zna Pythona” z 30.09.2026.

    „Stan na” to dzień notatki o dostępności, nie najnowszej notatki — i ta
    sama funkcja (``notes_days`` na ``load_note_rows``) co nocna ekstrakcja.
    """
    from app.services.notes_insights_extractor import load_note_rows
    from app.services.notes_profile_fill import notes_days

    candidate_id = await _seed(
        {"availability": {"raw": "od zaraz"}},
        content="Kandydat dostępny od zaraz.",
        note_day=datetime(2023, 5, 4, 12, tzinfo=timezone.utc),
        extra_notes=(
            (
                "Rozmowa: zna Pythona i Django.",
                datetime(2026, 9, 30, 12, tzinfo=timezone.utc),
            ),
        ),
    )
    async with AsyncSessionLocal() as db:
        days = notes_days(await load_note_rows(db, candidate_id))
    assert days.availability == date(2023, 5, 4)
    assert days.latest == date(2026, 9, 30)
    assert candidate_id in await _planned_ids()

    async with AsyncSessionLocal() as db:
        await notes_profile_backfill.lock_for_apply(db)
        plan, counts = await notes_profile_backfill.build_plan(db)
        mine = [item for item in plan if item.candidate_id == candidate_id]
        await notes_profile_backfill.apply_plan(db, mine, counts, user_id=1)
        await db.commit()
    candidate = await _candidate(candidate_id)
    assert candidate.availability_date == date(2023, 5, 4)
    marker = candidate.cv_extracted_data["_notes_insights"]["_availability_from_notes"]
    assert marker == {"date": "2023-05-04", "as_of": "2023-05-04", "basis": "asap"}


@pytest.mark.asyncio
async def test_relative_availability_without_an_availability_note_stays_empty():
    candidate_id = await _seed(
        {"availability": {"notice_period": "1 miesiąc"}},
        content="Rozmowa: zna Pythona i Django.",
        note_day=datetime(2026, 9, 30, 12, tzinfo=timezone.utc),
    )
    async with AsyncSessionLocal() as db:
        plan, _ = await notes_profile_backfill.build_plan(db)
    mine = [item for item in plan if item.candidate_id == candidate_id]
    # Okres wypowiedzenia wypełnia własne pole, ale nie datę dostępności.
    assert mine and "availability_date" not in mine[0].fields
    assert "notice_period" in mine[0].fields


@pytest.mark.asyncio
async def test_only_admin_can_run_the_profile_fill(app_client: AsyncClient):
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    password = f"T3st_{unique}!Fill"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=f"fill-rec-{unique}@example.com",
                password_hash=hash_password(password),
                name=f"Fill Rec {unique}",
                role=UserRole.recruiter,
                roles=[UserRole.recruiter.value],
                is_active=True,
            )
        )
        await db.commit()
    login = await app_client.post(
        "/api/auth/login",
        json={"email": f"fill-rec-{unique}@example.com", "password": password},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await app_client.post(URL, headers=headers)).status_code == 403
