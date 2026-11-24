"""Radar przepisów bez bazy: modele raportów, bramka, plany zapisu, terminy pętli."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import ValidationError

from app.services.law_radar import analyze, collect, gate, probes, runs
from app.tasks import law_radar as loop

WARSAW = ZoneInfo("Europe/Warsaw")


def _item(**over) -> dict:
    base = {
        "source": "sejm",
        "title": "Ustawa o zmianie ustawy o podatku od towarów i usług",
        "url": "https://api.sejm.gov.pl/eli/acts/DU/2026/473",
        "published": "2026-11-14",
        "act_ref": "DU/2026/473",
    }
    return {**base, **over}


def _change(**over) -> dict:
    base = {
        "title": "KSeF dla wszystkich",
        "summary": ["Faktury wyłącznie przez KSeF."],
        "roles": ["accounting"],
        "urgency": "now",
        "stage": "journal",
        "item_ids": [1],
    }
    return {**base, **over}


# ── Raport Zbieracza ─────────────────────────────────────────────────────


def test_collect_report_accepts_a_minimal_item_and_cleans_text() -> None:
    report = collect.CollectReport.model_validate(
        {
            "items": [
                _item(title="  Ustawa\n o VAT ", url="podatki.gov.pl/vat", quote="")
            ]
        }
    )
    item = report.items[0]
    assert item.title == "Ustawa o VAT"
    assert item.url == "https://podatki.gov.pl/vat"
    assert item.quote is None


@pytest.mark.parametrize(
    "over",
    [
        {"act_ref": "DU/26/473"},
        {"act_ref": "XX/2026/473"},
        {"act_ref": "DU/2026/473 "},
        {"print_no": "12a"},
        {"print_no": "123456"},
        {"url": "javascript:alert(1)"},
        {"url": "ftp://example.com/x"},
        {"source": "linkedin"},
        {"title": " \n "},
        {"title": "x" * 301},
        {"quote": "x" * 501},
        {"stage": "x" * 201},
        {"company": "Firma"},
    ],
)
def test_collect_report_refuses_bad_fields(over: dict) -> None:
    with pytest.raises(ValidationError):
        collect.CollectReport.model_validate({"items": [_item(**over)]})


def test_collect_report_limits_items_and_extra_keys() -> None:
    with pytest.raises(ValidationError):
        collect.CollectReport.model_validate({"items": [_item()] * 201})
    with pytest.raises(ValidationError):
        collect.CollectReport.model_validate({"items": [], "summary": "x"})
    assert collect.CollectReport.model_validate({}).items == []


def test_collect_plan_drops_repeats_inside_one_report() -> None:
    report = collect.CollectReport.model_validate(
        {
            "items": [
                _item(),
                _item(url="https://API.sejm.gov.pl/eli/acts/DU/2026/473/#x"),
                _item(source="lex", url="https://sip.lex.pl/akt/1", act_ref=None),
            ]
        }
    )
    rows, duplicates = collect.plan_items(report)
    assert duplicates == 1
    assert [row["klass"] for row in rows] == ["official", "lex"]
    assert all(row["gate"] == "pending" for row in rows)


def test_collect_task_tells_the_bot_about_lex_and_since() -> None:
    request = collect.build_request(date(2026, 11, 12))
    text = collect.task_text(request)
    assert "od 2026-11-12" in text
    assert "sip.lex.pl" in text
    assert "borg.wolterskluwer.pl" in text
    assert "logowanie.gofin.pl" in text
    assert "Nigdy nie zgaduj numerów" in text
    # Format przechodzi własny model: bot dostaje przykład, który NEXUS przyjmie.
    collect.CollectReport.model_validate(collect.report_format())
    assert set(request) == {"since", "topics", "sources", "max_items"}


# ── Raport Analityka ─────────────────────────────────────────────────────


def test_analyze_report_drops_unknown_probes_and_repeated_roles() -> None:
    report = analyze.AnalyzeReport.model_validate(
        {
            "changes": [
                _change(
                    roles=["accounting", "accounting", "board"],
                    probes=[
                        "ksef_sales_invoices",
                        "salary_of_ceo",
                        "ksef_sales_invoices",
                    ],
                )
            ]
        }
    )
    change = report.changes[0]
    assert change.roles == ["accounting", "board"]
    assert change.probes == ["ksef_sales_invoices"]
    analyze.AnalyzeReport.model_validate(analyze.report_format())


@pytest.mark.parametrize(
    "over",
    [
        {"summary": []},
        {"summary": ["a"] * 6},
        {"summary": ["x" * 301]},
        {"roles": []},
        {"roles": ["ceo"]},
        {"urgency": "later"},
        {"stage": "draft"},
        {"item_ids": []},
        {"item_ids": list(range(51))},
        {"title": "x" * 201},
        {"probes": ["a", "b", "c", "d", "e", "f"]},
        {"todo": [{"text": "Zrób", "role": "payroll"}] * 7},
        {"todo": [{"text": "Zrób", "role": "hr"}]},
        {"status": "done"},
    ],
)
def test_analyze_report_refuses_bad_fields(over: dict) -> None:
    with pytest.raises(ValidationError):
        analyze.AnalyzeReport.model_validate({"changes": [_change(**over)]})


def test_analyze_plan_keeps_only_items_and_changes_from_the_request() -> None:
    report = analyze.AnalyzeReport.model_validate(
        {
            "changes": [
                _change(item_ids=[1, 2, 99]),
                _change(change_ref=7, item_ids=[2, 3]),
                _change(change_ref=7, item_ids=[4]),
                _change(change_ref=8, item_ids=[5]),
                _change(item_ids=[98]),
            ]
        }
    )
    plan = analyze.plan_analysis(
        report, allowed_items={1, 2, 3, 4, 5}, open_changes={7}
    )
    assert [(p.change_ref, p.item_ids) for p in plan.changes] == [
        (None, [1, 2]),
        (7, [3]),
    ]
    assert plan.duplicate_change == 1
    assert plan.unknown_change == 1
    assert plan.no_items == 1
    assert plan.foreign_items == 2
    # Treść od bota nigdy nie niesie statusu ani decyzji.
    assert "status" not in plan.changes[0].values
    assert "decision_note" not in plan.changes[0].values


def test_new_todo_skips_tasks_the_change_already_has() -> None:
    todo = [
        {"text": "Sprawdzić KSeF", "role": "accounting"},
        {"text": "Nowe zadanie", "role": "board"},
        {"text": "nowe ZADANIE", "role": "board"},
    ]
    assert analyze.new_todo(["sprawdzić ksef"], todo) == [
        {"text": "Nowe zadanie", "role": "board"}
    ]


# ── Bramka ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "source,url,klass",
    [
        ("lex", "https://sip.lex.pl/akt/1", "lex"),
        ("lex", "https://isap.sejm.gov.pl/x", "lex"),
        ("sejm", "https://isap.sejm.gov.pl/isap.nsf/x", "official"),
        ("mf", "https://www.podatki.gov.pl/vat", "official"),
        ("other", "https://www.gov.pl/web/finanse", "official"),
        ("zus", "https://www.zus.pl/o-zus", "official"),
        ("eurlex", "https://eur-lex.europa.eu/eli/reg/2022/2554", "official"),
        ("advisor", "https://doradca.example.pl/alert", "practice"),
        ("gofin", "https://www.gofin.pl/podatki/17,2,8,1.html", "practice"),
        ("gofin", "https://www.podatki.gov.pl/vat", "official"),
        ("other", "https://gov.pl.evil.example/x", "practice"),
        ("other", "https://notgov.pl/x", "practice"),
        ("x", "https://x.com/MF_GOV_PL/status/1", "practice"),
    ],
)
def test_class_comes_from_source_and_host(source: str, url: str, klass: str) -> None:
    assert gate.classify(source, url) == klass


def test_fingerprint_ignores_case_fragment_and_trailing_slash() -> None:
    day = date(2026, 11, 14)
    a = gate.fingerprint("https://Sejm.gov.pl/druk/1/#top", None, "1", day)
    b = gate.fingerprint("https://sejm.gov.pl/druk/1", None, "1", day)
    assert a == b and len(a) == 64
    assert a != gate.fingerprint(
        "https://sejm.gov.pl/druk/1", None, "1", day + timedelta(1)
    )


def _sejm(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_gate_verifies_act_and_process_from_the_sejm_api() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/eli/acts/DU/2026/473":
            return httpx.Response(
                200,
                json={
                    "title": "Ustawa  o VAT",
                    "status": "obowiązujący",
                    "entryIntoForce": "2027-01-01",
                    "inForce": "NOT_IN_FORCE",
                },
            )
        if request.url.path == "/sejm/term10/processes/123":
            return httpx.Response(
                200,
                json={
                    "title": "Projekt",
                    "stages": [
                        {"stageName": "I czytanie", "date": "2026-10-01"},
                        {"stageName": "Przekazanie do Senatu", "date": "2026-11-10"},
                    ],
                },
            )
        return httpx.Response(404)

    async with _sejm(handler) as client:
        checker = gate.SejmChecker(client)
        act = await checker.check("DU/2026/473", None)
        process = await checker.check(None, "123")
        again = await checker.check("DU/2026/473", None)
    assert act.gate == "verified"
    assert act.official == {
        "act_title": "Ustawa o VAT",
        "act_status": "obowiązujący",
        "entry_into_force": "2027-01-01",
        "in_force": "NOT_IN_FORCE",
    }
    assert process.gate == "verified"
    assert process.official["official_stage"] == "Przekazanie do Senatu"
    assert process.official["official_stage_date"] == "2026-11-10"
    assert again == act
    assert seen.count("/eli/acts/DU/2026/473") == 1


@pytest.mark.asyncio
async def test_gate_rejects_numbers_the_api_does_not_know() -> None:
    async with _sejm(lambda request: httpx.Response(404)) as client:
        checker = gate.SejmChecker(client)
        act = await checker.check("MP/2026/9999", None)
        process = await checker.check(None, "77777")
    assert (act.gate, act.reason) == ("rejected", "act_missing")
    assert (process.gate, process.reason) == ("rejected", "print_missing")


@pytest.mark.asyncio
async def test_gate_keeps_items_without_number_or_after_network_error() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    async with _sejm(broken) as client:
        checker = gate.SejmChecker(client)
        no_ref = await checker.check(None, None)
        down = await checker.check("DU/2026/1", None)
    assert (no_ref.gate, no_ref.reason) == ("unverified", "no_ref")
    assert (down.gate, down.reason) == ("unverified", "network")
    assert checker.errors == 1

    async with _sejm(lambda request: httpx.Response(503)) as client:
        assert (
            await gate.SejmChecker(client).check("DU/2026/1", None)
        ).gate == "unverified"


@pytest.mark.asyncio
async def test_gate_stops_asking_after_the_lookup_limit() -> None:
    async with _sejm(
        lambda request: httpx.Response(200, json={"title": "Akt"})
    ) as client:
        checker = gate.SejmChecker(client, max_lookups=1)
        first = await checker.check("DU/2026/1", None)
        second = await checker.check("DU/2026/2", None)
    assert first.gate == "verified"
    assert (second.gate, second.reason) == ("unverified", "limit")
    assert checker.lookups == 1


# ── Bieg i webhook ───────────────────────────────────────────────────────


ENVELOPE_V2 = {"schema_version", "run_id", "request_url", "token", "expires_at"}


def test_collect_webhook_v2_is_only_the_envelope_and_get_has_the_order() -> None:
    now = datetime(2026, 11, 15, 5, 30, tzinfo=timezone.utc)
    request = collect.build_request(date(2026, 11, 12))
    run, token = runs.new_run("collect", request, now=now)
    run.id = 41
    body = runs.webhook_body(run, token)
    assert set(body) == ENVELOPE_V2
    assert body["schema_version"] == 2
    assert body["request_url"].endswith("/api/integrations/law-radar/runs/41")
    order = runs.request_body(run)
    assert {"task", "report_format", "request", "callback_url"} <= set(order)
    assert order["request"] == request and "token" not in order
    assert order["callback_url"] == body["request_url"]
    assert "reviewed_item_ids" not in order["report_format"]
    assert runs.hash_token(token) == run.token_hash
    assert runs.token_matches(run, token, now)
    assert not runs.token_matches(run, token, now + runs.TOKEN_TTL)
    assert not runs.token_matches(run, "zly", now)
    json.dumps(body)


def test_routine_listed_in_v1_fallback_gets_the_whole_order(monkeypatch) -> None:
    monkeypatch.setattr(runs.settings, "GROK_BOT_WEBHOOK_V1", "law_collect")
    now = datetime(2026, 11, 15, 5, 30, tzinfo=timezone.utc)
    run, token = runs.new_run(
        "collect", collect.build_request(date(2026, 11, 12)), now=now
    )
    run.id = 41
    body = runs.webhook_body(run, token)
    assert set(body) == {
        "schema_version",
        "run_id",
        "kind",
        "token",
        "expires_at",
        "callback_url",
        "task",
        "report_format",
        "request",
    }
    assert body["schema_version"] == 1
    assert "_schema_version" not in run.request
    assert not runs.uses_request_fetch(run)
    # Analityk dalej na v2: fallback obejmuje tylko wymienioną rutynę.
    analyze_run, _ = runs.new_run("analyze", {"items": []}, now=now)
    assert runs.uses_analyze_request_fetch(analyze_run)


def test_analyze_request_has_no_probe_numbers() -> None:
    request = analyze.build_request(
        [{"id": 1, "title": "Akt"}],
        [{"id": 2, "title": "Zmiana", "legal_ref": None}],
        topics=collect.PROFILE_TOPICS,
    )
    assert {probe["key"] for probe in request["probes"]} == set(probes.REGISTRY)
    assert all(set(probe) == {"key", "description"} for probe in request["probes"])
    assert "change_ref" in analyze.task_text(request)


def test_analyze_webhook_stays_small_as_the_request_grows() -> None:
    request = analyze.build_request(
        [{"id": i, "quote": "ą" * 500} for i in range(analyze.MAX_REQUEST_ITEMS)],
        [{"id": 2, "title": "Zmiana", "legal_ref": None}],
        topics=collect.PROFILE_TOPICS,
    )
    run, token = runs.new_run(
        "analyze", request, now=datetime(2026, 11, 17, 15, tzinfo=timezone.utc)
    )
    run.id = 42
    webhook = runs.webhook_body(run, token)
    assert len(json.dumps(webhook, ensure_ascii=False).encode()) < 1000
    assert webhook["schema_version"] == 2
    assert set(webhook) == ENVELOPE_V2
    full = runs.request_body(run)
    assert full["request"] == request
    assert full["callback_url"] == webhook["request_url"]
    assert "token" not in full
    analyze.AnalyzeReport.model_validate(full["report_format"])


# ── Sondy i terminy pętli ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "n,word",
    [(1, "umowa"), (2, "umowy"), (5, "umów"), (12, "umów"), (22, "umowy"), (0, "umów")],
)
def test_plural(n: int, word: str) -> None:
    assert probes.plural(n, "umowa", "umowy", "umów") == word


def test_probe_dates_follow_the_calendar() -> None:
    assert probes.months_back(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert probes.months_back(date(2026, 11, 15), 24) == date(2024, 11, 15)
    assert probes.next_year_start(date(2026, 12, 31)) == date(2027, 1, 1)
    assert probes.last_full_month(date(2026, 1, 15)) == (
        date(2025, 12, 1),
        date(2025, 12, 31),
    )


def test_collect_starts_once_a_day_from_half_past_five() -> None:
    early = datetime(2026, 11, 16, 5, 29, tzinfo=WARSAW)
    morning = datetime(2026, 11, 16, 5, 30, tzinfo=WARSAW)
    yesterday = datetime(2026, 11, 15, 22, 0, tzinfo=timezone.utc)
    today = datetime(2026, 11, 16, 4, 31, tzinfo=timezone.utc)
    assert not loop.collect_due(early, None)
    assert loop.collect_due(morning, None)
    assert loop.collect_due(morning, yesterday)
    assert not loop.collect_due(morning, today)


def test_probes_recompute_once_a_day_after_half_past_six() -> None:
    local = datetime(2026, 11, 16, 7, 0, tzinfo=WARSAW)
    before = datetime(2026, 11, 16, 5, 0, tzinfo=timezone.utc)
    after = datetime(2026, 11, 16, 5, 45, tzinfo=timezone.utc)
    assert not loop.probes_due(datetime(2026, 11, 16, 6, 0, tzinfo=WARSAW), before)
    assert loop.probes_due(local, before)
    assert not loop.probes_due(local, after)
    assert not loop.probes_due(local, None)


def test_collect_report_flags_skipped_lex_and_task_says_when() -> None:
    report = collect.CollectReport.model_validate({"items": [], "lex_skipped": True})
    assert report.lex_skipped is True
    assert collect.CollectReport.model_validate({"items": []}).lex_skipped is False
    text = collect.task_text(collect.build_request(date(2026, 11, 12)))
    assert "lex_skipped = true" in text
    assert collect.report_format()["lex_skipped"] is False
    assert "device_approval" in text
    with pytest.raises(ValidationError):
        collect.CollectReport.model_validate({"lex_skip_reason": "arbitrary pasted text"})


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.com\\.gov.pl/x",
        "https://evil.com\\@zus.pl/",
        "https://user@zus.pl/aktualnosci",
        "https://zus.pl.evil.com/",
    ],
)
def test_spoofed_host_is_never_official(url: str) -> None:
    assert gate.classify("other", url) == "practice"


@pytest.mark.parametrize("url", ["https://evil.com\\.gov.pl/x", "https://a@zus.pl/"])
def test_collect_report_refuses_backslash_and_userinfo_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        collect.CollectReport.model_validate(
            {
                "items": [
                    {
                        "source": "other",
                        "title": "T",
                        "url": url,
                        "published": "2026-11-14",
                    }
                ]
            }
        )


def test_real_official_hosts_stay_official() -> None:
    assert gate.classify("zus", "https://www.zus.pl/o-zus/aktualnosci") == "official"
    assert gate.classify("mf", "https://www.podatki.gov.pl/ksef/") == "official"


def test_report_examples_pair_act_numbers_with_their_real_titles() -> None:
    item = collect.report_format()["items"][0]
    assert item["act_ref"] == "DU/2026/473"
    assert "Inspekcji Pracy" in item["title"]
    change = analyze.report_format()["changes"][0]
    assert "PIP" in change["title"] and change["legal_ref"] == "Dz.U. 2026 poz. 473"
    analyze.AnalyzeReport.model_validate(analyze.report_format())
    collect.CollectReport.model_validate(collect.report_format())


def test_collect_accepts_gofin_and_flags_when_it_was_skipped() -> None:
    report = collect.CollectReport.model_validate(
        {
            "items": [
                _item(
                    source="gofin",
                    url="https://www.gofin.pl/podatki/17,2,8,1.html",
                    act_ref=None,
                )
            ],
            "gofin_skipped": False,
        }
    )
    assert report.items[0].source == "gofin"
    assert collect.CollectReport.model_validate({"items": []}).gofin_skipped is False
    assert (
        collect.CollectReport.model_validate(
            {"items": [], "gofin_skipped": True}
        ).gofin_skipped
        is True
    )
    text = collect.task_text(collect.build_request(date(2026, 11, 12)))
    assert "gofin_skipped = true" in text
    assert "source = gofin" in text
    assert "gofin" in collect.build_request(date(2026, 11, 12))["sources"]
    assert collect.report_format()["gofin_skipped"] is False


def test_source_check_is_rebuilt_only_when_it_does_not_know_gofin() -> None:
    from app.services.law_radar import schema

    (stmt,) = schema.CONSTRAINT_DDL
    assert "NOT LIKE '%gofin%'" in stmt
    assert "'gofin'" in schema.CK_ITEM_SOURCE
    assert stmt in schema.ALL_DDL
