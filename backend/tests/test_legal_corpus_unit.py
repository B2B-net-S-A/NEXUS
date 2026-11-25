"""Korpus prawa bez sieci i bazy: plan wersji z odpowiedzi API, różnice wersji,
termin sprawdzenia w pętli, asystent bez modelu.

Odpowiedzi API mają kształt z API ELI Sejmu i SPARQL CELLAR (25.11.2026),
wartości fikcyjne.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.services.legal import assistant, corpus, fetch
from app.services.legal.acts import ACT_KEYS, ACTS
from app.services.legal.citations import SourcePassage
from app.tasks import legal_corpus as loop

ACT = {
    "ELI": "DU/1999/1",
    "title": "Ustawa z dnia 1 kwietnia 1999 r. - Kodeks przykładowy.",
    "textHTML": True,
    "references": {
        "Inf. o tekście jednolitym": [{"id": "DU/2026/50"}, {"id": "DU/2025/900"}],
        "Akty zmieniające": [
            {"id": "DU/2026/70", "date": "2026-09-01"},
            {"id": "DU/2025/10", "date": "2025-01-01"},
        ],
    },
}
TJ_PDF = {
    "ELI": "DU/2026/50",
    "address": "WDU20260000050",
    "legalStatusDate": "2026-05-19",
    "promulgation": "2026-06-17",
    "textHTML": False,
    "texts": [
        {"fileName": "D20260050.pdf", "type": "O"},
        {"fileName": "D20260050L.pdf", "type": "T"},
    ],
}


def test_eli_plan_takes_pdf_of_consolidated_text_and_later_amendments() -> None:
    plan = fetch.eli_plan_from(ACT, TJ_PDF)
    assert plan.ident == "DU/2026/50"
    assert plan.format == "pdf"
    assert plan.download_url.endswith("/DU/2026/50/text/T/D20260050L.pdf")
    assert plan.valid_from == date(2026, 5, 19)
    assert plan.published_on == date(2026, 6, 17)
    assert (
        plan.url == "https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU20260000050"
    )
    assert plan.meta["amendments_after"] == [{"id": "DU/2026/70", "date": "2026-09-01"}]


def test_eli_plan_prefers_html_when_available() -> None:
    plan = fetch.eli_plan_from(ACT, {**TJ_PDF, "textHTML": True})
    assert plan.format == "html"
    assert plan.download_url.endswith("/DU/2026/50/text.html")


def test_eli_plan_without_texts_is_an_error() -> None:
    with pytest.raises(fetch.FetchError):
        fetch.eli_plan_from(ACT, {**TJ_PDF, "texts": []})


def test_newest_consolidated_text_is_chosen_by_year_and_position() -> None:
    assert sorted(["DU/2025/900", "DU/2026/50", "DU/2026/7"], key=fetch._eli_sort_key)[
        -1
    ] == ("DU/2026/50")


def test_latest_consolidated_version_from_sparql() -> None:
    bindings = [
        {"celex": {"value": "02024R1689-20240712"}},
        {"celex": {"value": "02024R1689-20260727"}},
        {"celex": {"value": "32024R1689"}},
    ]
    assert fetch.latest_consolidated(bindings) == (
        "02024R1689-20260727",
        date(2026, 7, 27),
    )
    assert fetch.latest_consolidated([]) is None


def test_diff_versions_lists_added_removed_changed() -> None:
    before = {"1": "a", "2": "b", "3": "c"}
    after = {"1": "a", "2": "B", "4": "d"}
    diff = corpus.diff_versions(before, after)
    assert diff["added"] == ["4"]
    assert diff["removed"] == ["3"]
    assert diff["changed"] == ["2"]
    assert diff["counts"] == {"added": 1, "removed": 1, "changed": 1}


def test_registry_has_the_sixteen_acts_of_the_plan() -> None:
    assert set(ACT_KEYS) == {
        "kc", "kp", "pr_aut", "pip", "min_wynagrodzenie", "zatory", "pit", "ksh",
        "kpc", "sus", "odo", "znk", "prawo_przedsiebiorcow", "rodo", "dora", "ai_act",
    }  # fmt: skip
    assert {spec.ident for spec in ACTS if spec.source == "eurlex"} == {
        "32016R0679",
        "32022R2554",
        "32024R1689",
    }


def test_loop_checks_new_and_stale_acts_and_retries_failures_sooner() -> None:
    now = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
    assert loop.due(None, None, now=now)
    assert not loop.due(now - timedelta(hours=1), "ok", now=now)
    assert loop.due(now - timedelta(hours=21), "ok", now=now)
    assert not loop.due(now - timedelta(hours=1), "failed", now=now)
    assert loop.due(now - timedelta(hours=3), "failed", now=now)


def test_ref_to_key_accepts_short_forms() -> None:
    assert corpus.ref_to_key("art. 61 § 1") == "61 §1"
    assert corpus.ref_to_key("61 § 1") == "61 §1"
    assert corpus.ref_to_key("art. 442¹") == "442^1"
    assert corpus._key_variants("6 ust.1") == ["6 ust.1", "6 §1"]
    assert corpus._ancestors("6 ust.1 lit.b") == ["6 ust.1", "6"]


def test_assistant_flags_dates_amounts_and_invented_tokens() -> None:
    issues = assistant.code_issues(
        "Umowa ustaje 31 grudnia, kara 5 000 zł, termin 14 dni, adres [ADRES].",
        {"[PARTNER]": "Jan Testowy"},
    )
    assert any("31 grudnia" in i for i in issues)
    assert any("5 000 zł" in i for i in issues)
    assert any("14 dni" in i for i in issues)
    assert any("[ADRES]" in i for i in issues)
    assert (
        assistant.code_issues(
            "Zgodnie z art. 61 § 1 KC [PARTNER] …", {"[PARTNER]": "x"}
        )
        == []
    )


def test_lawyer_threshold_labels() -> None:
    assert assistant.lawyer_triggers("Naliczyć karę umowną za opóźnienie") == [
        "kara umowna"
    ]
    assert assistant.lawyer_triggers(
        "rozwiązanie bez zachowania okresu wypowiedzenia"
    ) == ["rozwiązanie ze skutkiem natychmiastowym"]
    assert assistant.lawyer_triggers("Klient grozi sądem") == ["spór z klientem"]
    assert assistant.lawyer_triggers("zwykłe wypowiedzenie") == []


def test_licensed_sources_never_go_to_the_model() -> None:
    passages = [
        SourcePassage("law", "art. 1", "tekst", url="https://sip.lex.pl/akty/1"),
        SourcePassage("law", "art. 2", "tekst", url="https://www.gofin.pl/x"),
        SourcePassage(
            "law", "art. 3", "tekst", url="https://isap.sejm.gov.pl/x", act_key="kc"
        ),
        SourcePassage("contract", "§ 1", "   "),
    ]
    assert [p.ref for p in assistant.allowed_passages(passages)] == ["art. 3"]


@pytest.mark.asyncio
async def test_draft_without_provider_key_returns_sources_and_no_text(
    monkeypatch,
) -> None:
    from app.services import llm_providers

    monkeypatch.setattr(llm_providers, "api_key_configured", lambda _model: False)

    async def _no_search(*_a, **_k):
        return []

    monkeypatch.setattr(corpus, "search_provisions", _no_search)
    passage = SourcePassage("law", "art. 61 § 1", "§ 1. Tekst.", act_key="kc")
    result = await assistant.draft(
        None,  # type: ignore[arg-type] — bez modelu i bez wyszukiwania baza nie jest potrzebna
        kind="termination",
        instruction="Wypowiedzenie umowy B2B, kara umowna w § 7",
        passages=[passage],
        entities=[],
    )
    assert result.text == ""
    assert result.blocked is True
    assert result.passages == [passage]
    assert result.lawyer_review == ["kara umowna"]
    assert result.error and "Brak klucza" in result.error


@pytest.mark.asyncio
async def test_draft_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError):
        await assistant.draft(
            None,  # type: ignore[arg-type]
            kind="pozew",
            instruction="x",
            passages=[],
            entities=[],
        )
