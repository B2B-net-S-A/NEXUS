"""Ocena potencjału bez bazy: research bota, test KSC, odpowiedź modelu, baza wiedzy.

Nazwy firm i klientów są fikcyjne: repo i logi Actions są publiczne.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.services.sales import potential, potential_knowledge, signals
from app.services.sales.bot_tasks import potential as research
from app.services.sales.bot_tasks import signals_briefing
from app.services.sales.bot_tasks.base import TaskContext
from app.tasks import sales_signals as loop

TODAY = date(2026, 11, 23)


def _run(modes: dict[int, str], ids=(1, 2, 3)):
    run = signals.new_run(
        "briefing", list(ids), now=datetime.now(timezone.utc), modes=modes
    )[0]
    run.id = 501
    return run


def _item(ref: int, **over: Any) -> dict[str, Any]:
    base = {
        "company_ref": ref,
        "pkd": "21.20.z",
        "employees": "250-999 (2024)",
        "events": [
            {
                "date": "2026-03",
                "text": "Rozbudowa zakładu o nowe linie",
                "url": "example.com/rozbudowa",
                "line": "qa",
            }
        ],
        "jobs": [
            {
                "title": "Administrator systemów",
                "url": "https://example.com/praca",
                "published": (TODAY - timedelta(days=20)).isoformat(),
            }
        ],
        "stack": [{"text": "MES w zakładzie", "url": "https://example.com/mes"}],
    }
    return {**base, **over}


def _report(**over: Any) -> signals_briefing.BriefingReport:
    return signals_briefing.BriefingReport.model_validate({"checked_firms": 1, **over})


# ── Raport bota ──────────────────────────────────────────────────────────────


def test_research_report_has_no_people_fields_and_normalizes_pkd() -> None:
    item = _report(potential=[_item(1)]).potential[0]
    assert item.pkd == "21.20.Z"
    assert item.events[0].url == "https://example.com/rozbudowa"
    with pytest.raises(ValidationError):
        _report(potential=[_item(1, ceo="Jan Testowy")])
    # Zły element odpada sam, raport i reszta researchu zostają.
    event = _item(1)["events"][0]
    job = _item(1)["jobs"][0]
    bad = _report(
        potential=[
            _item(
                1,
                events=[{**event, "date": "marzec"}, event],
                jobs=[{**job, "published": ""}, {**job, "url": "javascript:alert(1)"}],
            )
        ]
    ).potential[0]
    assert len(bad.events) == 1 and len(bad.jobs) == 1
    assert bad.jobs[0].published is None
    odd_line = _report(potential=[_item(1, events=[{**event, "line": "sprzedaz"}])])
    assert odd_line.potential[0].events[0].line is None
    # Zły PKD nie blokuje raportu: test KSC po prostu się nie liczy.
    assert _report(potential=[_item(1, pkd="apteka")]).potential[0].pkd is None
    # Raport bez ``potential`` (punkty, haczyki) przechodzi jak dotąd.
    assert _report().potential == []


def test_plan_keeps_research_only_for_potential_firms_once_and_drops_stale_items() -> (
    None
):
    run = _run({1: "potential", 2: "meeting_prep", 3: "potential"})
    old_event = {**_item(1)["events"][0], "date": "2024-01-15"}
    future_event = {**_item(1)["events"][0], "date": "2027-02"}
    old_job = {**_item(1)["jobs"][0], "published": "2025-01-02"}
    items = _report(
        potential=[
            _item(
                1,
                events=[old_event, future_event, _item(1)["events"][0]],
                jobs=[old_job],
            ),
            _item(1),
            _item(2),
            _item(3),
            _item(9),
        ]
    ).potential
    rows, dropped = research.plan(run, items, today=TODAY)
    assert [row["company_id"] for row in rows] == [1, 3]
    assert dropped == 3
    first = rows[0]["payload"]
    assert first["state"] == "pending"
    assert [e["date"] for e in first["research"]["events"]] == ["2026-03"]
    assert first["research"]["jobs"] == []
    assert rows[0]["fingerprint"] != rows[1]["fingerprint"]


def test_potential_only_run_asks_for_research_and_leaves_points_empty() -> None:
    run = _run({1: "potential", 2: "potential"}, ids=(1, 2))
    ctx = TaskContext(
        firms=({"ref": 1, "mode": "potential"}, {"ref": 2, "mode": "potential"}),
        request={},
    )
    text = signals_briefing.BRIEFING.task_text(run, ctx)
    assert 'mode = "potential" (ref 1, 2)' in text
    assert "signals, briefings i hooks zostaw puste" in text
    assert "Nie otwieraj profili osób" in text
    assert "potential" in signals_briefing.BRIEFING.report_format()


@pytest.mark.asyncio
async def test_briefing_ingest_keeps_potential_firms_out_of_points(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    async def ingest(_db, run, report, *, now):
        seen["refs"] = [b.company_ref for b in report.briefings]
        seen["quiet"] = list(report.no_signal)
        return {"briefings": len(report.briefings), "dropped": {}}

    async def save(_db, run, rows, now, *, kind=None):
        seen["saved"] = (kind, [row["company_id"] for row in rows])
        return len(rows)

    monkeypatch.setattr(signals_briefing.signals, "ingest", ingest)
    monkeypatch.setattr(research, "save_results", save)
    run = _run({1: "potential", 2: "meeting_prep"}, ids=(1, 2))
    report = _report(
        briefings=[
            {"company_ref": 1, "points": [{"text": "Nie powinno wejść"}]},
            {"company_ref": 2, "points": [{"text": "Przed spotkaniem"}]},
        ],
        no_signal=[1],
        potential=[_item(1)],
    )
    summary = await signals_briefing.BRIEFING.ingest(
        None, run, report, datetime.now(timezone.utc)
    )
    assert seen == {"refs": [2], "quiet": [], "saved": ("potential", [1])}
    assert (summary["potential"], summary["potential_dropped"]) == (1, 0)
    assert (
        signals_briefing.BRIEFING.reply(
            {
                **summary,
                "leads": 0,
                "leads_new": 0,
                "dropped": {
                    "outside_window": [],
                    "nexus_clients": [],
                    "unknown_company": 0,
                    "duplicates": 0,
                },
            }
        )["potential"]
        == 1
    )


# ── Test KSC ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("pkd", "sizes", "result", "entity"),
    [
        ("21.20.Z", ("250-999",), "PRAWDOPODOBNIE TAK", "kluczowy"),
        ("21.20.Z", ("50-249",), "PRAWDOPODOBNIE TAK", "ważny"),
        ("27.32.Z", ("1000+",), "PRAWDOPODOBNIE TAK", "ważny"),
        ("27.32.Z", (None, "ok. 772 osoby (2022)"), "PRAWDOPODOBNIE TAK", "ważny"),
        ("21.20.Z", (None, ""), "MOŻLIWE", None),
        ("61.10.Z", ("1-49",), "MOŻLIWE", None),
        ("27.32.Z", ("1-49",), "PRAWDOPODOBNIE NIE", None),
        ("52.21.Z", ("250-999",), "PRAWDOPODOBNIE NIE", None),
    ],
)
def test_ksc_test_from_pkd_and_size(pkd, sizes, result, entity) -> None:
    out = potential.ksc_test(pkd, *sizes)
    assert (out["result"], out["entity"]) == (result, entity)
    assert "03.04.2027" in out["why"] or result == "PRAWDOPODOBNIE NIE"


def test_ksc_test_needs_pkd_and_longest_prefix_wins() -> None:
    assert potential.ksc_test(None, "1000+") is None
    # 52.22 (porty) jest w zał. I, a 52.21 nie.
    assert potential.ksc_test("52.22.A", "250-999")["entity"] == "kluczowy"
    assert potential.employees_floor("1 200 osób") == 1200


# ── Odpowiedź modelu ─────────────────────────────────────────────────────────


def _answer(**over: Any) -> str:
    base = {
        "verdict": "ŚREDNI",
        "summary": "Zakład w rozbudowie.",
        "land": {"title": "Diagnoza KSC", "why": "Termin 03.04.2027."},
        "expand": ["Pentest OT"],
        "fit": [
            {
                "line": "security",
                "score": 4,
                "need": "KSC",
                "service": "Diagnoza",
                "horizon": "teraz",
            },
            {
                "line": "security",
                "score": 1,
                "need": "",
                "service": "",
                "horizon": "teraz",
            },
            {
                "line": "elevate",
                "score": 9,
                "need": "",
                "service": "Access",
                "horizon": "3–6 mies.",
            },
            {
                "line": "marketing",
                "score": 5,
                "need": "",
                "service": "",
                "horizon": "teraz",
            },
        ],
        "references": [
            {"nr": "aaaa1111", "why": "Ta sama branża."},
            {"nr": "zmyslona", "why": "Nie ma jej w bazie."},
            {"nr": "aaaa1111", "why": "Drugi raz."},
        ],
        "questions": [{"group": "Bezpieczeństwo", "text": "Kto prowadzi KSC?"}],
        "verify": ["IT jest w centrali."],
        "risks": [],
        "opening": "Dzień dobry, …",
    }
    return json.dumps({**base, **over}, ensure_ascii=False)


def test_parse_assessment_keeps_only_known_references_and_lines() -> None:
    out = potential.parse_assessment(_answer(), {"aaaa1111", "bbbb2222"})
    assert out["references"] == [{"id": "aaaa1111", "why": "Ta sama branża."}]
    assert [(f["line"], f["score"]) for f in out["fit"]] == [
        ("elevate", 5),
        ("security", 4),
    ]
    assert out["land"]["title"] == "Diagnoza KSC"


def test_parse_assessment_refuses_broken_or_empty_answers() -> None:
    with pytest.raises(ValueError):
        potential.parse_assessment("to nie JSON", set())
    with pytest.raises(ValueError):
        potential.parse_assessment(_answer(summary="  "), set())
    with pytest.raises(ValueError):
        potential.parse_assessment(_answer(verdict="ŚWIETNY"), set())


# ── Baza wiedzy ──────────────────────────────────────────────────────────────

TABLE = """
| Klient | Sektor | Zakres | Współpraca od | Podpisał | Data listu |
|---|---|---|---|---|---|
| Bank Alfa | bankowość | body leasing IT | 2019 | Kierownik Testów | 28.05.2026 |
| Leasing Beta | leasing / finanse | testy | umowa z 21.11.2017 | Wicedyrektor IT | 03.06.2026 (ważny 12 mies.) |
| – | | | | | |
"""


def test_parse_table_reads_rows_dates_and_validity() -> None:
    refs = potential_knowledge.parse_table(TABLE)
    assert [r.client for r in refs] == ["Bank Alfa", "Leasing Beta"]
    assert refs[0].letter_date == date(2026, 5, 28) and refs[0].valid_until is None
    assert refs[1].valid_until == date(2027, 6, 3)
    assert refs[1].sectors == ["leasing", "finanse"]
    assert refs[1].since == "umowa z 21.11.2017"
    assert all(r.kind == "list" and r.id == "" for r in refs)
    assert potential_knowledge.parse_table("bez tabeli") == []
    assert potential_knowledge.parse_table("| Sektor |\n|---|\n| x |") == []


def test_name_variants_cover_brand_in_brackets_and_slashes() -> None:
    assert potential_knowledge.name_variants("Telko Alfa (Plus)") == [
        "Telko Alfa (Plus)",
        "Telko Alfa",
    ]
    assert potential_knowledge.name_variants("Biuro Beta / Gamma Info") == [
        "Biuro Beta / Gamma Info",
        "Biuro Beta",
        "Gamma Info",
    ]


def test_reference_ids_are_stable_and_unique() -> None:
    a = potential_knowledge.Reference(id="abcd1234", client="Alfa")
    b = potential_knowledge.Reference(id="abcd1234", client="Beta")
    c = potential_knowledge.Reference(client="Gamma")
    out = potential_knowledge._with_ids([a, b, c])
    assert out[0].id == "abcd1234"
    assert len({r.id for r in out}) == 3


def test_freshness_and_model_view_hide_signatures_and_notes() -> None:
    old = potential_knowledge.Reference(
        id="aaaa1111",
        client="Alfa",
        kind="list",
        letter_date=date(2024, 11, 8),
        signed_by="Jan Testowy",
        note="tylko dla nas",
    )
    valid = potential_knowledge.Reference(
        id="bbbb2222",
        client="Beta",
        kind="list",
        letter_date=date(2026, 6, 3),
        valid_until=date(2027, 6, 3),
    )
    logo = potential_knowledge.Reference(id="cccc3333", client="Gamma", kind="logo")
    assert potential_knowledge.is_fresh(old, TODAY) is False
    assert potential_knowledge.is_fresh(valid, TODAY) is True
    assert potential_knowledge.is_fresh(logo, TODAY) is None
    knowledge = potential_knowledge.Knowledge(
        offer="Oferta",
        references=[old, valid, logo],
        history=[],
        updated_at=None,
        updated_by=None,
    )
    view = potential_knowledge.for_model(knowledge, TODAY)
    dumped = json.dumps(view, ensure_ascii=False)
    assert "Jan Testowy" not in dumped and "tylko dla nas" not in dumped
    assert view["referencje"][0]["list_aktualny"] is False


def test_change_summary_counts_without_content() -> None:
    before = potential_knowledge.KnowledgeIn(
        offer="A",
        references=[potential_knowledge.Reference(id="aaaa1111", client="Alfa")],
    )
    after = potential_knowledge.KnowledgeIn(
        offer="B",
        references=[
            potential_knowledge.Reference(id="aaaa1111", client="Alfa", scope="testy"),
            potential_knowledge.Reference(id="bbbb2222", client="Beta"),
        ],
    )
    assert potential_knowledge.change_summary(before, after) == (
        "opis oferty, dodane referencje: 1, zmienione referencje: 1"
    )
    assert potential_knowledge.change_summary(before, before) == "bez zmian"


# ── Pętla: pierwsze spotkanie ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_meeting_goes_to_potential_and_others_keep_points(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    started: list = []

    async def knowledge(_db):
        return potential_knowledge.Knowledge(
            offer="Oferta", references=[], history=[], updated_at=None, updated_by=None
        )

    async def modes(_db, company_ids, **_k):
        return {3: "first_call", 4: "ongoing", 5: "first_call"}

    async def fresh(_db, ids, **_k):
        return {5}

    class _Run:
        status = "started"

    async def start(_db, kind, company_ids, **kwargs):
        started.append((list(company_ids), kwargs.get("modes")))
        return _Run()

    monkeypatch.setattr(loop.potential_knowledge, "load", knowledge)
    monkeypatch.setattr(loop.potential, "model_ready", lambda: True)
    monkeypatch.setattr(loop.targets, "modes_for", modes)
    monkeypatch.setattr(loop.potential, "fresh_company_ids", fresh)
    monkeypatch.setattr(loop.signals, "start_run", start)
    sent, rest = await loop._first_meetings_to_potential(
        AsyncMock(), [3, 4, 5], now=datetime.now(timezone.utc)
    )
    assert (sent, rest) == (1, [4])
    assert started == [([3], {3: "potential"})]
