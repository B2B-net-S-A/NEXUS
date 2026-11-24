"""Decyzja C w czytnikach AI notatek kandydata — bez bazy (audyt r3, 24.11.2026).

Notatka Delivery Leada z wysyłki („Wysłany 150/100-110”: cena dla klienta /
stawka osoby) jest zwykłą notatką rodzaju ``human``, więc filtry rodzajów
(``ai_readable_sql``, ``facts_readable_sql``) jej nie wycinały:

* nocny odczyt faktów brał ją za najnowszą wzmiankę o stawce i wpisywał cenę
  dla klienta jako ``expected_rate`` kandydata (podpowiedź stawki w screeningu);
* Luna przy przepięciu screeningu dostawała ją w notatkach i oddawała rekruterowi
  w podpowiedzi — maska kwot działa tylko bez prawa do stawek, a regex nie łapie
  „X/Y-Z”;
* podsumowanie aktywności (czyta je każda rola, DLP nie łapie „150/100-110”)
  i generator CV bez procesu (dokument dla klienta) brały ją do modelu.

Rozpoznanie notatki z wysyłki (``recruitment_rate_hints.send_note_ids``) jest tu
podmienione — jego regułę sprawdza ``test_fix48_ws10_send_note_hidden.py``.
Wariant z bazą: ``test_audit_r3_send_note_ai_context_db.py``. Treści fikcyjne.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from app.models.user import User, UserRole
from app.services import note_kinds
from app.services import recruitment_rate_hints as hints

DL, RECRUITER = 30, 40
SEND_NOTE = "Wysłany 150/100-110"
TALK = "Rozmowa: Kafka od 4 lat, chce 95 zł/h, dostępny od zaraz."
AT = datetime(2026, 9, 22, 9, 53, tzinfo=timezone.utc)
DAY = date(2026, 9, 22)
SEND_ID = 2


def _user(role: UserRole, user_id: int) -> User:
    return User(
        id=user_id, email=f"u{user_id}@example.com", role=role, roles=[role.value]
    )


@pytest.fixture
def send_ids(monkeypatch):
    """Notatka ``SEND_ID`` to notatka z wysyłki; zapis wywołań."""
    calls: list[list[int]] = []

    async def _send_note_ids(_db, note_ids):
        calls.append(sorted(note_ids))
        return frozenset({SEND_ID} & set(note_ids))

    monkeypatch.setattr(hints, "send_note_ids", _send_note_ids)
    return calls


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def scalars(self):
        return self

    def __iter__(self):
        return iter(self._rows)


class _Db:
    """Sesja z odpowiedziami w kolejności zapytań; zapisuje SQL i parametry."""

    def __init__(self, *results):
        self._results = list(results)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None, **_kwargs):
        self.calls.append((str(statement), dict(params or {})))
        return _Result(self._results.pop(0))

    async def scalars(self, statement, params=None, **_kwargs):
        return await self.execute(statement, params)


# ── nocny odczyt faktów: ``load_note_rows_bulk`` ───────────────────────────


@pytest.mark.asyncio
async def test_facts_reader_drops_the_send_note_before_the_limit(send_ids):
    from app.services.notes_insights_extractor import NOTES_LIMIT, load_note_rows_bulk

    db = _Db(
        [(1,), (SEND_ID,), (3,)],  # notatki, które wolno czytać odczytowi faktów
        [(7, 1, AT, DAY, TALK, DAY)],  # wybór do limitu, już bez notatki z wysyłki
    )

    rows = await load_note_rows_bulk(db, [7])

    assert send_ids == [[1, SEND_ID, 3]]
    assert len(db.calls) == 2
    picked_sql, params = db.calls[1]
    assert params["skip"] == [SEND_ID]
    assert params["lim"] == NOTES_LIMIT
    # Najpierw filtr (WHERE zapytania wewnętrznego liczy się przed numeracją
    # `row_number()`), potem limit w zapytaniu zewnętrznym.
    assert picked_sql.index(":skip") < picked_sql.index(") picked WHERE rn <= :lim")
    assert rows == {7: [(1, AT, DAY, TALK, DAY)]}


@pytest.mark.asyncio
async def test_facts_reader_without_notes_asks_nothing_more(send_ids):
    from app.services.notes_insights_extractor import load_note_rows_bulk

    db = _Db([], [])

    assert await load_note_rows_bulk(db, [7]) == {}
    assert db.calls[1][1]["skip"] == []


def test_prompt_version_bumped_so_facts_from_send_notes_are_recomputed():
    from app.services.notes_insights_extractor import PROMPT_VERSION

    assert PROMPT_VERSION == "v7-no-send-notes"


# ── Luna przy przepięciu screeningu: ``_job_scoped_notes`` ─────────────────


def _job_notes_db():
    return _Db(
        [
            (SEND_ID, AT, DAY, SEND_NOTE),
            (1, AT, DAY, TALK),
        ]
    )


@pytest.mark.asyncio
async def test_reassign_notes_for_the_recruiter_skip_the_send_note(send_ids):
    from app.services.screening_reassign import _job_scoped_notes

    blob = await _job_scoped_notes(
        _job_notes_db(),
        candidate_id=3,
        job_ids=(10, 11),
        user=_user(UserRole.recruiter, RECRUITER),
    )

    assert "150/100-110" not in blob
    assert "Kafka od 4 lat" in blob
    assert send_ids == [[1, SEND_ID]]


@pytest.mark.asyncio
async def test_reassign_notes_for_the_delivery_lead_keep_the_send_note(send_ids):
    from app.services.screening_reassign import _job_scoped_notes

    blob = await _job_scoped_notes(
        _job_notes_db(),
        candidate_id=3,
        job_ids=(10, 11),
        user=_user(UserRole.delivery_lead, DL),
    )

    assert SEND_NOTE in blob
    assert "Kafka od 4 lat" in blob
    # Rola ze stawką do klienta nie płaci za rozpoznanie.
    assert send_ids == []


@pytest.mark.asyncio
async def test_reassign_notes_cut_to_the_limit_after_the_filter(send_ids):
    from app.services import screening_reassign as svc

    rows = [(SEND_ID, AT, DAY, SEND_NOTE)] + [
        (100 + n, AT, DAY, f"Rozmowa numer {n}: projekt w banku.")
        for n in range(svc.NOTES_ROW_LIMIT)
    ]
    db = _Db(rows)

    blob = await svc._job_scoped_notes(
        db,
        candidate_id=3,
        job_ids=(10, 11),
        user=_user(UserRole.recruiter, RECRUITER),
    )

    assert "150/100-110" not in blob
    # Zapytanie nie tnie przed filtrem — limit liczy się po wycięciu notatki.
    assert ":lim" not in db.calls[0][0]
    assert blob.count("Rozmowa numer") == svc.NOTES_ROW_LIMIT


# ── podsumowanie aktywności AI (czyta każda rola, cache wspólny) ───────────


def _note(note_id: int, content: str):
    return SimpleNamespace(
        id=note_id,
        content=content,
        kind=note_kinds.HUMAN,
        created_at=AT,
        source_created_at=None,
    )


@pytest.mark.asyncio
async def test_activity_summary_notes_skip_the_send_note_for_every_role(send_ids):
    from app.services import candidate_activity_summary_service as cas

    db = _Db([_note(SEND_ID, SEND_NOTE), _note(1, "Rozmowa: Kafka od 4 lat.")])

    section = await cas._notes_section(db, 3, (10,))

    assert "150/100-110" not in section.text
    assert "Kafka od 4 lat" in section.text
    assert section.included_items == 1
    assert send_ids == [[1, SEND_ID]]


# ── generator CV bez procesu (dokument dla klienta) ────────────────────────


@pytest.mark.asyncio
async def test_cv_notes_without_process_skip_the_send_note(send_ids):
    from app.services.cv_generator_b2b import standalone_service as svc

    db = _Db([_note(SEND_ID, SEND_NOTE), _note(1, "Kandydat zna Kafkę.")])

    text = await svc.collect_candidate_notes_text(db, candidate_id=3)

    assert "150/100-110" not in text
    assert "Kafkę" in text
    assert send_ids == [[1, SEND_ID]]
