"""Cena dla klienta w notatce DL-a z wysyłki — zakryta dla rekrutera (decyzja C).

Audyt 13.10.2026: „Wysłany 150/100-110” Delivery Leada jest zwykłą notatką
(`human`), więc rekruter czytał w niej cenę dla klienta — w Historii profilu
i od 13.10 w „Wcześniej u nas”. Decyzja Artura 14.10.2026: zakryć. Notatkę
z wysyłki rozpoznaje TA SAMA reguła co podpowiedź stawki do klienta (#2153):
autor przesunął kartę na „CV wysłane”, najwyżej 30 min przed albo po ruchu,
ta rekrutacja albo żadna, kwota 40–400.

Przy okazji `has_amount`: godzina („14:50”) i numer telefonu nie są kwotą —
przypadkowa liczba wypychała prawdziwą notatkę z wysyłki.

Bez bazy. Wariant z bazą: ``test_fix48_ws10_send_note_hidden_db.py``.
Treści fikcyjne.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from app.api.candidate_access import note_content_hidden, visible_note_content
from app.models.user import User, UserRole
from app.services import note_kinds
from app.services import recruitment_rate_hints as hints

SENT_AT = datetime(2026, 9, 22, 9, 52, tzinfo=timezone.utc)
DL, RECRUITER = 30, 40
JOB, OTHER_JOB = 100, 200


def _user(role: UserRole, user_id: int) -> User:
    return User(
        id=user_id, email=f"u{user_id}@example.com", role=role, roles=[role.value]
    )


def _send(job_id: int = JOB, *, by: int = DL) -> hints.Send:
    return hints.Send(job_id=job_id, moved_at=SENT_AT, moved_by=by)


def _note(
    note_id: int,
    *,
    minutes: float = 1,
    job_id: Optional[int] = None,
    author_id: int = DL,
    text: str = "Wysłany 150/100-110",
) -> hints.SendNote:
    return hints.SendNote(
        id=note_id,
        job_id=job_id,
        author_id=author_id,
        at=SENT_AT + timedelta(minutes=minutes),
        text=text,
    )


# ── has_amount ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "plain",
    [
        "rozmowa z klientem o 14:50",
        "oddzwonię o 9:45",
        "spotkanie godz. 14.50",
        "tel. 512 345 678",
        "nowy numer +48 123 456 789",
        "numer 123-456-789",
        "kontakt 512345678",
        "stacjonarny 12 345 67 89",
    ],
)
def test_clock_times_and_phone_numbers_are_not_an_amount(plain: str) -> None:
    assert hints.has_amount(plain) is False


@pytest.mark.parametrize(
    "plain",
    [
        "Wysłany 150/100-110",
        "Wysłany 150 100-110",
        "wysłany za 145, rozmowa o 14:50",
        "150 zł, tel. 512 345 678",
        "stawka 85.50",
        "120,50 zł/h",
    ],
)
def test_rate_next_to_a_time_or_a_phone_still_counts(plain: str) -> None:
    assert hints.has_amount(plain) is True


def test_note_with_a_time_no_longer_pushes_out_the_real_send_note() -> None:
    # Bliżej ruchu notatka z godziną, dalej — prawdziwa cena. Notatki bez kwoty
    # odpadają przed wyborem (`send_notes` → `has_amount`).
    notes = [
        _note(1, minutes=1, text="klient prosi o rozmowę o 14:50"),
        _note(2, minutes=4),
    ]
    with_amount = [note for note in notes if hints.has_amount(note.text)]
    assert hints.pick_send_notes([_send()], with_amount)[JOB].id == 2


# ── rozpoznanie notatek z wysyłki ───────────────────────────────────────────


def test_every_note_of_the_sender_in_the_window_with_an_amount_is_a_send_note():
    ids = hints.send_note_ids_among(
        [_send()],
        [
            _note(1, minutes=1),
            _note(2, minutes=-29, job_id=JOB, text="pokażemy za 160"),
            _note(3, minutes=31),  # za późno
            _note(4, minutes=2, job_id=OTHER_JOB),  # inna rekrutacja
            _note(5, minutes=2, author_id=RECRUITER),  # nie wysyłający
            _note(6, minutes=3, text="Wysłany, czekamy na odpowiedź"),  # bez kwoty
            _note(7, minutes=3, text="rozmowa z klientem o 14:50"),  # godzina
        ],
    )
    assert ids == {1, 2}


def test_without_a_send_nothing_is_a_send_note():
    assert hints.send_note_ids_among([], [_note(1)]) == set()


# ── zakrycie treści ─────────────────────────────────────────────────────────


def test_send_note_is_hidden_from_the_recruiter_but_not_from_rate_viewers():
    recruiter = _user(UserRole.recruiter, RECRUITER)
    lead = _user(UserRole.delivery_lead, DL)
    other_lead = _user(UserRole.delivery_lead, DL + 1)
    finance = _user(UserRole.finance, 50)

    assert note_content_hidden(
        recruiter, kind=note_kinds.HUMAN, author_id=DL, send_note=True
    )
    for viewer in (lead, other_lead, finance):
        assert not note_content_hidden(
            viewer, kind=note_kinds.HUMAN, author_id=DL, send_note=True
        )
    # Zwykła notatka (stawka KANDYDATA jest dla rekrutera jawna) — bez zmian.
    assert not note_content_hidden(recruiter, kind=note_kinds.HUMAN, author_id=DL)


def test_visible_note_content_uses_the_placeholder_for_a_send_note():
    recruiter = _user(UserRole.recruiter, RECRUITER)
    note = type(
        "N", (), {"kind": note_kinds.HUMAN, "author_id": DL, "content": "Wysłany 150"}
    )()
    assert (
        visible_note_content(recruiter, note, send_note=True)
        == note_kinds.CLIENT_RATE_PLACEHOLDER
    )
    assert visible_note_content(recruiter, note) == "Wysłany 150"


# ── fragment w dzwonku wzmianki ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mention_snippet_of_a_send_note_does_not_carry_the_price(monkeypatch):
    # „Wysłany 150/100-110 @rekruter” — dzwonek oznaczonej osoby niósł cenę.
    from types import SimpleNamespace

    from app.api import notes as notes_api

    found = {}

    async def _send_note_ids(_db, note_ids):
        found["ids"] = list(note_ids)
        return frozenset({7})

    monkeypatch.setattr(hints, "send_note_ids", _send_note_ids)
    note = SimpleNamespace(
        id=7,
        content="Wysłany 150/100-110 @Ola Testowa",
        note_type="general",
        external_source=None,
        author_id=None,
        candidate_id=3,
    )
    snippet = await notes_api._mention_snippet(object(), note)
    assert snippet == note_kinds.CLIENT_RATE_SNIPPET
    assert found["ids"] == [7]


@pytest.mark.asyncio
async def test_mention_snippet_of_an_ordinary_note_keeps_the_text(monkeypatch):
    from types import SimpleNamespace

    from app.api import notes as notes_api

    async def _none(_db, _note_ids):
        return frozenset()

    monkeypatch.setattr(hints, "send_note_ids", _none)
    note = SimpleNamespace(
        id=8,
        content="Kandydat chce 95 zł/h @Ola Testowa",
        note_type="general",
        external_source=None,
        author_id=None,
        candidate_id=3,
    )
    snippet = await notes_api._mention_snippet(object(), note)
    assert "95" in snippet
