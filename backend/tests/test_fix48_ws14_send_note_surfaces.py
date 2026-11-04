"""Decyzja C na pozostałych powierzchniach z treścią notatek — bez bazy (14.10.2026).

WS10 zakrył notatkę DL-a z wysyłki („Wysłany 150/100-110”) w ``GET /api/notes``,
przypięciu i dzwonku. Tę samą treść rekruter czytał jeszcze w podglądzie
kandydata, w „Ostatniej rozmowie” i „ostatniej notatce” na liście, w wycinkach
wyszukiwania, na osi ``/timeline`` i na osi kontraktu. Rozpoznanie notatki
z wysyłki (``recruitment_rate_hints.send_note_ids``) jest tu podmienione — jego
regułę sprawdza ``test_fix48_ws10_send_note_hidden.py``.

Wariant z bazą: ``test_fix48_ws14_send_note_surfaces_db.py``. Treści fikcyjne.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.models.user import User, UserRole
from app.services import note_kinds
from app.services import recruitment_rate_hints as hints

DL, RECRUITER = 30, 40
SEND_NOTE = "Wysłany 150/100-110"
CANDIDATE_RATE = "Kandydat chce 95 zł/h"
AT = datetime(2026, 9, 22, 9, 53, tzinfo=timezone.utc)


def _user(role: UserRole, user_id: int) -> User:
    return User(
        id=user_id, email=f"u{user_id}@example.com", role=role, roles=[role.value]
    )


def _note(note_id: int, content: str, *, author_id: int = DL, **extra):
    values = {
        "id": note_id,
        "content": content,
        "kind": note_kinds.HUMAN,
        "author_id": author_id,
        "candidate_id": 3,
        "created_at": AT,
        "note_type": None,
        "job_id": None,
        "external_source": None,
        "pinned_at": None,
        "parent_note_id": None,
        **extra,
    }
    return SimpleNamespace(**values)


@pytest.fixture
def send_ids(monkeypatch):
    """Notatka 1 (i odpowiedź 11) to notatka z wysyłki; zapis wywołań."""
    calls: list[list[int]] = []

    async def _send_note_ids(_db, note_ids):
        calls.append(sorted(note_ids))
        return frozenset({1, 11} & set(note_ids))

    monkeypatch.setattr(hints, "send_note_ids", _send_note_ids)
    return calls


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def scalars(self):
        return self

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _Db:
    """Sesja z odpowiedziami w kolejności zapytań endpointu."""

    def __init__(self, *results):
        self._results = list(results)

    async def execute(self, *_args, **_kwargs):
        return _Result(self._results.pop(0))


# ── lista kandydatów: „Ostatnia rozmowa”, „ostatnia notatka”, wycinki ──────


def test_list_preview_covers_the_send_note_for_the_recruiter():
    from app.api.candidates import _list_note_preview

    recruiter = _user(UserRole.recruiter, RECRUITER)
    lead = _user(UserRole.delivery_lead, DL)
    send, rate = _note(1, SEND_NOTE), _note(2, CANDIDATE_RATE)

    assert (
        _list_note_preview(recruiter, send, frozenset({1}))
        == note_kinds.CLIENT_RATE_PLACEHOLDER
    )
    # Notatka o stawce KANDYDATA zostaje jawna; rola ze stawką widzi cenę.
    assert _list_note_preview(recruiter, rate, frozenset({1})) == CANDIDATE_RATE
    assert _list_note_preview(lead, send, frozenset()) == SEND_NOTE


def test_send_note_is_not_a_search_snippet_source_for_the_recruiter():
    from app.api.candidates import _snippet_notes_by_candidate

    recruiter = _user(UserRole.recruiter, RECRUITER)
    rows = [
        _note(1, f"{SEND_NOTE} zqmarker"),
        _note(2, "Rozmowa: zqmarker, Java od 5 lat", author_id=RECRUITER),
        _note(3, "", author_id=RECRUITER),
    ]

    assert _snippet_notes_by_candidate(recruiter, rows, frozenset({1})) == {
        3: ["Rozmowa: zqmarker, Java od 5 lat"]
    }
    lead = _user(UserRole.delivery_lead, DL)
    assert len(_snippet_notes_by_candidate(lead, rows, frozenset())[3]) == 2


# ── oś kandydata `/timeline` ────────────────────────────────────────────────


def _timeline_db(note, reply):
    candidate = SimpleNamespace(name="Jan", lastname="Testowy")
    return _Db(
        [candidate],  # kandydat
        # notatki główne: autor, e-mail, nazwa od klienta, tytuł dla rekrutera, numer
        [(note, "Delivery Lead", "dl@example.com", None, None, None)],
        [(reply, "Delivery Lead")],  # odpowiedzi
        [],  # ruchy etapów
        [],  # aktywności
        [],  # aktywności użytkowników
    )


async def test_timeline_covers_the_send_note_and_its_reply(send_ids):
    from app.api.candidates import get_candidate_timeline

    note = _note(1, SEND_NOTE)
    reply = _note(11, "Poprawka: 155/100-110", parent_note_id=1)

    body = await get_candidate_timeline(
        candidate_id=3,
        current_user=_user(UserRole.recruiter, RECRUITER),
        db=_timeline_db(note, reply),
        limit=50,
    )

    item = next(i for i in body["timeline"] if i["type"] == "note")
    assert item["content"] == note_kinds.CLIENT_RATE_PLACEHOLDER
    assert item["content_rendered"] == note_kinds.CLIENT_RATE_PLACEHOLDER
    assert item["content_hidden"] is True
    assert item["replies"][0]["content"] == note_kinds.CLIENT_RATE_PLACEHOLDER
    assert "150/100-110" not in repr(body)
    assert send_ids == [[1, 11]]


async def test_timeline_for_a_rate_viewer_shows_the_price_without_a_query(send_ids):
    from app.api.candidates import get_candidate_timeline

    note = _note(1, SEND_NOTE)
    reply = _note(11, "Poprawka: 155/100-110", parent_note_id=1)

    body = await get_candidate_timeline(
        candidate_id=3,
        current_user=_user(UserRole.delivery_lead, DL + 1),
        db=_timeline_db(note, reply),
        limit=50,
    )

    item = next(i for i in body["timeline"] if i["type"] == "note")
    assert item["content"] == SEND_NOTE
    assert item["content_hidden"] is False
    assert send_ids == []


# ── oś kontraktu ────────────────────────────────────────────────────────────


def test_contract_timeline_item_covers_the_send_note():
    from app.api.contracts import _note_timeline_item

    note = _note(1, SEND_NOTE)
    recruiter = _user(UserRole.recruiter, RECRUITER)

    covered = _note_timeline_item(
        note, "dl@example.com", viewer=recruiter, send_note=True
    )
    plain = _note_timeline_item(note, "dl@example.com", viewer=recruiter)

    assert covered.content == note_kinds.CLIENT_RATE_PLACEHOLDER
    assert plain.content == SEND_NOTE


async def test_contract_timeline_covers_the_send_note(monkeypatch, send_ids):
    from app.api import contracts as contracts_api

    async def _visible(*_args, **_kwargs):
        return None

    monkeypatch.setattr(contracts_api, "_assert_contract", _visible)
    note, other = _note(1, SEND_NOTE), _note(2, "Przedłużenie do marca")
    db = _Db([(note, "dl@example.com"), (other, "dl@example.com")], [])

    items = await contracts_api.contract_timeline(
        contract_id=9,
        current_user=_user(UserRole.recruiter, RECRUITER),
        db=db,
        limit=100,
    )

    by_id = {item.id: item.content for item in items}
    assert by_id == {
        1: note_kinds.CLIENT_RATE_PLACEHOLDER,
        2: "Przedłużenie do marca",
    }
    assert send_ids == [[1, 2]]
