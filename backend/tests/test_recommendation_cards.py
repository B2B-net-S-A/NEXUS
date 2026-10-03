"""Karta rekomendacji na serwerze (0413): import z notatek, API, strażnicy.

Czyste reguły: ``test_recommendation_card_rules.py``; parser:
``test_recommendation_card_parser.py``. Dane wyłącznie fikcyjne.
"""

import re
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.note import Note, NoteType
from app.models.note import _set_note_kind_on_insert
from app.models.recommendation_card import RecommendationCard
from app.models.user import User, UserRole
from app.services import note_kinds, recommendation_card_schema
from app.services import recommendation_card_import as card_import
from app.services import recommendation_cards as cards

_BACKEND = Path(__file__).resolve().parents[1]

_CARD = (
    "<p>Imię i nazwisko: Tomasz Wzorcowy</p><p>Stawka: 135 zł/h</p>"
    "<p>Dostępność: 1 miesiąc</p><p>Tryb pracy: hybrydowo, 2 dni w tygodniu</p>"
    "<p>Lokalizacja: Łódź</p><p>Narodowość: polska</p>"
    "<p>P1: Opisz doświadczenie z Javą.</p><p>Odpowiedź: Java 21 w banku.</p>"
)


# ── bez bazy ─────────────────────────────────────────────────────────────────


def test_entrypoint_mirrors_the_migration_sql():
    entrypoint = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    statements = (
        recommendation_card_schema.TABLE_DDL,
        *recommendation_card_schema.COLUMN_DDL,
    )
    for stmt in statements:
        assert stmt in entrypoint, stmt


def test_card_disappears_with_the_candidate_and_the_job():
    ddl = recommendation_card_schema.TABLE_DDL
    assert "REFERENCES candidates(id) ON DELETE CASCADE" in ddl
    assert "REFERENCES jobs(id) ON DELETE CASCADE" in ddl


def test_only_listed_modules_read_recommendation_cards():
    """Narodowość z karty nie może trafić do promptów ani dopasowania.

    Kartę czyta wyłącznie jej własne API, import z notatek i hak scalania
    kandydatów. Nowy czytelnik = świadomy wpis tutaj.
    """
    allowed = {
        "app/api/recommendation_cards.py",
        "app/api/notes.py",
        "app/main.py",
        "app/models/__init__.py",
        "app/models/recommendation_card.py",
        "app/services/candidate_merge.py",
        "app/services/recommendation_card_import.py",
        "app/services/recommendation_cards.py",
        "app/tasks/recommendation_card_import.py",
    }
    pattern = re.compile(
        r"^\s*(?:from|import)\s.*\brecommendation_card(?:s|_rules|_import)?\b"
        r"|\bRecommendationCard\b",
        re.M,
    )
    readers = {
        path.relative_to(_BACKEND).as_posix()
        for path in (_BACKEND / "app").rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    }
    assert readers <= allowed, sorted(readers - allowed)


def test_explicit_note_kind_survives_the_listener():
    note = Note(
        content="Wyślijmy za 161 zł/h",
        note_type=NoteType.general,
        kind=note_kinds.DL_REVIEW,
    )
    _set_note_kind_on_insert(None, None, note)
    assert note.kind == note_kinds.DL_REVIEW


# ── z bazą ───────────────────────────────────────────────────────────────────


async def _seed_user(role: UserRole) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"card-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Card"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Card {role.value} {unique}",
            role=role,
            roles=[role.value],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id, email, password


async def _seed_pair() -> tuple[int, int]:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Card client {unique}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Card job {unique}", client_id=client.id, status=JobStatus.published
        )
        candidate = Candidate(
            name="Tomasz", lastname=f"Wzorcowy{unique}", email=f"card-{unique}@x.com"
        )
        db.add_all([job, candidate])
        await db.commit()
        return candidate.id, job.id


async def _add_note(candidate_id: int, job_id, content: str = _CARD) -> int:
    async with AsyncSessionLocal() as db:
        note = Note(
            content=content,
            note_type=NoteType.general,
            candidate_id=candidate_id,
            job_id=job_id,
        )
        db.add(note)
        await db.commit()
        return note.id


async def _drain() -> None:
    for _ in range(200):
        async with AsyncSessionLocal() as db:
            done = await card_import.process_pending(db)
            await db.commit()
        if not done:
            return
    raise AssertionError("import kart nie doszedł do końca")


async def _card(candidate_id: int, job_id: int):
    async with AsyncSessionLocal() as db:
        return await cards.load_card(db, candidate_id=candidate_id, job_id=job_id)


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_import_builds_the_card_and_stamps_the_note(app_client: AsyncClient):
    candidate_id, job_id = await _seed_pair()
    note_id = await _add_note(candidate_id, job_id)

    await _drain()

    card = await _card(candidate_id, job_id)
    assert card is not None
    assert card.fields_notes["rate"]["value"] == 135.0
    assert card.fields_notes["rate"]["note_id"] == note_id
    assert card.note_answers["items"][0]["answer"] == "Java 21 w banku."
    assert "name" not in card.fields_notes
    async with AsyncSessionLocal() as db:
        stamped, updated, created = (
            await db.execute(
                select(Note.card_parsed_hash, Note.updated_at, Note.created_at).where(
                    Note.id == note_id
                )
            )
        ).one()
    assert stamped
    # Stempel odcisku nie rusza `updated_at` (odcisk nocnego odczytu faktów).
    assert updated == created


@pytest.mark.asyncio
async def test_job_linked_later_by_raw_sql_is_picked_up(app_client: AsyncClient):
    candidate_id, job_id = await _seed_pair()
    note_id = await _add_note(candidate_id, None)
    await _drain()
    assert await _card(candidate_id, job_id) is None

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE notes SET job_id = :job_id WHERE id = :id"),
            {"job_id": job_id, "id": note_id},
        )
        await db.commit()
    await _drain()

    card = await _card(candidate_id, job_id)
    assert card is not None and card.fields_notes["location"]["raw"] == "Łódź"


@pytest.mark.asyncio
async def test_note_deleted_by_raw_sql_is_repaired(app_client: AsyncClient):
    candidate_id, job_id = await _seed_pair()
    note_id = await _add_note(candidate_id, job_id)
    await _drain()
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM notes WHERE id = :id"), {"id": note_id})
        await db.commit()

    for _ in range(50):
        async with AsyncSessionLocal() as db:
            repaired = await card_import.repair_orphans(db)
            await db.commit()
        if not repaired:
            break

    card = await _card(candidate_id, job_id)
    assert card is not None
    assert card.fields_notes == {} and card.note_answers == {}


@pytest.mark.asyncio
async def test_note_saved_in_nexus_fills_the_card_only_with_the_flag(
    app_client: AsyncClient, monkeypatch
):
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(app_client, email, password)

    monkeypatch.setattr(settings, "RECOMMENDATION_CARD_IMPORT_ENABLED", False)
    off_candidate, off_job = await _seed_pair()
    created = await app_client.post(
        "/api/notes",
        headers=headers,
        json={"content": _CARD, "candidate_id": off_candidate, "job_id": off_job},
    )
    assert created.status_code == 201, created.text
    assert await _card(off_candidate, off_job) is None

    monkeypatch.setattr(settings, "RECOMMENDATION_CARD_IMPORT_ENABLED", True)
    candidate_id, job_id = await _seed_pair()
    created = await app_client.post(
        "/api/notes",
        headers=headers,
        json={"content": _CARD, "candidate_id": candidate_id, "job_id": job_id},
    )
    assert created.status_code == 201, created.text
    assert created.json()["kind"] == note_kinds.CARD
    card = await _card(candidate_id, job_id)
    assert card is not None and card.fields_notes["rate"]["value"] == 135.0

    # Usunięcie notatki zabiera jej pola z karty.
    deleted = await app_client.delete(
        f"/api/notes/{created.json()['id']}", headers=headers
    )
    assert deleted.status_code == 204, deleted.text
    card = await _card(candidate_id, job_id)
    assert card is not None and card.fields_notes == {}


@pytest.mark.asyncio
async def test_api_manual_field_wins_and_can_be_removed(app_client: AsyncClient):
    candidate_id, job_id = await _seed_pair()
    await _add_note(candidate_id, job_id)
    await _drain()
    user_id, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(app_client, email, password)
    params = {"candidate_id": candidate_id, "job_id": job_id}

    before = await app_client.get(
        "/api/recommendation-cards", params=params, headers=headers
    )
    assert before.status_code == 200, before.text
    body = before.json()
    assert body["exists"] is True
    assert body["fields"]["rate"]["source"] == "note"
    assert body["completeness"]["filled"] == 5
    assert "english" in body["completeness"]["missing"]
    assert body["note_answers"]["items"][0]["question"].startswith("Opisz")
    assert "Stawka: 135 zł/h" in body["legacy_text"]

    saved = await app_client.put(
        "/api/recommendation-cards",
        headers=headers,
        json={**params, "fields": {"rate": "150 zł/h", "english": "C1"}},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["fields"]["rate"]["value"] == 150.0
    assert body["fields"]["rate"]["source"] == "manual"
    assert body["fields"]["rate"]["by"] == user_id
    assert body["fields"]["english"]["level"] == "C1"
    assert body["completeness"]["filled"] == 6

    # Ponowny import z notatek nie rusza pól wpisanych ręcznie.
    async with AsyncSessionLocal() as db:
        await card_import.refresh_candidate(db, candidate_id=candidate_id)
        await db.commit()
    again = await app_client.get(
        "/api/recommendation-cards", params=params, headers=headers
    )
    assert again.json()["fields"]["rate"]["value"] == 150.0

    removed = await app_client.put(
        "/api/recommendation-cards",
        headers=headers,
        json={**params, "fields": {"rate": None}},
    )
    assert removed.json()["fields"]["rate"]["value"] == 135.0
    assert removed.json()["fields"]["rate"]["source"] == "note"

    # Dziennik zdarzeń niesie nazwy pól, nie wartości.
    async with AsyncSessionLocal() as db:
        logged = (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == "candidate",
                    Activity.entity_id == candidate_id,
                    Activity.action == "recommendation_card_updated",
                )
            )
        ).all()
    assert len(logged) == 2
    assert all(set(item.details) == {"job_id", "fields"} for item in logged)


@pytest.mark.asyncio
async def test_api_card_without_a_row_is_empty_and_unknown_field_is_refused(
    app_client: AsyncClient,
):
    candidate_id, job_id = await _seed_pair()
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(app_client, email, password)
    params = {"candidate_id": candidate_id, "job_id": job_id}

    empty = await app_client.get(
        "/api/recommendation-cards", params=params, headers=headers
    )
    assert empty.status_code == 200, empty.text
    assert empty.json()["exists"] is False
    assert empty.json()["completeness"]["status"] == "empty"

    unknown = await app_client.put(
        "/api/recommendation-cards",
        headers=headers,
        json={**params, "fields": {"salary": "10"}},
    )
    assert unknown.status_code == 422
    too_long = await app_client.put(
        "/api/recommendation-cards",
        headers=headers,
        json={**params, "fields": {"location": "x" * 301}},
    )
    assert too_long.status_code == 422
    missing = await app_client.get(
        "/api/recommendation-cards",
        params={"candidate_id": candidate_id, "job_id": 2_000_000_000},
        headers=headers,
    )
    assert missing.status_code == 404
    assert await _card(candidate_id, job_id) is None


@pytest.mark.asyncio
async def test_api_refuses_the_viewer_role(app_client: AsyncClient):
    candidate_id, job_id = await _seed_pair()
    _, email, password = await _seed_user(UserRole.user)
    headers = await _login(app_client, email, password)

    denied = await app_client.get(
        "/api/recommendation-cards",
        params={"candidate_id": candidate_id, "job_id": job_id},
        headers=headers,
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_nationality_is_suggested_from_the_previous_card(
    app_client: AsyncClient,
):
    candidate_id, job_id = await _seed_pair()
    await _add_note(candidate_id, job_id)
    await _drain()
    _, other_job_id = await _seed_pair()
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(app_client, email, password)

    fresh = await app_client.get(
        "/api/recommendation-cards",
        params={"candidate_id": candidate_id, "job_id": other_job_id},
        headers=headers,
    )
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()["suggestions"] == {"nationality": "polska"}
    assert "nationality" not in fresh.json()["fields"]


@pytest.mark.asyncio
async def test_merge_joins_manual_fields_of_both_cards(app_client: AsyncClient):
    survivor_id, job_id = await _seed_pair()
    duplicate_id, _ = await _seed_pair()
    user_id, _, _ = await _seed_user(UserRole.recruiter)
    async with AsyncSessionLocal() as db:
        await cards.save_manual(
            db,
            candidate_id=survivor_id,
            job_id=job_id,
            changes={"rate": "150"},
            user_id=user_id,
        )
        await cards.save_manual(
            db,
            candidate_id=duplicate_id,
            job_id=job_id,
            changes={"rate": "120", "english": "B2"},
            user_id=user_id,
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        await cards.merge_manual_fields(
            db, survivor_id=survivor_id, duplicate_id=duplicate_id
        )
        await db.commit()

    kept = await _card(survivor_id, job_id)
    assert kept.fields_manual["rate"]["raw"] == "150"
    assert kept.fields_manual["english"]["raw"] == "B2"
    assert await _card(duplicate_id, job_id) is None
    async with AsyncSessionLocal() as db:
        total = await db.scalar(
            select(RecommendationCard.id).where(RecommendationCard.job_id == job_id)
        )
    assert total == kept.id


@pytest.mark.asyncio
async def test_same_value_confirms_a_hint_from_the_previous_attempt(
    app_client: AsyncClient,
):
    from datetime import datetime, timezone

    candidate_id, job_id = await _seed_pair()
    user_id, _, _ = await _seed_user(UserRole.recruiter)
    old = datetime(2026, 9, 1, tzinfo=timezone.utc)
    attempt = datetime(2026, 10, 1, tzinfo=timezone.utc)
    pair = {"candidate_id": candidate_id, "job_id": job_id, "user_id": user_id}

    async with AsyncSessionLocal() as db:
        await cards.save_manual(db, changes={"rate": "150 zł/h"}, now=old, **pair)
        await db.commit()
    async with AsyncSessionLocal() as db:
        _, unchanged = await cards.save_manual(db, changes={"rate": "150 zł/h"}, **pair)
        _, confirmed = await cards.save_manual(
            db, changes={"rate": "150 zł/h"}, attempt_started=attempt, **pair
        )
        await db.commit()

    assert unchanged == []
    assert confirmed == ["rate"]
    card = await _card(candidate_id, job_id)
    current, previous = cards.split_fields(
        card.fields_notes, card.fields_manual, attempt_started=attempt
    )
    assert "rate" in current and previous == {}


@pytest.mark.asyncio
async def test_one_failing_candidate_does_not_block_the_import(
    app_client: AsyncClient, monkeypatch
):
    broken_candidate, broken_job = await _seed_pair()
    broken_note = await _add_note(broken_candidate, broken_job)
    candidate_id, job_id = await _seed_pair()
    await _add_note(candidate_id, job_id)
    original = cards.rebuild_pair

    async def flaky(db, *, candidate_id: int, job_id: int) -> bool:
        if candidate_id == broken_candidate:
            raise RuntimeError("boom")
        return await original(db, candidate_id=candidate_id, job_id=job_id)

    monkeypatch.setattr(cards, "rebuild_pair", flaky)
    await _drain()

    assert await _card(broken_candidate, broken_job) is None
    card = await _card(candidate_id, job_id)
    assert card is not None and card.fields_notes["rate"]["value"] == 135.0
    async with AsyncSessionLocal() as db:
        stamped = await db.scalar(
            select(Note.card_parsed_hash).where(Note.id == broken_note)
        )
    assert stamped
