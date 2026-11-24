"""Decyzja C na trzech kolejnych powierzchniach z treścią notatek (audyt r4, 24.11.2026).

Notatka Delivery Leada z wysyłki („Wysłany 150/100-110”) to cena dla klienta.
Rekruter czytał ją jeszcze w ostatniej notatce follow-upu
(``GET /api/candidate-followups/candidates/{id}``), w cytatach „skąd ✓”
(``POST /api/search/candidates/requirement-evidence``) i na liście notatek
pakietu CV (``GET /api/cv-generator/generated/{id}/package``). Rozpoznanie
notatki z wysyłki (``recruitment_rate_hints.send_note_ids``) jest tu
podmienione — jego regułę sprawdza ``test_fix48_ws10_send_note_hidden.py``.
Treści fikcyjne.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from app.models.user import User, UserRole
from app.services import note_kinds
from app.services import recruitment_rate_hints as hints

DL, RECRUITER = 30, 40
SEND_NOTE = "Wysłany 150/100-110, Java senior"
TALK_NOTE = "Rozmowa: Java od 6 lat, chce 95 zł/h"
AT = datetime(2026, 9, 22, 9, 53, tzinfo=timezone.utc)

RATE_VIEWERS = (
    UserRole.delivery_lead,
    UserRole.head_of_recruitment,
    UserRole.finance,
)


def _user(role: UserRole, user_id: int) -> User:
    return User(
        id=user_id, email=f"u{user_id}@example.com", role=role, roles=[role.value]
    )


@pytest.fixture
def send_ids(monkeypatch):
    """Notatka 1 to notatka z wysyłki; zapis wywołań rozpoznania."""
    calls: list[list[int]] = []

    async def _send_note_ids(_db, note_ids):
        calls.append(sorted(note_ids))
        return frozenset({1} & set(note_ids))

    monkeypatch.setattr(hints, "send_note_ids", _send_note_ids)
    return calls


class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _Db:
    """Sesja z odpowiedziami w kolejności zapytań."""

    def __init__(self, *results):
        self._results = list(results)

    async def execute(self, *_args, **_kwargs):
        return _Rows(self._results.pop(0))

    async def scalars(self, *_args, **_kwargs):
        return _Rows(self._results.pop(0))


# ── follow-up: ostatnia notatka procesu ─────────────────────────────────────


def _followup():
    from app.services import candidate_followups as svc

    process = svc.WaitingProcess(
        candidate_id=3,
        job_id=5,
        job_title="Java Developer",
        client_id=None,
        client_name=None,
        column="cv_sent",
        stage_name=None,
        sent_at=AT,
        silent_since=AT,
        owner_id=None,
    )
    return svc.Followup(
        candidate_id=3,
        processes=[process],
        due_on=date(2026, 9, 29),
        caller_id=None,
        caller_reason="owner",
        owner_ids=frozenset(),
        last_contact=None,
    )


@pytest.fixture
def no_names(monkeypatch):
    from app.services import candidate_followups as svc

    async def _names(_db, _ids):
        return {}

    monkeypatch.setattr(svc, "user_names", _names)


def _note_row(note_id: int, content: str, *, author_id: int = DL):
    # id, candidate_id, job_id, kind, content, author_id, created_at
    return (note_id, 3, 5, note_kinds.HUMAN, content, author_id, AT)


async def test_followup_last_note_covers_the_send_note_for_the_recruiter(
    send_ids, no_names
):
    from app.api.candidate_followups import serialize_rows

    rows = await serialize_rows(
        _Db([_note_row(1, SEND_NOTE)]),
        [_followup()],
        today=date(2026, 9, 29),
        with_notes=True,
        viewer=_user(UserRole.recruiter, RECRUITER),
    )

    assert rows[0].processes[0].last_note == note_kinds.CLIENT_RATE_PLACEHOLDER
    assert "150/100-110" not in repr(rows)
    assert send_ids == [[1]]


async def test_followup_last_note_without_a_viewer_fails_closed(send_ids, no_names):
    from app.api.candidate_followups import serialize_rows

    rows = await serialize_rows(
        _Db([_note_row(1, SEND_NOTE)]),
        [_followup()],
        today=date(2026, 9, 29),
        with_notes=True,
    )

    assert rows[0].processes[0].last_note == note_kinds.CLIENT_RATE_PLACEHOLDER


async def test_followup_last_note_keeps_other_notes_for_the_recruiter(
    send_ids, no_names
):
    from app.api.candidate_followups import serialize_rows

    rows = await serialize_rows(
        _Db([_note_row(2, TALK_NOTE, author_id=RECRUITER + 1)]),
        [_followup()],
        today=date(2026, 9, 29),
        with_notes=True,
        viewer=_user(UserRole.recruiter, RECRUITER),
    )

    assert rows[0].processes[0].last_note == TALK_NOTE


@pytest.mark.parametrize("role", RATE_VIEWERS)
async def test_followup_last_note_shows_the_price_to_rate_viewers(
    role, send_ids, no_names
):
    from app.api.candidate_followups import serialize_rows

    rows = await serialize_rows(
        _Db([_note_row(1, SEND_NOTE)]),
        [_followup()],
        today=date(2026, 9, 29),
        with_notes=True,
        viewer=_user(role, DL + 1),
    )

    assert rows[0].processes[0].last_note == SEND_NOTE
    assert send_ids == []


async def test_followup_route_passes_the_viewer(monkeypatch):
    from app.api import candidate_followups as api

    seen: list = []

    async def _candidate(_db, _cid):
        return SimpleNamespace(id=3)

    async def _detail(_db, _cid, *, viewer):
        seen.append(viewer)
        return "detail"

    monkeypatch.setattr(api, "_require_candidate", _candidate)
    monkeypatch.setattr(api, "_detail", _detail)
    recruiter = _user(UserRole.recruiter, RECRUITER)

    assert (
        await api.get_candidate_followup(
            candidate_id=3, current_user=recruiter, db=None
        )
        == "detail"
    )
    assert seen == [recruiter]


# ── „skąd ✓”: cytaty z notatek ──────────────────────────────────────────────


def _evidence_row(note_id: int, content: str, *, author_id: int = DL):
    # id, at, author name, kind, content, author_id
    return (note_id, AT, "Osoba Testowa", note_kinds.HUMAN, content, author_id)


def _evidence_db():
    return _Db([_evidence_row(1, SEND_NOTE), _evidence_row(2, TALK_NOTE)])


async def test_requirement_evidence_drops_the_send_note_for_the_recruiter(send_ids):
    from app.services.requirement_evidence import load_notes

    notes = await load_notes(
        _evidence_db(), 3, ["java"], viewer=_user(UserRole.recruiter, RECRUITER)
    )

    assert [n.id for n in notes] == [2]
    assert "150/100-110" not in repr(notes)
    assert send_ids == [[1, 2]]


@pytest.mark.parametrize("role", RATE_VIEWERS)
async def test_requirement_evidence_keeps_the_send_note_for_rate_viewers(
    role, send_ids
):
    from app.services.requirement_evidence import load_notes

    notes = await load_notes(_evidence_db(), 3, ["java"], viewer=_user(role, DL + 1))

    assert [n.id for n in notes] == [1, 2]
    assert send_ids == []


async def test_requirement_evidence_route_passes_the_viewer(monkeypatch):
    from app.api import candidate_search, search
    from app.services import requirement_evidence

    seen: list = []

    async def _job(*_args, **_kwargs):
        return None

    async def _load(_db, _cid, _labels, *, viewer):
        seen.append(viewer)
        return []

    class _GetDb:
        async def get(self, *_args):
            return SimpleNamespace(id=3)

    monkeypatch.setattr(candidate_search, "_authorized_job", _job)
    monkeypatch.setattr(requirement_evidence, "load_notes", _load)
    monkeypatch.setattr(requirement_evidence, "collect", lambda *_a: {})
    recruiter = _user(UserRole.recruiter, RECRUITER)
    body = SimpleNamespace(job_id=5, candidate_id=3, labels=["java"])

    await search.candidate_requirement_evidence.__wrapped__(
        request=None, body=body, current_user=recruiter, db=_GetDb()
    )

    assert seen == [recruiter]


# ── pakiet CV: lista notatek pary ───────────────────────────────────────────


def _package_note(note_id: int, content: str, *, author_id: int = DL):
    return SimpleNamespace(
        id=note_id,
        content=content,
        kind=note_kinds.HUMAN,
        author_id=author_id,
        updated_at=AT,
    )


@pytest.fixture
def package(monkeypatch):
    from app.api import cv_generator_b2b as api
    from app.services import cv_packages

    async def _document(*_args, **_kwargs):
        return SimpleNamespace(candidate_id=3, job_id=5)

    async def _assess(*_args, **_kwargs):
        return {"ready": False}, None

    monkeypatch.setattr(api, "_load_generated_document", _document)
    monkeypatch.setattr(cv_packages, "assess", _assess)

    async def _get(user):
        return await api.get_cv_package(
            generated_id=9,
            current_user=user,
            note_id=None,
            db=_Db([_package_note(1, SEND_NOTE), _package_note(2, TALK_NOTE)]),
        )

    return _get


async def test_cv_package_covers_the_send_note_for_the_recruiter(send_ids, package):
    state = await package(_user(UserRole.recruiter, RECRUITER))

    by_id = {n["id"]: n["content"] for n in state["notes"]}
    assert by_id == {1: note_kinds.CLIENT_RATE_PLACEHOLDER, 2: TALK_NOTE}
    assert send_ids == [[1, 2]]


@pytest.mark.parametrize("role", RATE_VIEWERS)
async def test_cv_package_shows_the_send_note_to_rate_viewers(role, send_ids, package):
    state = await package(_user(role, DL + 1))

    by_id = {n["id"]: n["content"] for n in state["notes"]}
    assert by_id == {1: SEND_NOTE, 2: TALK_NOTE}
    assert send_ids == []
