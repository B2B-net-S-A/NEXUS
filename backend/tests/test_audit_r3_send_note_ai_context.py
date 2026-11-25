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

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
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


# ── podsumowanie aktywności: stary cache (review PR #3942) ─────────────────


def test_activity_summary_policy_bumped_so_cached_send_note_prices_stop_serving():
    """GET podsumowania nie generuje i oddaje wiersz także przy innym
    ``source_version`` (``is_stale`` to tylko plakietka). Wiersz sprzed
    poprawki mógł przepisać „150/100-110”, a DLP kwot tego nie łapie —
    przestaje pasować dopiero po zmianie wersji polityki (klucz ``get_cached``)."""
    from app.services import candidate_activity_summary_service as cas

    assert cas.CONTENT_POLICY_VERSION != "candidate-summary-no-finance-v3"
    assert not cas._contains_financial_amount("Kandydat wysłany 150/100-110.")


@pytest.mark.asyncio
async def test_activity_summary_cache_is_keyed_by_the_policy_version():
    from sqlalchemy.dialects import postgresql

    from app.services import candidate_activity_summary_service as cas

    seen: list = []

    class _ScalarDb:
        async def scalar(self, statement):
            seen.append(statement)
            return None

    await cas.get_cached(3, _ScalarDb(), visibility_scope_hash="a" * 64)

    sql = str(
        seen[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert f"content_policy_version = '{cas.CONTENT_POLICY_VERSION}'" in sql


# ── fakty policzone przed v7 z notatki z wysyłki (review PR #3942) ─────────
#
# Samo podbicie PROMPT_VERSION nie cofało starej ceny dla klienta: krótki wsad
# po wycięciu notatki idzie w ``stamp_no_content`` (kopiuje stare fakty), a
# odczyt bez stawki nie rusza kolumny ``expected_rate_hourly`` (zapis tylko
# przy wartości). Kwota z notatki z wysyłki, której nie ma we wsadzie, znika.

V6 = "notes_insights:v6-note-kinds:model"
CID = 7
SHORT = "Oddzwoni jutro, ok."
LONG_TALK = "Rozmowa: Kafka od 4 lat, projekt w banku, dostępny od zaraz po urlopie."
SEND_AMOUNTS = ("150", "100", "110")


def _send_note_cand(*, column=None, rate_written=None, expected_value=150):
    insights = {
        "_extractor": V6,
        "_input_hash": "old",
        "_extracted_at": "2026-09-23T00:00:00+00:00",
    }
    if expected_value is not None:
        insights["expected_rate"] = {
            "value": expected_value,
            "currency": "PLN",
            "period": "h",
        }
    if rate_written is not None:
        insights["_rate_written"] = rate_written
        insights["_rate_from_notes"] = True
    return SimpleNamespace(
        id=CID,
        skills=None,
        years_it_experience=None,
        expected_rate_hourly=column,
        expected_rate_currency="PLN" if column is not None else None,
        profile_rate_version=3,
        accepts_below_min_rate=None,
        notice_period=None,
        notice_period_unit=None,
        availability_date=None,
        availability_status="unknown",
        cv_extracted_data={"_notes_insights": insights},
        max_onsite_days_per_week=None,
        preferences=None,
        remote_modes=None,
        skills_manually_curated=False,
    )


class _SyncDb:
    """Sesja ``_extract_candidate``: jeden kandydat, zapis audytów."""

    def __init__(self, cand):
        self.cand = cand
        self.added: list = []
        self.info: dict = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def execute(self, *_args, **_kwargs):
        return SimpleNamespace(scalar_one_or_none=lambda: self.cand)

    async def scalar(self, *_args, **_kwargs):
        return self.cand

    async def commit(self):
        return None

    async def flush(self):
        return None

    def add(self, obj):
        self.added.append(obj)

    def begin_nested(self):
        @asynccontextmanager
        async def _nested():
            yield

        return _nested()


@pytest.fixture
def sync_world(monkeypatch):
    """``_extract_candidate`` bez bazy i bez modelu; zwraca ustawiacz świata."""
    import app.services.candidate_notes_facts as facts_mod
    import app.services.match_score_cache as score_cache
    import app.services.notes_insights_extractor as extractor
    from app.services import conversation_facts
    from app.tasks import notes_insights_sync as sync

    stale: list[int] = []

    async def _mark_stale(_db, cid):
        stale.append(cid)

    @asynccontextmanager
    async def _no_quota(*_args, **_kwargs):
        yield

    async def _no_contracts(*_args, **_kwargs):
        return None

    async def _no_languages(*_args, **_kwargs):
        return 0

    for module in (extractor, facts_mod):
        monkeypatch.setattr(module, "flag_modified", lambda *a, **k: None)
    monkeypatch.setattr(score_cache, "mark_stale_for_candidate", _mark_stale)
    monkeypatch.setattr(conversation_facts, "enabled", lambda: False)
    monkeypatch.setattr(sync, "ai_feature", _no_quota)
    monkeypatch.setattr(sync, "load_contract_history", _no_contracts)
    monkeypatch.setattr(sync, "fill_languages_from_notes", _no_languages)

    def _setup(cand, *, notes, parsed=None):
        db = _SyncDb(cand)
        rows = [(100 + n, AT, DAY, body, DAY) for n, body in enumerate(notes)]

        async def _rows(_db, _cid):
            return rows

        async def _amounts(_db, cid, blob):
            assert cid == CID
            sent = frozenset(Decimal(a) for a in SEND_AMOUNTS)
            return sent - extractor._numbers_in(blob)

        async def _extract(_blob):
            assert parsed is not None, "krótki wsad nie woła modelu"
            return parsed

        monkeypatch.setattr(sync, "AsyncSessionLocal", lambda: db)
        monkeypatch.setattr(sync, "load_note_rows", _rows)
        # Pętla woła send_note_amounts_to_release z ekstraktora, a ten — tę funkcję.
        monkeypatch.setattr(extractor, "stale_send_note_amounts", _amounts)
        monkeypatch.setattr(sync, "extract_insights", _extract)
        return db

    _setup.stale = stale
    return _setup


@pytest.mark.asyncio
async def test_short_input_drops_the_send_note_rate_kept_by_the_stamp(sync_world):
    from app.services.screening_suggestions import suggestions_from_notes
    from app.tasks.notes_insights_sync import _empty_stats, _extract_candidate

    cand = _send_note_cand()
    sync_world(cand, notes=[SHORT])
    stats = _empty_stats()

    await _extract_candidate(CID, stats, [])

    insights = cand.cv_extracted_data["_notes_insights"]
    assert stats["skipped_short"] == 1
    assert insights["_no_content"] is True
    assert "expected_rate" not in insights
    assert "rate" not in suggestions_from_notes(cand, include_rate=True)
    assert sync_world.stale == [CID]


@pytest.mark.asyncio
async def test_short_input_clears_the_column_written_from_the_send_note(sync_world):
    from app.tasks.notes_insights_sync import _empty_stats, _extract_candidate

    cand = _send_note_cand(
        column=Decimal("150.00"),
        rate_written={"amount": "150.00", "currency": "PLN", "version": 3},
    )
    db = sync_world(cand, notes=[SHORT])

    await _extract_candidate(CID, _empty_stats(), [])

    assert cand.expected_rate_hourly is None
    insights = cand.cv_extracted_data["_notes_insights"]
    assert "_rate_written" not in insights and "_rate_from_notes" not in insights
    assert [a.details["source"] for a in db.added] == ["notes_removed"]


@pytest.mark.asyncio
async def test_reading_without_a_rate_clears_the_column_from_the_send_note(
    sync_world,
):
    from app.tasks.notes_insights_sync import _empty_stats, _extract_candidate

    cand = _send_note_cand(
        column=Decimal("150.00"),
        rate_written={"amount": "150.00", "currency": "PLN", "version": 3},
    )
    db = sync_world(cand, notes=[LONG_TALK], parsed={"expected_rate": {"value": None}})
    touched: list[int] = []

    await _extract_candidate(CID, _empty_stats(), touched)

    assert cand.expected_rate_hourly is None
    assert "_rate_written" not in cand.cv_extracted_data["_notes_insights"]
    assert [a.details["source"] for a in db.added] == ["notes_removed"]
    assert touched == [CID]


@pytest.mark.asyncio
async def test_rate_typed_by_a_person_stays_even_when_it_matches_the_send_note(
    sync_world,
):
    from app.tasks.notes_insights_sync import _empty_stats, _extract_candidate

    # Bez `_rate_written` zgodnego z profilem — stawkę wpisał człowiek.
    cand = _send_note_cand(column=Decimal("150.00"), expected_value=None)
    db = sync_world(cand, notes=[LONG_TALK], parsed={"expected_rate": {"value": None}})

    await _extract_candidate(CID, _empty_stats(), [])

    assert cand.expected_rate_hourly == Decimal("150.00")
    assert db.added == []


@pytest.mark.asyncio
async def test_rate_still_in_the_input_notes_stays(sync_world):
    from app.tasks.notes_insights_sync import _empty_stats, _extract_candidate

    # 110 jest też w zwykłej notatce rekrutera — to nie tylko cena z wysyłki.
    cand = _send_note_cand(
        column=Decimal("110.00"),
        rate_written={"amount": "110.00", "currency": "PLN", "version": 3},
        expected_value=110,
    )
    db = sync_world(
        cand,
        notes=["Rozmowa: chce 110 zł/h na B2B, Kafka od 4 lat, projekt w banku."],
        parsed={"expected_rate": {"value": None}},
    )

    await _extract_candidate(CID, _empty_stats(), [])

    assert cand.expected_rate_hourly == Decimal("110.00")
    assert db.added == []


@pytest.mark.asyncio
async def test_stale_send_note_amounts_are_send_note_numbers_missing_from_input(
    send_ids,
):
    from app.services import notes_insights_extractor as extractor

    db = _Db([(1, TALK), (SEND_ID, f"<p>{SEND_NOTE}</p>")])

    amounts = await extractor.stale_send_note_amounts(
        db, 3, "[2026-09-22]\nchce 110 zł/h"
    )

    assert amounts == {Decimal("150"), Decimal("100")}
    assert send_ids == [[1, SEND_ID]]
    sql, params = db.calls[0]
    assert params == {"c": 3}
    assert note_kinds.facts_readable_sql() in sql
