"""Poprawki z przeglądu kodu asystenta prawnego (25.11.2026), bez bazy.

* zadania: wiersz po wypowiedzeniu i wiersz zgodności sortują się razem
  (strefy czasu), a „Pomiń” wycisza tylko jedno sprawdzenie zgodności;
* ``/redline/render`` sprawdza każdy cytat sam, bez ``state`` z przeglądarki;
* „Zatwierdzam” pisma modelu liczy daty i kwoty niepoliczone przez kod;
* liczebniki „-nastu”/„-dziestu” w okresie wypowiedzenia.
Dane fikcyjne.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.legal import tasks

# ── 1. zadania: daty ze strefą ──────────────────────────────────────────────


def _notice_row():
    contract = SimpleNamespace(
        id=10,
        client_id=5,
        candidate_id=77,
        agreement_termination_signed_on=date(2026, 11, 12),
        agreement_last_day=date(2026, 12, 31),
    )
    candidate = SimpleNamespace(name="Jan", lastname="Przykładowy")
    client = SimpleNamespace(name="Fikcyjny Bank", display_name=None)
    return tasks.notice_rows([(contract, candidate, client)])[0]


def _fit_row(checked_at: datetime):
    return tasks.LegalTaskRow(
        key="client_fit_gap:5:x",
        kind="client_fit_gap",
        severity="gap",
        title="t",
        detail="d",
        action_label="a",
        href="/x",
        client_id=5,
        contract_id=None,
        created_at=checked_at,
    )


def test_notice_task_time_is_timezone_aware_warsaw():
    row = _notice_row()
    assert row.created_at.tzinfo is not None
    assert row.created_at.utcoffset().total_seconds() == 3600  # listopad: CET


def test_merge_sorts_notice_and_client_fit_rows_together():
    notice = _notice_row()
    fit = _fit_row(datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc))
    merged = tasks.merge_rows([[notice], [fit]], closed=set())
    assert [r.kind for r in merged] == ["client_fit_gap", "notice_reply"]


def test_merge_tolerates_a_naive_row_from_an_old_provider():
    naive = _fit_row(datetime(2026, 11, 1, 12, 0))
    aware = _fit_row(datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc))
    aware = tasks.LegalTaskRow(**{**aware.__dict__, "key": "client_fit_gap:6:y"})
    merged = tasks.merge_rows([[naive], [aware]], closed=set())
    assert [r.key for r in merged] == ["client_fit_gap:6:y", "client_fit_gap:5:x"]


# ── 6. klucz zadania zgodności = jedno sprawdzenie ──────────────────────────


async def _fit_tasks(monkeypatch, checked_at: datetime):
    from app.services.legal_client_fit import service, task_provider

    finding = SimpleNamespace(
        state="gap", topic="ict_training", client_source_kind="framework", client_source_id=1
    )
    check = SimpleNamespace(checked_at=checked_at, requested_at=checked_at)
    client = SimpleNamespace(id=5, name="Fikcyjny Bank", display_name=None)

    async def _all(_user, _db):
        return None

    async def _counts(_db, _ids):
        return {5: 2}

    class _Db:
        async def execute(self, _statement):
            return SimpleNamespace(all=lambda: [(finding, check, client)])

    monkeypatch.setattr(task_provider, "resolve_delivery_lead_client_ids", _all)
    monkeypatch.setattr(task_provider, "visible_client_ids", lambda *_a: _all(None, None))
    monkeypatch.setattr(service, "active_b2b_contracts", _counts)
    return await task_provider.client_fit_tasks(_Db(), None)


@pytest.mark.asyncio
async def test_dismissed_fit_task_returns_after_a_new_check(monkeypatch):
    first = await _fit_tasks(monkeypatch, datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc))
    again = await _fit_tasks(monkeypatch, datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc))
    later = await _fit_tasks(monkeypatch, datetime(2026, 11, 24, 8, 0, tzinfo=timezone.utc))
    assert first[0].key.startswith("client_fit_gap:5:")
    assert first[0].key == again[0].key  # to samo sprawdzenie = ten sam klucz
    closed = {first[0].key}
    assert tasks.merge_rows([again], closed) == []
    assert [r.key for r in tasks.merge_rows([later], closed)] == [later[0].key]
    assert len(later[0].key) <= 160


# ── 3. /redline/render sprawdza każdy cytat sam ─────────────────────────────


def _render_changes(sources):
    return json.dumps(
        [
            {
                "id": "a1",
                "kind": "replace",
                "paragraph": 0,
                "find": "30 dni",
                "new_text": "14 dni",
                "reason": "Krótszy termin.",
                "sources": sources,
            }
        ]
    )


@pytest.mark.asyncio
async def test_recheck_blocks_invented_law_quote_without_state(monkeypatch):
    from app.api import legal_redline as api
    from app.services.legal import corpus

    async def no_provision(*_a, **_kw):
        return None

    monkeypatch.setattr(corpus, "get_provision", no_provision)
    items = api._parse_changes(
        _render_changes([{"ref": "art. 999 KC", "kind": "law", "quote": "zmyślony"}])
    )
    assert items[0].sources[0].state == "ok"  # domyślne z przeglądarki
    document = api.SourcePassage(kind="contract", ref="dokument", text="Termin 30 dni.")
    with pytest.raises(HTTPException) as exc:
        await api.recheck_changes(object(), items, document, contract=None)
    assert exc.value.status_code == 422 and "bez pokrycia" in exc.value.detail


@pytest.mark.asyncio
async def test_recheck_accepts_quote_found_in_the_corpus(monkeypatch):
    from app.api import legal_redline as api
    from app.services.legal import corpus

    hit = corpus.ProvisionHit(
        id=1, act_key="kc", act_short_name="KC", ref="art. 77 § 1", ref_key="77 §1",
        kind="paragraph", heading=None,
        text="Uzupełnienie lub zmiana umowy wymaga zachowania formy.",
        repealed=False, version_id=1, version_ident="x", valid_from=date(2026, 1, 1),
        valid_to=None, url="https://eli.gov.pl/x",
    )
    seen = {}

    async def provision(_db, act_key, ref, **_kw):
        seen["asked"] = (act_key, ref)
        return hit

    monkeypatch.setattr(corpus, "get_provision", provision)
    items = api._parse_changes(
        _render_changes(
            [
                {"ref": "kc art. 77 § 1", "kind": "law", "quote": "zmiana umowy wymaga zachowania formy", "state": "mismatch"},
                {"ref": "dokument", "kind": "contract", "quote": "Termin 30 dni"},
            ]
        )
    )
    document = api.SourcePassage(kind="contract", ref="dokument", text="Termin 30 dni.")
    checked = await api.recheck_changes(object(), items, document, contract=None)
    assert seen["asked"] == ("kc", "art. 77 § 1")
    assert [s.state for s in checked[0].sources] == ["ok", "ok"]


@pytest.mark.asyncio
async def test_recheck_blocks_source_kind_it_cannot_load(monkeypatch):
    from app.api import legal_redline as api

    items = api._parse_changes(
        _render_changes([{"ref": "II CSK 1/26", "kind": "case", "quote": "dowolny tekst", "state": "ok"}])
    )
    document = api.SourcePassage(kind="contract", ref="dokument", text="Termin 30 dni.")
    with pytest.raises(HTTPException) as exc:
        await api.recheck_changes(object(), items, document, contract=None)
    assert exc.value.status_code == 422


# ── 4. „Zatwierdzam” liczy daty i kwoty z tekstu ────────────────────────────


def _letter_ctx():
    from app.services.legal import letter_service

    contract = SimpleNamespace(
        id=1,
        client_id=5,
        candidate_id=77,
        agreement_termination_party="consultant",
        agreement_termination_mode="notice",
        agreement_termination_signed_on=date(2026, 11, 12),
        agreement_last_day=date(2026, 12, 31),
    )
    return letter_service.LetterContext(
        contract=contract,
        partner={"full_name": "Jan Przykładowy", "company": "Przykładowy IT"},
        female=False,
        contract_number="12/2026",
        signing_date=date(2026, 1, 5),
        client_name="Fikcyjny Bank",
        client_legal_name="Fikcyjny Bank S.A.",
        rule=None,
        rule_reason=None,
        rule_sources=(),
        rule_notes=(),
        notice_document=None,
    )


@pytest.fixture
def letter_review(monkeypatch):
    from app.services.legal import letter_service

    ctx = _letter_ctx()

    async def load(_db, _contract):
        return ctx

    async def no_checks(*_a, **_kw):
        return []

    monkeypatch.setattr(letter_service, "load_context", load)
    monkeypatch.setattr(letter_service, "verify_letter_text", no_checks)
    return ctx


def _client_letter(body: str) -> str:
    from app.services.legal import letter_service, letters

    ctx = _letter_ctx()
    return letters.compose_letter(
        place="Warszawa",
        on_date=date(2026, 11, 25),
        recipient=letter_service.client_recipient(ctx),
        subject=letter_service.subject_for("client_letter", ctx).capitalize(),
        body=body,
        signature="B2B.net S.A.",
    )


@pytest.mark.asyncio
async def test_review_flags_a_date_typed_into_the_model_letter(letter_review):
    from app.services.legal import letter_service

    request = letter_service.LetterRequest(kind="client_letter")
    text = _client_letter("Konsultant zakończy pracę 15.01.2027 i przekaże projekt w 14 dni.")
    review = await letter_service.review_text(None, letter_review.contract, request, text)
    assert review.approval.blocked
    assert any("15.01.2027" in issue for issue in review.issues)
    assert any("14 dni" in issue for issue in review.issues)


@pytest.mark.asyncio
async def test_review_does_not_flag_dates_written_by_code(letter_review):
    from app.services.legal import letter_service

    request = letter_service.LetterRequest(kind="client_letter")
    text = _client_letter("Konsultant pozostaje do dyspozycji zespołu projektu.")
    review = await letter_service.review_text(None, letter_review.contract, request, text)
    assert review.issues == []
    assert not review.approval.blocked


@pytest.mark.asyncio
async def test_approve_refuses_model_letter_with_a_typed_date(letter_review, monkeypatch):
    from app.api import contracts
    from app.api import legal_letters as api
    from tests.test_permissions_contracts_rules import FINANCE, _user

    async def all_clients(_user, _db):
        return None

    monkeypatch.setattr(contracts, "resolve_delivery_lead_client_ids", all_clients)
    monkeypatch.setattr(contracts, "resolve_delivery_lead_finance_client_ids", all_clients)

    class _Db:
        async def scalar(self, _statement, *_a, **_kw):
            return letter_review.contract

        async def commit(self):
            pytest.fail("zatwierdzone mimo daty od modelu")

    body = api.LetterTextIn(
        kind="client_letter", text=_client_letter("Ostatni dzień pracy: 15.01.2027.")
    )
    with pytest.raises(HTTPException) as blocked:
        await api.approve_contract_letter(
            contract_id=1, body=body, current_user=_user(FINANCE), db=_Db()
        )
    assert blocked.value.status_code == 409
    with pytest.raises(HTTPException) as docx:
        await api.contract_letter_docx(
            contract_id=1, body=body, current_user=_user(FINANCE), db=_Db()
        )
    assert docx.value.status_code == 409


# ── 5. liczebniki słowne w okresie wypowiedzenia ────────────────────────────


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("z zachowaniem czternastu dni okresu wypowiedzenia", ("days", 14)),
        ("z zachowaniem piętnastu dni okresu wypowiedzenia", ("days", 15)),
        ("z zachowaniem dwudziestu jeden dni okresu wypowiedzenia", ("days", 21)),
        ("z zachowaniem trzydziestu dni okresu wypowiedzenia", ("days", 30)),
        ("z zachowaniem trzydziestu (30) dni okresu wypowiedzenia", ("days", 30)),
        ("z zachowaniem 30 (trzydziestu) dni okresu wypowiedzenia", ("days", 30)),
        ("z zachowaniem dwunastu miesięcy okresu wypowiedzenia", ("months", 12)),
        ("z zachowaniem jednego miesiąca okresu wypowiedzenia", ("months", 1)),
        ("z zachowaniem trzech miesięcy okresu wypowiedzenia", ("months", 3)),
        ("z zachowaniem dwóch tygodni okresu wypowiedzenia", ("days", 14)),
    ],
)
def test_word_numbers_in_notice_period(sentence, expected):
    from app.services.contract_document_text import termination
    from app.services.contract_document_text.structure import fold

    assert termination._duration(fold(sentence)) == expected


def test_twelve_months_to_the_end_of_month_is_parsed():
    from app.services.contract_document_text.termination import (
        PERIOD_END_OF_MONTH,
        parse_termination,
    )

    text = (
        "§ 5\n1. Każda ze Stron może rozwiązać Umowę z zachowaniem dwunastu miesięcy "
        "okresu wypowiedzenia ze skutkiem na koniec miesiąca kalendarzowego.\n"
    )
    rule = parse_termination(text).rule
    assert (rule.period_kind, rule.period_months) == (PERIOD_END_OF_MONTH, 12)


def test_fourteen_days_is_parsed_from_the_whole_contract():
    from app.services.contract_document_text.termination import PERIOD_DAYS, parse_termination

    text = (
        "§ 5\n1. Każda ze Stron może rozwiązać Umowę z zachowaniem czternastu dni "
        "okresu wypowiedzenia.\n"
    )
    rule = parse_termination(text).rule
    assert (rule.period_kind, rule.period_days) == (PERIOD_DAYS, 14)
