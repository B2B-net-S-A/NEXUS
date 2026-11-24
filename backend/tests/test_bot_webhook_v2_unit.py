"""Webhook v2 botów Grok (24.11.2026): koperta zamiast zlecenia, zapas v1, logi.

Przy paczkach 25–40 firm treść webhooka z całym zleceniem docierała do bota
ucięta (bieg 693), więc webhook niesie samą kopertę, a zlecenie leży pod GET.
Testy bez bazy; ścieżka z bazą i trasą GET jest w ``test_sales_bot_webhook_v2_api.py``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.models.sales import SalesCompany
from app.services import grok_webhook
from app.services.sales import signals
from app.services.sales.bot_tasks import people

NOW = datetime(2026, 11, 24, 16, 0, tzinfo=timezone.utc)
ENVELOPE = {"schema_version", "run_id", "request_url", "token", "expires_at"}


def _companies(count: int) -> list[SalesCompany]:
    return [
        SalesCompany(
            id=ref,
            name=f"Firma testowa {ref} sp. z o.o.",
            domain=f"firma-{ref}.example.pl",
            nip="5260250274",
            krs="0000012345",
        )
        for ref in range(1, count + 1)
    ]


def _briefing_run(count: int, mode: str = "first_call"):
    run, token = signals.new_run(
        "briefing",
        list(range(1, count + 1)),
        now=NOW,
        modes={ref: mode for ref in range(1, count + 1)},
    )
    run.id = 693
    return run, token


# ── Koperta i zlecenie ───────────────────────────────────────────────────


def test_v2_webhook_is_only_the_envelope_even_for_forty_firms() -> None:
    run, token = _briefing_run(40)
    body = signals.webhook_envelope(run, token)
    assert set(body) == ENVELOPE
    assert body["schema_version"] == 2
    assert body["request_url"].endswith("/api/integrations/sales-signals/runs/693")
    assert body["token"] == token
    assert body["expires_at"] == (NOW + signals.TOKEN_TTL).isoformat()
    assert len(grok_webhook.encode(body)) < 512


def test_order_has_task_format_request_firms_and_callback_but_no_token() -> None:
    run, token = _briefing_run(30)
    feedback = {"rejected": [], "seen_urls": ["https://e.com/1"]}
    order = signals.order_body(run, _companies(30), feedback)
    assert {"task", "report_format", "request", "firms", "callback_url"} <= set(order)
    assert len(order["firms"]) == 30
    assert order["callback_url"] == signals.webhook_envelope(run, token)["request_url"]
    assert order["seen_urls"] == ["https://e.com/1"]
    # Koniec polecenia (miejsce cięcia w biegu 693) jest w odpowiedzi GET w całości.
    assert order["task"].endswith("ze statusem received.")
    assert "Content-Type: application/json" in order["task"]
    assert token not in json.dumps(order)
    assert "schema_version" not in order


def test_v1_body_is_the_same_order_plus_token() -> None:
    run, token = _briefing_run(3)
    companies = _companies(3)
    body = signals.webhook_body(run, token, companies, dict(signals.NO_FEEDBACK))
    order = signals.order_body(run, companies, dict(signals.NO_FEEDBACK))
    assert body == {"schema_version": 1, **order, "token": token}


def test_feedback_keeps_the_most_recent_and_v1_limits_shorten_it() -> None:
    rows = [
        (1, f"Temat {i}", f"https://e.com/{i:03d}", "dismissed", "Już wiemy")
        for i in range(300)
    ]
    full = signals.feedback_from_rows(rows)
    assert (len(full["rejected"]), len(full["seen_urls"])) == (50, 200)
    short = signals.feedback_from_rows(
        rows,
        max_rejected=signals.V1_MAX_REJECTED,
        max_seen_urls=signals.V1_MAX_SEEN_URLS,
    )
    assert (len(short["rejected"]), len(short["seen_urls"])) == (20, 50)
    # Wiersze idą od ostatniej zmiany leada: zostają najświeższe linki.
    assert short["seen_urls"] == [f"https://e.com/{i:03d}" for i in range(50)]


@pytest.mark.asyncio
async def test_run_feedback_is_shorter_in_v1_and_skipped_for_hooks(monkeypatch) -> None:
    asked: list[dict[str, int]] = []

    async def feedback(_db, company_ids, **limits):
        asked.append(limits)
        return {"rejected": [], "seen_urls": []}

    monkeypatch.setattr(signals, "_feedback", feedback)
    run, _ = _briefing_run(3)
    await signals.run_feedback(None, run)
    await signals.run_feedback(None, run, schema=grok_webhook.V1)
    assert asked == [
        {},
        {
            "max_rejected": signals.V1_MAX_REJECTED,
            "max_seen_urls": signals.V1_MAX_SEEN_URLS,
        },
    ]
    hooks, _ = _briefing_run(3, mode="call_hook")
    assert await signals.run_feedback(None, hooks) == signals.NO_FEEDBACK
    assert len(asked) == 2


def test_package_request_keeps_only_its_own_first_meetings() -> None:
    assert signals._part_request({}, [1, 2]) == {}
    assert signals._part_request({"first_meeting": [1, 5, 12]}, [1, 2, 12]) == {
        "first_meeting": [1, 12]
    }


@pytest.mark.parametrize(
    ("setting", "routine", "expected"),
    [
        ("", "research", 2),
        ("research", "research", 1),
        (" Research , law_collect ", "research", 1),
        (" Research , law_collect ", "law_collect", 1),
        ("research", "law_analyze", 2),
    ],
)
def test_v1_fallback_names_routines(monkeypatch, setting, routine, expected) -> None:
    monkeypatch.setattr(settings, "GROK_BOT_WEBHOOK_V1", setting)
    assert grok_webhook.schema_for(routine) == expected


# ── Wysyłka: rozmiar treści i kod odpowiedzi w logu ──────────────────────


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _post(handler, body: dict[str, Any], caplog) -> grok_webhook.Outcome:
    caplog.set_level(logging.INFO, logger="app.services.grok_webhook")
    async with _client(handler) as client:
        return await grok_webhook.post(
            "https://bot.example/hook",
            "test-key",
            body,
            client=client,
            channel="sales",
            run_id=693,
            kind="briefing",
            routine="research",
        )


@pytest.mark.asyncio
async def test_post_sends_exactly_the_logged_bytes_and_logs_the_status(caplog) -> None:
    run, token = _briefing_run(1)
    body = signals.order_body(run, _companies(1), dict(signals.NO_FEEDBACK))
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["content"] = request.content
        seen["headers"] = request.headers
        return httpx.Response(202)

    outcome = await _post(handler, body, caplog)
    assert outcome == grok_webhook.Outcome(len(seen["content"]), 202)
    assert json.loads(seen["content"]) == body
    # Te same bajty, które httpx wysłałby z ``json=`` (polskie znaki bez \\u).
    assert seen["content"] == httpx.Request("POST", "https://x", json=body).content
    assert seen["headers"]["Content-Type"] == "application/json"
    assert seen["headers"]["Authorization"] == "Bearer test-key"
    [record] = [r for r in caplog.records if r.getMessage().startswith("bot_webhook")]
    assert f"bytes={outcome.sent_bytes} response=202" in record.getMessage()
    assert (record.event_kind, record.sent_bytes, record.response_status) == (
        "bot_webhook",
        outcome.sent_bytes,
        202,
    )
    assert token not in record.getMessage()


@pytest.mark.asyncio
async def test_post_reports_http_error_timeout_and_connection_error(caplog) -> None:
    body = {"schema_version": 2, "run_id": 1}
    failed = await _post(lambda request: httpx.Response(413), body, caplog)
    assert (failed.status_code, failed.error, failed.timed_out) == (
        413,
        "webhook HTTP 413",
        False,
    )

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    waited = await _post(slow, body, caplog)
    assert (waited.error, waited.timed_out) == (None, True)
    assert "response=timeout" in caplog.records[-1].getMessage()

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    lost = await _post(down, body, caplog)
    assert (lost.status_code, lost.error) == (None, "webhook ConnectError")


# ── Licznik punktów: puste ``briefings`` to 0 (bieg 560) ─────────────────


class _Db:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> None:
        self.statements.append(statement)


@pytest.mark.asyncio
async def test_empty_briefings_count_zero_and_no_news_rows_separately(
    monkeypatch,
) -> None:
    run, _ = _briefing_run(2, mode="ongoing")
    companies = {c.id: c for c in _companies(2)}

    async def rows(_db, ids):
        return {cid: companies[cid] for cid in ids}

    async def no_clients(_db, _identities):
        return {}

    monkeypatch.setattr(signals, "_companies", rows)
    monkeypatch.setattr(signals.client_gate, "match_companies", no_clients)
    report = signals.RunReport.model_validate(
        {"checked_firms": 2, "briefings": [], "no_signal": [1, 2]}
    )
    db = _Db()
    summary = await signals.ingest(db, run, report, now=NOW)
    assert (summary["briefings"], summary["briefings_no_news"]) == (0, 2)
    assert len(db.statements) == 2  # wiersze „nic nowego” dalej zapisane

    report = signals.RunReport.model_validate(
        {
            "checked_firms": 2,
            "briefings": [{"company_ref": 1, "points": [{"text": "Nowy program"}]}],
            "no_signal": [2],
        }
    )
    run, _ = _briefing_run(2, mode="ongoing")
    summary = await signals.ingest(_Db(), run, report, now=NOW)
    assert (summary["briefings"], summary["briefings_no_news"]) == (1, 1)


# ── Decydenci (Cognism): pusty raport ``not_processed`` ──────────────────


@pytest.mark.parametrize(
    "report",
    [
        {},
        {"firms": []},
        {"firms": None},
        {"status": "not_processed", "firms": []},
        {"status": "not_processed", "blocked_reason": "session_expired"},
        {"status": "", "blocked_reason": "null", "firms": []},
        {
            "firms": [
                {
                    "company_ref": 1,
                    "status": "not_processed",
                    "blocked_reason": "",
                    "company_name": "",
                    "company_domain": "",
                    "people": None,
                }
            ]
        },
        {
            "firms": [
                {"company_ref": 1, "status": "not_processed", "blocked_reason": "null"}
            ]
        },
        {
            "firms": [
                {
                    "company_ref": 1,
                    "status": "not_processed",
                    "blocked_reason": "rate_limited",
                }
            ]
        },
    ],
)
def test_cognism_accepts_an_empty_not_processed_report(report) -> None:
    parsed = people.CognismReport.model_validate(report)
    assert all(firm.status == "not_processed" for firm in parsed.firms)
    assert all(firm.blocked_reason is None for firm in parsed.firms)


@pytest.mark.parametrize(
    "report",
    [
        {"status": "done", "firms": []},
        {"firms": [], "people": []},
        {
            "firms": [
                {
                    "company_ref": 1,
                    "status": "matched",
                    "company_name": "",
                    "people": [],
                }
            ]
        },
        {"firms": [{"company_ref": 1, "status": "no_people", "company_name": "null"}]},
    ],
)
def test_cognism_still_refuses_unknown_fields_and_matches_without_employer(
    report,
) -> None:
    with pytest.raises(ValidationError):
        people.CognismReport.model_validate(report)


@pytest.mark.asyncio
async def test_run_level_blocked_reason_marks_every_unprocessed_firm(
    monkeypatch,
) -> None:
    run, _ = signals.new_run("people", [11, 12], now=NOW, request={"source": "cognism"})
    run.id = 598
    run.started_at = NOW - timedelta(minutes=5)

    class _Rows:
        def scalars(self) -> list[SalesCompany]:
            return []

    class _CognismDb:
        async def execute(self, _statement: Any) -> _Rows:
            return _Rows()

    async def no_clients(_db, _identities):
        return {}

    async def no_objections(_db, _ids):
        return set(), set(), set()

    monkeypatch.setattr(people.client_gate, "match_companies", no_clients)
    monkeypatch.setattr(people, "_cognism_objections", no_objections)
    report = people.CognismReport.model_validate(
        {"status": "not_processed", "blocked_reason": "session_expired"}
    )
    summary = await people.COGNISM.ingest(_CognismDb(), run, report, NOW)
    assert (summary["processed"], summary["not_processed"]) == (0, 2)
    assert summary["unprocessed_company_ids"] == [11, 12]
    assert summary["firm_issues"] == {"11": "session_expired", "12": "session_expired"}
