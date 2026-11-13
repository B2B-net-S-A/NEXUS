"""„Warto wrócić” (G-E) i „Nowe centra IT” (G-D) bez bazy: raporty, plan, pętla."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.models.sales import SalesCompany
from app.services.sales import bot_tasks, client_gate, signals
from app.services.sales import signal_targets as targets
from app.services.sales.bot_tasks import discovery, winback
from app.tasks import sales_signals as loop

WARSAW = ZoneInfo("Europe/Warsaw")
NOW = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)
TODAY = date(2026, 11, 12)


# ── rejestr ──────────────────────────────────────────────────────────────


def test_both_kinds_are_registered_and_wait_for_the_flag(monkeypatch) -> None:
    assert bot_tasks.REGISTRY["winback"] is winback.WINBACK
    assert bot_tasks.REGISTRY["discovery"] is discovery.DISCOVERY
    assert winback.WINBACK.lead_feedback and winback.WINBACK.needs_firms
    assert not discovery.DISCOVERY.needs_firms
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", False)
    assert not bot_tasks.allowed_to_start("winback")
    assert not bot_tasks.allowed_to_start("discovery")
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    assert bot_tasks.allowed_to_start("winback")
    assert bot_tasks.allowed_to_start("discovery")


def test_neither_kind_takes_request_fields() -> None:
    for task in (winback.WINBACK, discovery.DISCOVERY):
        assert task.validate_request(None) == {}
        with pytest.raises(ValueError):
            task.validate_request({"lost_reason": "Cena za wysoka"})


def test_winback_webhook_sends_only_names_and_domains() -> None:
    run, token = signals.new_run("winback", [7], now=NOW)
    run.id = 11
    company = SalesCompany(id=7, name="Firma A", normalized_name="firma a")
    company.domain = "firma-a.pl"
    body = signals.webhook_body(
        run, token, [company], {"rejected": [], "seen_urls": []}
    )
    assert body["firms"] == [{"ref": 7, "name": "Firma A", "domain": "firma-a.pl"}]
    assert body["request"] == {}
    assert body["kind"] == "winback"
    assert "no_signal" in body["report_format"]
    text = json.dumps(body, ensure_ascii=False)
    for internal in targets.WINBACK_LOST_REASONS:
        assert internal not in text


def test_discovery_webhook_has_no_firms() -> None:
    run, token = signals.new_run("discovery", [], now=NOW)
    run.id = 12
    body = signals.webhook_body(run, token, [], {"rejected": [], "seen_urls": []})
    assert body["firms"] == [] and body["request"] == {}
    assert "items" in body["report_format"]
    assert str(discovery.MAX_ITEMS) in body["task"]


# ── „Warto wrócić”: raport i plan ────────────────────────────────────────


def _signal(ref: int = 7, **over) -> dict:
    base = {
        "company_ref": ref,
        "type": "program",
        "title": "Nowy program chmurowy",
        "summary": "Firma przenosi aplikacje do chmury",
        "why_now": "Program potrzebuje zespołu",
        "url": "https://example.com/news",
        "published": (TODAY - timedelta(days=10)).isoformat(),
        "strength": "medium",
    }
    return {**base, **over}


def _report(*items: dict) -> winback.WinbackReport:
    return winback.WinbackReport.model_validate(
        {"checked_firms": 3, "signals": list(items), "no_signal": []}
    )


def test_winback_report_is_signals_without_briefings() -> None:
    assert len(_report(_signal()).signals) == 1
    with pytest.raises(ValidationError):
        winback.WinbackReport.model_validate(
            {"checked_firms": 1, "signals": [], "briefings": []}
        )
    with pytest.raises(ValidationError):
        _report(_signal(url="javascript:alert(1)"))
    with pytest.raises(ValidationError):
        _report(_signal(contact="jan@example.com"))


def _deal(company_id: int = 7, owner: int | None = 30) -> targets.LostDeal:
    return targets.LostDeal(
        opportunity_id=500 + company_id,
        company_id=company_id,
        title="Wsparcie aplikacji",
        lost_reason="Klient zrezygnował z projektu",
        lost_at=datetime(2026, 4, 8, 10, 0, tzinfo=timezone.utc),
        owner_user_id=owner,
    )


def _companies(*owners: tuple[int, int | None]) -> dict[int, signals.CompanyInfo]:
    return {
        cid: signals.CompanyInfo(id=cid, name=f"Firma {cid}", owner_user_id=owner)
        for cid, owner in owners
    }


def _run(ids: list[int]):
    run, _token = signals.new_run("winback", ids, now=NOW)
    run.id = 21
    return run


def test_winback_plan_makes_a_lead_with_the_lost_deal() -> None:
    plan = winback.plan_intake(
        _run([7]),
        _report(_signal()),
        _companies((7, 10)),
        {7: _deal()},
        {},
        {10},
        today=TODAY,
    )
    [lead] = plan.leads
    assert lead["source"] == "research"
    assert lead["fingerprint"] == signals.fingerprint(7, "https://example.com/news")
    assert lead["assignee_user_id"] == 10
    assert lead["score"] == signals.STRENGTH_SCORE["medium"]
    payload = lead["payload"]
    assert payload["origin"] == "winback"
    assert payload["lost_opportunity_id"] == 507
    assert payload["lost_reason"] == "Klient zrezygnował z projektu"
    assert payload["lost_at"].startswith("2026-04-08")
    assert payload["why_now"] == "Program potrzebuje zespołu"


@pytest.mark.parametrize(
    ("company_owner", "deal_owner", "in_sales", "expected"),
    [
        (10, 30, {10, 30}, 10),  # opiekun firmy wygrywa
        (10, 30, {30}, 30),  # opiekun firmy odszedł ze Sprzedaży
        (None, 30, {30}, 30),
        (10, 30, set(), None),  # nikt nie pracuje w Sprzedaży: „Przejmij”
        (None, None, {10}, None),
    ],
)
def test_assignee_is_someone_in_sales(company_owner, deal_owner, in_sales, expected):
    assert winback.pick_assignee(company_owner, deal_owner, in_sales) == expected


def test_winback_plan_drops_what_should_not_become_a_lead() -> None:
    old = (TODAY - timedelta(days=signals.SIGNAL_WINDOW_DAYS + 1)).isoformat()
    report = _report(
        _signal(ref=99),  # spoza biegu
        _signal(ref=7, published=old),
        _signal(ref=8),  # klient NEXUSA
        _signal(ref=9),  # firma ma już otwartą szansę
        _signal(ref=7),
        _signal(ref=7),  # ten sam link drugi raz
    )
    plan = winback.plan_intake(
        _run([7, 8, 9]),
        report,
        _companies((7, None), (8, None), (9, None)),
        {7: _deal(7, owner=None), 8: _deal(8)},
        {8: client_gate.ClientMatch(client_name="Klient", delivery_lead=None)},
        set(),
        today=TODAY,
    )
    assert len(plan.leads) == 1
    assert plan.leads[0]["assignee_user_id"] is None
    assert (
        plan.unknown_company,
        plan.outside_window,
        plan.nexus_clients,
        plan.not_eligible,
        plan.duplicates,
    ) == (1, 1, 1, 1, 1)


def test_reply_to_the_bot_is_numbers_only() -> None:
    summary = {
        "leads": 2,
        "quiet": 3,
        "dropped": {"not_eligible": 1, "names": ["Firma"]},
        "names": ["Firma A"],
    }
    assert winback.WINBACK.reply(summary) == {
        "leads": 2,
        "quiet": 3,
        "dropped": {"not_eligible": 1},
    }


# ── „Warto wrócić”: kalendarz ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("day", "months", "expected"),
    [
        (date(2026, 11, 12), 14, date(2025, 9, 12)),
        (date(2026, 3, 31), 1, date(2026, 2, 28)),
        (date(2028, 3, 31), 1, date(2028, 2, 29)),
        (date(2026, 1, 15), 14, date(2024, 11, 15)),
    ],
)
def test_months_before(day, months, expected) -> None:
    assert targets.months_before(day, months) == expected


@pytest.mark.parametrize(
    ("local", "expected_day"),
    [
        (datetime(2026, 11, 12, 9, 0, tzinfo=WARSAW), 2),
        (datetime(2026, 12, 1, 9, 0, tzinfo=WARSAW), 7),
        (datetime(2027, 2, 3, 9, 0, tzinfo=WARSAW), 1),
    ],
)
def test_first_monday_start(local, expected_day) -> None:
    due = loop.first_monday_start(local)
    assert (due.day, due.hour, due.weekday()) == (expected_day, 7, 0)


class _Db:
    def __init__(self, last: dict[str, datetime | None]) -> None:
        self.last = last

    async def scalar(self, statement):
        text = str(statement.compile(compile_kwargs={"literal_binds": True}))
        for kind in ("winback", "discovery", "signals"):
            if f"'{kind}'" in text:
                return self.last.get(kind)
        return None  # punkty: bez firm do wysłania (``new_company_ids`` pusty)


def _patch(monkeypatch, started: list, *, flag: bool) -> None:
    async def zero(*_a, **_k):
        return 0

    async def nothing(*_a, **_k):
        return []

    async def winback_ids(*_a, **_k):
        return [4, 5]

    async def no_ids(*_a, **_k):
        return set()

    class _Run:
        status = "started"

    async def start(_db, kind, company_ids, **_k):
        started.append((kind, list(company_ids)))
        return _Run()

    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", flag)
    monkeypatch.setattr(loop.signals, "expire_runs", zero)
    monkeypatch.setattr(loop.signals, "start_run", start)
    monkeypatch.setattr(loop.targets, "pilot_company_ids", nothing)
    monkeypatch.setattr(loop.targets, "winback_company_ids", winback_ids)
    monkeypatch.setattr(loop.targets, "recently_sent", no_ids)
    monkeypatch.setattr(loop.targets, "new_company_ids", nothing)
    monkeypatch.setattr(loop.targets, "refresh_company_ids", nothing)

    async def no_dossier(*_a, **_k):
        return {}

    monkeypatch.setattr(loop.lead_dossier, "order", no_dossier)


@pytest.mark.asyncio
async def test_monthly_runs_start_from_the_first_monday_once(monkeypatch) -> None:
    started: list = []
    _patch(monkeypatch, started, flag=True)
    first_monday = datetime(2026, 11, 2, 7, 5, tzinfo=WARSAW)
    now = first_monday.astimezone(timezone.utc)
    done = await loop.tick(_Db({}), now=now, local=first_monday)
    assert ("winback", [4, 5]) in started and ("discovery", []) in started
    assert (done["winback"], done["discovery"]) == (2, 1)

    # Ten miesiąc już był: nic drugi raz, także kilka dni później.
    started.clear()
    later = datetime(2026, 11, 12, 9, 0, tzinfo=WARSAW)
    await loop.tick(
        _Db({"winback": now, "discovery": now}),
        now=later.astimezone(timezone.utc),
        local=later,
    )
    assert started == []

    # Bieg z poprzedniego miesiąca: nadrabia przy pierwszym obrocie po terminie.
    await loop.tick(
        _Db({"winback": now - timedelta(days=30), "discovery": None}),
        now=later.astimezone(timezone.utc),
        local=later,
    )
    assert {kind for kind, _ in started} == {"winback", "discovery"}


@pytest.mark.asyncio
async def test_no_monthly_runs_without_flag_or_before_the_first_monday(
    monkeypatch,
) -> None:
    started: list = []
    _patch(monkeypatch, started, flag=False)
    first_monday = datetime(2026, 11, 2, 7, 5, tzinfo=WARSAW)
    await loop.tick(
        _Db({}), now=first_monday.astimezone(timezone.utc), local=first_monday
    )
    assert started == []

    _patch(monkeypatch, started, flag=True)
    before = datetime(2026, 11, 2, 6, 55, tzinfo=WARSAW)
    await loop.tick(_Db({}), now=before.astimezone(timezone.utc), local=before)
    assert started == []


# ── „Nowe centra IT”: raport ─────────────────────────────────────────────


def _item(**over) -> dict:
    base = {
        "company": "Centrum Testowe Sp. z o.o.",
        "domain": "https://www.centrum-testowe.pl/kariera",
        "city": "Wrocław",
        "what": "Nowe centrum usług IT",
        "scale": "200 miejsc pracy",
        "why": "Buduje zespół od zera",
        "url": "gazeta.example.com/artykul",
        "published": (TODAY - timedelta(days=30)).isoformat(),
    }
    return {**base, **over}


def test_discovery_report_limits() -> None:
    report = discovery.DiscoveryReport.model_validate({"items": [_item()]})
    [item] = report.items
    assert item.url == "https://gazeta.example.com/artykul"
    assert discovery.clean_domain(item.domain) == "centrum-testowe.pl"
    with pytest.raises(ValidationError):
        discovery.DiscoveryReport.model_validate(
            {"items": [_item()] * (discovery.MAX_ITEMS + 1)}
        )
    with pytest.raises(ValidationError):
        discovery.DiscoveryReport.model_validate({"items": [_item(company="  ")]})
    with pytest.raises(ValidationError):
        discovery.DiscoveryReport.model_validate({"items": [_item(email="a@b.pl")]})
    with pytest.raises(ValidationError):
        discovery.DiscoveryReport.model_validate({"items": [_item(url="ftp://x")]})
    with pytest.raises(ValidationError):
        discovery.DiscoveryReport.model_validate({"items": [], "people": []})


def test_discovery_key_prefers_domain_then_canonical_name() -> None:
    with_domain = discovery.DiscoveryItem.model_validate(_item())
    assert discovery.result_key(with_domain) == "centrum-testowe.pl"
    gmail = discovery.DiscoveryItem.model_validate(_item(domain="gmail.com"))
    no_domain = discovery.DiscoveryItem.model_validate(_item(domain=None))
    assert discovery.result_key(gmail) == discovery.result_key(no_domain)
    assert discovery.result_key(no_domain) == "centrum testowe"


@pytest.mark.parametrize(
    ("days_ago", "inside"),
    [(0, True), (discovery.WINDOW_DAYS, True), (discovery.WINDOW_DAYS + 1, False)],
)
def test_discovery_window_is_six_months(days_ago, inside) -> None:
    assert discovery.in_window(TODAY - timedelta(days=days_ago), TODAY) is inside
    assert not discovery.in_window(TODAY + timedelta(days=2), TODAY)
