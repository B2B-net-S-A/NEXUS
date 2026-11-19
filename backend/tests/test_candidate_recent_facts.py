"""„Ostatnio z osobą” na liście kandydatów (18.11.2026).

`GET /api/candidates?include_recent_facts=true` — dwie najnowsze informacje
o osobie (rozmowa, notatka, odrzucenie), najnowsza pierwsza. Logika:
`app/services/candidate_recent_facts.py`.

Zgłoszenie: lista pokazywała cytat z lipca („nie jest zainteresowany, nie
wydzwaniać”) z kolumny „Ostatnie odrzucenie”, choć w listopadzie była
rozmowa z „Dostępność: ASAP”.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.services import candidate_recent_facts as rf
from tests.test_candidates_last_rejection import (
    _cleanup,
    _list,
    _seed_candidate,
    _seed_job,
    _seed_stage,
)

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
CARD = (
    "<p>Notatka z rozmowy</p><p>Imię i nazwisko: Jan Test</p>"
    "<p>Stawka: 110</p><p>Dostępność: ASAP</p><p>Angielski: B2</p>"
)


# ── Testy bez bazy ───────────────────────────────────────────────────────────


def test_card_note_is_a_talk_with_availability_and_rate() -> None:
    fact = rf.note_fact(NOW, "card", CARD)
    assert fact is not None
    assert fact.kind == "talk"
    assert fact.text == "dostępność ASAP, 110 zł/h"


def test_plain_note_keeps_its_wording_and_case() -> None:
    fact = rf.note_fact(
        NOW, "status", "<div><p>Nie jest zainteresowany&nbsp;Nordeą</p></div>"
    )
    assert fact is not None
    assert fact.kind == "note"
    assert fact.text == "Nie jest zainteresowany Nordeą"


def test_empty_note_gives_no_fact() -> None:
    assert rf.note_fact(NOW, "human", "<p> </p>") is None


def test_long_note_is_shortened() -> None:
    fact = rf.note_fact(NOW, "human", "x" * 400)
    assert fact is not None
    assert len(fact.text) == rf.TEXT_MAX_CHARS
    assert fact.text.endswith("…")


def test_newest_first_and_only_two() -> None:
    old_refusal = rf.Fact(at=NOW - timedelta(days=111), kind="note", text="nie dzwonić")
    talk = rf.Fact(at=NOW - timedelta(days=16), kind="talk", text="dostępność ASAP")
    older = rf.Fact(at=NOW - timedelta(days=300), kind="note", text="stara")
    facts = rf.merge([older, old_refusal, talk], None)
    assert [f.text for f in facts] == ["dostępność ASAP", "nie dzwonić"]


def test_rejection_newer_than_notes_goes_first() -> None:
    talk = rf.Fact(at=NOW - timedelta(days=30), kind="talk", text="dostępność ASAP")
    rejection = {
        "at": NOW - timedelta(days=2),
        "note": None,
        "label": "Brak doświadczenia",
        "client_name": "Klient X",
    }
    facts = rf.merge([talk], rejection)
    assert [(f.kind, f.text, f.client_name) for f in facts] == [
        ("rejection", "Brak doświadczenia", "Klient X"),
        ("talk", "dostępność ASAP", None),
    ]


def test_traffit_rejection_duplicating_a_status_note_is_shown_once() -> None:
    """Import Traffita: ten sam opis w notatce statusu i przy odrzuceniu."""
    day = NOW - timedelta(days=111)
    note = rf.Fact(
        at=day.replace(hour=11),
        kind="note",
        text="nie jest zainteresowany i prosi żeby nie wydzwaniać",
    )
    rejection = {
        "at": day.replace(hour=13),
        "note": "nie jest zainteresowany i prosi żeby nie wydzwaniać",
        "label": "Traffit · Odrzucenie oferty przez Kandydata",
        "client_name": None,
    }
    facts = rf.merge([note], rejection)
    assert [f.kind for f in facts] == ["note"]


def test_same_day_rejection_with_other_text_stays() -> None:
    note = rf.Fact(at=NOW, kind="note", text="rozmowa o projekcie")
    rejection = {"at": NOW, "note": None, "label": "Po CV", "client_name": None}
    assert [f.kind for f in rf.merge([note], rejection)] == ["note", "rejection"]


# ── Test z bazą ──────────────────────────────────────────────────────────────


async def _seed_note(candidate_id: int, content: str, *, created_at: datetime) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.note import Note, NoteType

    async with AsyncSessionLocal() as db:
        db.add(
            Note(
                candidate_id=candidate_id,
                content=content,
                note_type=NoteType.general,
                created_at=created_at,
            )
        )
        await db.commit()


async def _drop_notes(candidate_ids: list[int]) -> None:
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.note import Note

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Note).where(Note.candidate_id.in_(candidate_ids)))
        await db.commit()


@pytest.mark.asyncio
async def test_list_shows_the_talk_above_the_older_refusal(
    app_client: AsyncClient, app_auth_headers: dict
):
    cohort = f"Rf{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    job = await _seed_job()
    person = await _seed_candidate(cohort)
    quiet = await _seed_candidate(cohort)
    try:
        refusal = "nie jest zainteresowany i prosi żeby nie wydzwaniać"
        await _seed_note(person, refusal, created_at=now - timedelta(days=111))
        await _seed_stage(
            person,
            job[0],
            "rejected",
            moved_at=now - timedelta(days=111),
            rejection_note="Odrzucenie oferty przez Kandydata",
            notes=refusal,
        )
        await _seed_note(
            person, "nie odebrał, napisałem sms", created_at=now - timedelta(days=16)
        )
        await _seed_note(person, CARD, created_at=now - timedelta(days=16, hours=-2))

        payload = await _list(
            app_client, app_auth_headers, cohort, [("include_recent_facts", "true")]
        )
        by_id = {it["id"]: it for it in payload["items"]}
        facts = by_id[person]["recent_facts"]
        # Próba kontaktu nie jest informacją o osobie; dubel z Traffita raz.
        assert [(f["kind"], f["text"]) for f in facts] == [
            ("talk", "dostępność ASAP, 110 zł/h"),
            ("note", refusal),
        ]
        assert by_id[quiet]["recent_facts"] == []

        plain = await _list(app_client, app_auth_headers, cohort)
        assert all(it.get("recent_facts") is None for it in plain["items"])
    finally:
        await _drop_notes([person, quiet])
        await _cleanup([person, quiet], [job])
