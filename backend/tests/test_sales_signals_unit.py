"""Kanał sygnałów z bota researchu bez bazy: raport, token, plan przyjęcia, harmonogram."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.models.sales import SalesCompany, SalesSignalRun
from app.services.sales import client_gate
from app.services.sales import signals
from app.tasks import sales_signals as loop

NOW = datetime(2026, 11, 16, 7, 10, tzinfo=timezone.utc)


def _signal(**over):
    base = {
        "company_ref": 1,
        "type": "restructuring",
        "title": "Połączenie spółek",
        "summary": "Rejestracja w I kwartale",
        "why_now": "Integracja systemów",
        "url": "https://example.com/news/1",
        "published": "2026-11-01",
        "strength": "medium",
    }
    return {**base, **over}


def _report(**over) -> signals.RunReport:
    return signals.RunReport.model_validate({"checked_firms": 2, **over})


def _run(company_ids=(1, 2), **over) -> SalesSignalRun:
    run, _token = signals.new_run("signals", list(company_ids), now=NOW)
    run.id = 7
    for key, value in over.items():
        setattr(run, key, value)
    return run


COMPANIES = {
    1: signals.CompanyInfo(id=1, name="Firma A", owner_user_id=81),
    2: signals.CompanyInfo(id=2, name="Firma B", owner_user_id=None),
}


# ── raport ───────────────────────────────────────────────────────────────


def test_report_rejects_unknown_fields_so_no_person_data_gets_in() -> None:
    with pytest.raises(ValidationError):
        _report(signals=[_signal(contact_name="Osoba Testowa")])
    with pytest.raises(ValidationError):
        _report(people=[])


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,x", ""])
def test_report_accepts_only_http_sources(url: str) -> None:
    with pytest.raises(ValidationError):
        _report(signals=[_signal(url=url)])


def test_report_limits_signals_and_points() -> None:
    with pytest.raises(ValidationError):
        _report(signals=[_signal(url=f"https://e.com/{i}") for i in range(51)])
    with pytest.raises(ValidationError):
        _report(
            briefings=[
                {"company_ref": 1, "points": [{"text": f"p{i}"} for i in range(5)]}
            ]
        )
    with pytest.raises(ValidationError):
        _report(briefings=[{"company_ref": 1, "points": []}])


def test_report_strips_control_characters() -> None:
    report = _report(signals=[_signal(title="Nowy\x00 program\n\n  AI")])
    assert report.signals[0].title == "Nowy program AI"


def test_unknown_signal_type_and_strength_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _report(signals=[_signal(type="gossip")])
    with pytest.raises(ValidationError):
        _report(signals=[_signal(strength="huge")])


# ── token ────────────────────────────────────────────────────────────────


def test_token_works_once_for_its_run_until_expiry() -> None:
    run, token = signals.new_run("signals", [1], now=NOW)
    assert run.token_hash != token
    assert signals.token_matches(run, token, NOW + timedelta(minutes=5))
    assert not signals.token_matches(run, "x" + token, NOW)
    assert not signals.token_matches(run, None, NOW)
    assert not signals.token_matches(run, token, NOW + signals.TOKEN_TTL)
    run.status, run.token_hash = "received", None
    assert not signals.token_matches(run, token, NOW)


# ── plan przyjęcia ───────────────────────────────────────────────────────


def test_plan_creates_lead_with_score_owner_and_payload() -> None:
    plan = signals.plan_intake(
        _run(), _report(signals=[_signal()]), COMPANIES, {}, today=date(2026, 11, 16)
    )
    assert len(plan.leads) == 1
    lead = plan.leads[0]
    assert (lead["source"], lead["company_id"], lead["score"]) == ("research", 1, 60)
    assert lead["assignee_user_id"] == 81
    assert lead["fingerprint"] == signals.fingerprint(1, "https://example.com/news/1")
    assert lead["payload"] == {
        "origin": "grok",
        "run_id": 7,
        "type": "restructuring",
        "strength": "medium",
        "why_now": "Integracja systemów",
        "published": "2026-11-01",
        "domain": "example.com",
    }


def test_plan_drops_firm_outside_run_old_news_and_duplicates() -> None:
    report = _report(
        signals=[
            _signal(company_ref=3),  # spoza biegu
            _signal(published="2026-06-01"),  # starszy niż 120 dni
            _signal(published="2026-12-30"),  # z przyszłości
            _signal(),
            _signal(title="Ten sam link"),
        ]
    )
    plan = signals.plan_intake(_run(), report, COMPANIES, {}, today=date(2026, 11, 16))
    assert plan.unknown_company == 1
    assert [d["published"] for d in plan.outside_window] == ["2026-06-01", "2026-12-30"]
    assert (len(plan.leads), plan.duplicates) == (1, 1)


def test_plan_sends_client_signal_to_delivery_lead_not_to_leads() -> None:
    clients = {1: client_gate.ClientMatch(client_name="Klient A", delivery_lead="DL")}
    plan = signals.plan_intake(
        _run(),
        _report(signals=[_signal()]),
        COMPANIES,
        clients,
        today=date(2026, 11, 16),
    )
    assert plan.leads == []
    assert plan.nexus_clients == [
        {"company": "Firma A", "client": "Klient A", "delivery_lead": "DL"}
    ]


def test_plan_keeps_briefing_mode_from_run() -> None:
    run = _run(modes={"1": "ongoing"})
    report = _report(
        briefings=[
            {"company_ref": 1, "points": [{"text": "Nowy CTO", "url": "e.com/a"}]},
            {"company_ref": 2, "points": [{"text": "Raport roczny"}]},
            {"company_ref": 9, "points": [{"text": "Obca firma"}]},
        ]
    )
    plan = signals.plan_intake(run, report, COMPANIES, {}, today=date(2026, 11, 16))
    assert [(b["company_id"], b["mode"]) for b in plan.briefings] == [
        (1, "ongoing"),
        (2, "first_call"),
    ]
    assert plan.briefings[0]["points"][0]["url"] == "https://e.com/a"
    assert plan.unknown_company == 1


# ── webhook ──────────────────────────────────────────────────────────────


def test_webhook_body_carries_only_company_names_and_domains() -> None:
    run, token = signals.new_run("briefing", [1], now=NOW, modes={1: "first_call"})
    run.id = 11
    company = SalesCompany(id=1, name="Firma A", domain="firma-a.pl", nip="123")
    body = signals.webhook_body(
        run, token, [company], {"rejected": [], "seen_urls": []}
    )
    assert body["firms"] == [
        {"ref": 1, "name": "Firma A", "domain": "firma-a.pl", "mode": "first_call"}
    ]
    assert body["token"] == token and body["run_id"] == 11
    assert body["callback_url"].endswith("/api/integrations/sales-signals/runs/11")
    assert "nip" not in str(body["firms"])


# ── harmonogram pętli ────────────────────────────────────────────────────


class _Db:
    def __init__(self, last: dict[str, datetime | None]) -> None:
        self.last = last

    async def scalar(self, statement):
        text = str(statement.compile(compile_kwargs={"literal_binds": True}))
        return self.last["signals" if "'signals'" in text else "briefing"]


def _patch(monkeypatch, started: list) -> None:
    async def zero(*_a, **_k):
        return 0

    async def ids(*_a, **_k):
        return [1, 2]

    async def empty(*_a, **_k):
        return set()

    async def modes(_db, company_ids, **_k):
        return {cid: "first_call" for cid in company_ids}

    class _Run:
        status = "started"

    async def start(_db, kind, company_ids, **_k):
        started.append((kind, list(company_ids)))
        return _Run()

    monkeypatch.setattr(loop.signals, "expire_runs", zero)
    monkeypatch.setattr(loop.signals, "start_run", start)
    monkeypatch.setattr(loop.targets, "pilot_company_ids", ids)
    monkeypatch.setattr(loop.targets, "new_company_ids", ids)
    monkeypatch.setattr(loop.targets, "refresh_company_ids", ids)
    monkeypatch.setattr(loop.targets, "recently_sent", empty)
    monkeypatch.setattr(loop.targets, "modes_for", modes)


WARSAW = ZoneInfo("Europe/Warsaw")


@pytest.mark.asyncio
async def test_signals_run_starts_once_on_monday_morning(monkeypatch) -> None:
    started: list = []
    _patch(monkeypatch, started)
    monday = datetime(2026, 11, 16, 7, 5, tzinfo=WARSAW)
    hour_ago = monday.astimezone(timezone.utc) - timedelta(hours=2)
    db = _Db({"signals": None, "briefing": hour_ago})
    await loop.tick(db, now=monday.astimezone(timezone.utc), local=monday)
    assert ("signals", [1, 2]) in started

    started.clear()
    db = _Db({"signals": monday.astimezone(timezone.utc), "briefing": hour_ago})
    await loop.tick(db, now=monday.astimezone(timezone.utc), local=monday)
    assert all(kind != "signals" for kind, _ in started)


@pytest.mark.asyncio
async def test_no_signals_run_before_seven_or_on_tuesday(monkeypatch) -> None:
    started: list = []
    _patch(monkeypatch, started)
    for local in (
        datetime(2026, 11, 16, 6, 55, tzinfo=WARSAW),
        datetime(2026, 11, 17, 9, 0, tzinfo=WARSAW),
    ):
        db = _Db({"signals": None, "briefing": None})
        await loop.tick(db, now=local.astimezone(timezone.utc), local=local)
    assert all(kind != "signals" for kind, _ in started)


@pytest.mark.asyncio
async def test_briefing_runs_at_most_hourly(monkeypatch) -> None:
    started: list = []
    _patch(monkeypatch, started)
    local = datetime(2026, 11, 17, 10, 0, tzinfo=WARSAW)
    now = local.astimezone(timezone.utc)
    await loop.tick(
        _Db({"signals": None, "briefing": now - timedelta(minutes=20)}),
        now=now,
        local=local,
    )
    assert started == []
    await loop.tick(
        _Db({"signals": None, "briefing": now - timedelta(hours=2)}),
        now=now,
        local=local,
    )
    assert started == [("briefing", [1, 2])]


def test_feedback_sends_only_listed_reasons_never_free_text() -> None:
    rows = [
        (1, "Fuzja", "https://e.com/1", "dismissed", "Już wiemy"),
        (1, "Program", "https://e.com/2", "dismissed", "nie odbiera, tel. 600 100 200"),
        (2, "Nowy CTO", "https://e.com/3", "new", None),
    ]
    feedback = signals.feedback_from_rows(rows)
    assert feedback["rejected"] == [{"ref": 1, "title": "Fuzja", "reason": "Już wiemy"}]
    assert feedback["seen_urls"] == [
        "https://e.com/1",
        "https://e.com/2",
        "https://e.com/3",
    ]


@pytest.mark.parametrize("title", ["   ", "​", "\n\t"])
def test_title_empty_after_cleaning_is_a_422_not_a_500(title: str) -> None:
    with pytest.raises(ValidationError):
        _report(signals=[_signal(title=title)])


def test_bare_domain_longer_than_column_after_scheme_is_rejected() -> None:
    long_url = "e.com/" + "a" * 990  # 996 znaków, z „https://” ponad 1000
    with pytest.raises(ValidationError):
        _report(signals=[_signal(url=long_url)])


@pytest.mark.asyncio
async def test_failed_webhook_does_not_count_as_this_weeks_review(monkeypatch) -> None:
    started: list = []
    _patch(monkeypatch, started)

    class _Failed:
        status = "failed"

    async def start(_db, kind, company_ids, **_k):
        started.append((kind, list(company_ids)))
        return _Failed()

    monkeypatch.setattr(loop.signals, "start_run", start)
    monday = datetime(2026, 11, 16, 7, 5, tzinfo=WARSAW)
    now = monday.astimezone(timezone.utc)
    done = await loop.tick(
        _Db({"signals": None, "briefing": now}), now=now, local=monday
    )
    assert ("signals", [1, 2]) in started
    assert done["signals"] == 0
