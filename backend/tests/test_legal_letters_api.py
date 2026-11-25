"""Pismo na kontrakcie i zadania asystenta (część F) — bramki, odmowy, Jarvis, bez bazy.

Pismo czyta treść podpisanej umowy (stawki), więc bramka jest ta sama co
pobranie dokumentu kontraktu: „Stawki i kwoty: podgląd”, a konto z rolą
Delivery Leada tylko u klienta z przypisania. Pełny werdykt dla 29 person:
``tests/data/authz_golden/legal_letters.json`` i ``legal_tasks.json``.
Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api import contracts
from app.api import legal_letters as api
from app.api import legal_tasks as tasks_api
from app.core.rate_limit import limiter
from app.models.contract import Contract
from app.services.jarvis import agent, prompt, tools
from app.services.jarvis.transport import ToolResponse
from app.services.jarvis.web import WEB_SAFE_TOOLS
from app.services.legal import citations, letter_service, letters, tasks
from app.services.request_semantics import is_read_only_http_request
from app.services.section_permissions import ProductSection
from tests.test_permissions_contracts_rules import (
    FINANCE,
    LEAD,
    RECRUITER,
    TCM,
    _everything_but,
    _gate_refusal,
    _holder,
    _portfolio,
    _route_id,
    _user,
)

ROUTES = (
    api.draft_contract_letter,
    api.contract_letter_docx,
    api.approve_contract_letter,
)


@pytest.mark.parametrize("endpoint", ROUTES, ids=_route_id)
async def test_letter_routes_require_the_amounts_view(endpoint) -> None:
    assert await _gate_refusal(endpoint, _holder("amounts_view")) is None
    refusal = await _gate_refusal(endpoint, _everything_but("amounts_view"))
    assert refusal["permission"] == "amounts_view"


def test_draft_and_docx_are_reads_approve_is_a_write() -> None:
    base = "/api/contracts/12/legal-letter"
    assert is_read_only_http_request("POST", f"{base}/draft")
    assert is_read_only_http_request("POST", f"{base}/docx")
    assert not is_read_only_http_request("POST", f"{base}/approve")
    assert not is_read_only_http_request("POST", "/api/legal/tasks/x/dismiss")


class _Db:
    def __init__(self, contract=None, rows=()):
        self.contract = contract
        self.rows = list(rows)
        self.commits = 0

    async def scalar(self, statement, *_args, **_kwargs):
        entity = statement.column_descriptions[0]["entity"]
        if entity is Contract:
            return self.contract
        raise AssertionError(f"nieoczekiwane zapytanie: {entity}")

    async def execute(self, _statement, *_args, **_kwargs):
        rows = self.rows
        return SimpleNamespace(all=lambda: rows)

    async def commit(self) -> None:
        self.commits += 1


def _contract(client_id: int = 5, **kw):
    values = dict(
        id=1,
        client_id=client_id,
        candidate_id=77,
        agreement_termination_party="consultant",
        agreement_termination_mode="notice",
        agreement_termination_signed_on=date(2026, 11, 12),
        agreement_last_day=date(2026, 12, 31),
    )
    values.update(kw)
    return SimpleNamespace(**values)


class _Reached(Exception):
    pass


@pytest.fixture
def portfolio(monkeypatch):
    monkeypatch.setattr(contracts, "resolve_delivery_lead_client_ids", _portfolio(5))
    monkeypatch.setattr(
        contracts, "resolve_delivery_lead_finance_client_ids", _portfolio(5)
    )
    monkeypatch.setattr(limiter, "enabled", False)


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


async def test_delivery_lead_drafts_only_at_an_assigned_client(
    portfolio, monkeypatch
) -> None:
    async def reached(*_args, **_kwargs):
        raise _Reached

    monkeypatch.setattr(letter_service, "build_letter", reached)
    body = api.LetterIn(kind="notice_reply")
    with pytest.raises(_Reached):
        await api.draft_contract_letter(
            request=_request(),
            contract_id=1,
            body=body,
            current_user=_user(LEAD),
            db=_Db(_contract(5)),
        )
    with pytest.raises(HTTPException) as denied:
        await api.draft_contract_letter(
            request=_request(),
            contract_id=1,
            body=body,
            current_user=_user(LEAD),
            db=_Db(_contract(6)),
        )
    assert denied.value.status_code in (403, 404)
    for user in (_user(FINANCE), _holder("amounts_view", role=TCM)):
        with pytest.raises(_Reached):
            await api.draft_contract_letter(
                request=_request(),
                contract_id=1,
                body=body,
                current_user=user,
                db=_Db(_contract(6)),
            )


async def test_unavailable_letter_is_422(portfolio, monkeypatch) -> None:
    async def unavailable(*_args, **_kwargs):
        raise letter_service.LetterUnavailable("Brak wypowiedzenia Partnera.")

    monkeypatch.setattr(letter_service, "build_letter", unavailable)
    with pytest.raises(HTTPException) as refused:
        await api.draft_contract_letter(
            request=_request(),
            contract_id=1,
            body=api.LetterIn(kind="notice_reply"),
            current_user=_user(FINANCE),
            db=_Db(_contract(5)),
        )
    assert refused.value.status_code == 422


def _review(statuses, *, warning=None, kind="notice_reply"):
    letter_kind = letters.KINDS_BY_KEY[kind]
    checks = [
        citations.CitationCheck(
            citations.extract("§ 8 ust. 2 umowy")[0], status, status, "test"
        )
        for status in statuses
    ]
    return letter_service.TextReview(
        letter_kind,
        "Szanowny Panie, zgodnie z § 8 ust. 2 umowy …",
        checks,
        warning,
        [],
        letters.approval_state(
            check_statuses=statuses, issues=[], warning=warning, has_text=True
        ),
    )


async def test_approve_refuses_a_letter_with_a_bad_citation(
    portfolio, monkeypatch
) -> None:
    closed: list[dict] = []

    async def review(*_args, **_kwargs):
        return _review(["ok", "mismatch"])

    async def close(_db, **kwargs):
        closed.append(kwargs)

    monkeypatch.setattr(letter_service, "review_text", review)
    monkeypatch.setattr(tasks, "close_task", close)
    db = _Db(_contract(5))
    with pytest.raises(HTTPException) as blocked:
        await api.approve_contract_letter(
            contract_id=1,
            body=api.LetterTextIn(kind="notice_reply", text="…"),
            current_user=_user(FINANCE),
            db=db,
        )
    assert blocked.value.status_code == 409
    assert "pokrycia" in blocked.value.detail["message"]
    assert closed == [] and db.commits == 0
    # DOCX zablokowanego pisma też nie powstaje.
    with pytest.raises(HTTPException) as docx:
        await api.contract_letter_docx(
            contract_id=1,
            body=api.LetterTextIn(kind="notice_reply", text="…"),
            current_user=_user(FINANCE),
            db=db,
        )
    assert docx.value.status_code == 409


async def test_approve_refuses_an_unanswered_form_question(
    portfolio, monkeypatch
) -> None:
    question = letters.form_warning("notice_reply", _strict_rule())

    async def review(*_args, **_kwargs):
        return _review(["ok"], warning=question)

    monkeypatch.setattr(letter_service, "review_text", review)
    with pytest.raises(HTTPException) as blocked:
        await api.approve_contract_letter(
            contract_id=1,
            body=api.LetterTextIn(kind="notice_reply", text="…"),
            current_user=_user(FINANCE),
            db=_Db(_contract(5)),
        )
    assert blocked.value.status_code == 409


def _strict_rule() -> letters.NoticeRule:
    return letters.NoticeRule(
        "from_next_month",
        1,
        None,
        forms=("written",),
        under_nullity=True,
        delivery=("post",),
    )


async def test_approved_reply_closes_the_notice_task(portfolio, monkeypatch) -> None:
    closed: list[dict] = []

    async def review(*_args, **_kwargs):
        return _review(["ok"])

    async def close(_db, **kwargs):
        closed.append(kwargs)

    monkeypatch.setattr(letter_service, "review_text", review)
    monkeypatch.setattr(tasks, "close_task", close)
    db = _Db(_contract(5))
    out = await api.approve_contract_letter(
        contract_id=1,
        body=api.LetterTextIn(kind="notice_reply", text="…", original_confirmed=True),
        current_user=_user(FINANCE),
        db=db,
    )
    assert out["approved"] is True
    assert out["task_key"] == "notice_reply:1:2026-11-12"
    assert closed[0]["status"] == "done" and closed[0]["letter_kind"] == "notice_reply"
    assert db.commits == 1
    # Pismo do klienta nie zamyka zadania po wypowiedzeniu.
    closed.clear()

    async def client_review(*_args, **_kwargs):
        return _review(["ok"], kind="client_letter")

    monkeypatch.setattr(letter_service, "review_text", client_review)
    out = await api.approve_contract_letter(
        contract_id=1,
        body=api.LetterTextIn(kind="client_letter", text="…"),
        current_user=_user(FINANCE),
        db=_Db(_contract(5)),
    )
    assert out["task_key"] is None and closed == []


# ── zadania asystenta ───────────────────────────────────────────────────────


def _row(contract_id, candidate_id, signed_on, client_id=5):
    contract = _contract(
        client_id,
        id=contract_id,
        candidate_id=candidate_id,
        agreement_termination_signed_on=signed_on,
    )
    candidate = SimpleNamespace(name="Jan", lastname=f"Przykładowy{candidate_id}")
    client = SimpleNamespace(name="Fikcyjny Bank", display_name=None)
    return contract, candidate, client


def test_one_task_per_notice_and_a_stable_key() -> None:
    rows = tasks.notice_rows(
        [
            _row(10, 77, date(2026, 11, 12)),
            # Kolejny projekt tej samej osoby na tej samej umowie — to samo wypowiedzenie.
            _row(11, 77, date(2026, 11, 12)),
            _row(12, 78, date(2026, 11, 20)),
        ]
    )
    assert [r.key for r in rows] == [
        "notice_reply:12:2026-11-20",
        "notice_reply:11:2026-11-12",
    ]
    first = rows[1]
    assert first.title == "Jan Przykładowy77: szkic odpowiedzi na wypowiedzenie czeka"
    assert first.href == "/contracts/11?pismo=notice_reply"
    assert "z 12.11.2026" in first.detail and "31.12.2026" in first.detail
    assert first.kind == "notice_reply" and first.severity == "info"


def test_merge_drops_closed_tasks_and_duplicates_between_providers() -> None:
    a = tasks.notice_rows([_row(10, 77, date(2026, 11, 12))])
    b = tasks.notice_rows([_row(12, 78, date(2026, 11, 20))])
    merged = tasks.merge_rows([a, a + b], closed=set())
    assert [r.key for r in merged] == [b[0].key, a[0].key]
    assert tasks.merge_rows([a, b], closed={a[0].key}) == b


@pytest.fixture
def task_scope(monkeypatch):
    monkeypatch.setattr(
        tasks, "resolve_delivery_lead_finance_client_ids", _portfolio(5)
    )


async def test_notice_tasks_follow_the_amounts_view_and_dl_portfolio(
    task_scope,
) -> None:
    rows = [
        _row(10, 77, date(2026, 11, 12), client_id=5),
        _row(12, 78, date(2026, 11, 20), client_id=6),
    ]
    lead = await tasks.notice_reply_tasks(_Db(rows=rows), _user(LEAD))
    assert [r.client_id for r in lead] == [5]
    finance = await tasks.notice_reply_tasks(_Db(rows=rows), _user(FINANCE))
    assert sorted(r.client_id for r in finance) == [5, 6]
    # Bez podglądu kwot — brak zadań (pismo i tak by odmówiło), nie 403.
    recruiter = await tasks.notice_reply_tasks(_Db(rows=rows), _user(RECRUITER))
    assert recruiter == []


async def test_dismiss_only_a_visible_task(monkeypatch) -> None:
    row = tasks.notice_rows([_row(10, 77, date(2026, 11, 12))])[0]
    closed: list[dict] = []

    async def collect(_db, _user):
        return [row]

    async def close(_db, **kwargs):
        closed.append(kwargs)

    monkeypatch.setattr(tasks, "collect", collect)
    monkeypatch.setattr(tasks, "close_task", close)
    db = _Db()
    with pytest.raises(HTTPException) as missing:
        await tasks_api.dismiss_legal_task(
            key="notice_reply:99:2026-11-12", current_user=_user(FINANCE), db=db
        )
    assert missing.value.status_code == 404 and closed == []
    out = await tasks_api.dismiss_legal_task(
        key=row.key, current_user=_user(FINANCE), db=db
    )
    assert out == {"dismissed": True, "key": row.key}
    assert closed[0]["status"] == "dismissed" and db.commits == 1
    listed = await tasks_api.legal_tasks(
        current_user=_user(FINANCE), contract_id=10, db=db
    )
    assert [i["key"] for i in listed["items"]] == [row.key]
    other = await tasks_api.legal_tasks(
        current_user=_user(FINANCE), contract_id=11, db=db
    )
    assert other == {"items": []}


# ── Jarvis: draft_legal_letter ──────────────────────────────────────────────


def test_jarvis_tool_is_a_link_behind_the_amounts_view() -> None:
    tool = tools.TOOLS_BY_NAME["draft_legal_letter"]
    assert tool.tier == tools.DRAFT_EMAIL.tier == "link"
    assert tool.section == ProductSection.delivery
    assert tool.any_permission == ("amounts_view",)
    assert "draft_legal_letter" not in WEB_SAFE_TOOLS
    sections = {ProductSection.delivery: 1}
    assert tool in tools.tools_for_user(sections, permissions={"amounts_view"})
    assert tool not in tools.tools_for_user(sections, permissions={"delivery_view"})


class _Transport:
    def __init__(self, response: ToolResponse):
        self.response = response
        self.calls: list = []

    async def call(self, spec):
        self.calls.append(spec)
        return self.response


async def test_jarvis_draft_card_says_nothing_was_sent() -> None:
    transport = _Transport(
        ToolResponse(
            200,
            {
                "label": "Odpowiedź na wypowiedzenie Partnera",
                "subject": "potwierdzenie wypowiedzenia umowy",
                "text": "Warszawa, 25 listopada 2026 r.\n\nTreść.",
                "blocked": False,
                "block_reasons": [],
                "lawyer_review": [],
                "counts": {"ok": 2, "missing": 0, "mismatch": 0},
            },
        )
    )
    events: list[dict] = []
    result = await agent._draft_legal_letter(
        transport,
        {"contract_id": 12, "kind": "notice_reply", "instruction": "krótko"},
        "use-1",
        events,
    )
    spec = transport.calls[0]
    assert (spec.method, spec.path) == ("POST", "/api/contracts/12/legal-letter/draft")
    # Od modelu tylko rodzaj i prośba — dane osoby liczy serwer.
    assert spec.json == {"kind": "notice_reply", "instruction": "krótko"}
    assert events[0]["type"] == "legal_letter"
    assert events[0]["letter"]["contract_id"] == 12
    assert events[0]["letter"]["counts"] == {"ok": 2, "missing": 0, "mismatch": 0}
    assert "nic nie wysłano" in result["content"]
    assert "Nie powtarzaj" in result["content"]


async def test_jarvis_draft_refusal_is_an_error_without_card() -> None:
    transport = _Transport(ToolResponse(403, {"detail": "Brak uprawnienia"}))
    events: list[dict] = []
    result = await agent._draft_legal_letter(
        transport, {"contract_id": 12, "kind": "notice_reply"}, "use-2", events
    )
    assert events == []
    assert result.get("is_error") is True
    bad = await agent._draft_legal_letter(transport, {"kind": "x"}, "use-3", events)
    assert bad.get("is_error") is True and len(transport.calls) == 1


def test_jarvis_prompt_sends_letters_to_the_tool() -> None:
    umowy = prompt.SYSTEM_PROMPT.split("UMOWY", 1)[1].split("PAMIĘĆ", 1)[0]
    assert "draft_legal_letter" in umowy
    assert "nie pisz pisma sam" in umowy
