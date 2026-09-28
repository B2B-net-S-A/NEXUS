"""Regresje strukturalnej odpowiedzi AI dla analizy znamion UoP."""

from __future__ import annotations

import pytest

import app.services.b2b_contract_generator.uop_check as uop_check


def test_extract_json_accepts_fence_nested_issues_and_literal_newline():
    raw = """Oto wynik:
```json
{"issues":[{"phrase":"godziny pracy","why":"ryzyko","suggestion":"termin"}],"rewritten":"linia 1
linia 2","summary":"Wymaga zmiany."}
```
"""

    parsed = uop_check._extract_json(raw)

    assert parsed["issues"][0]["phrase"] == "godziny pracy"
    assert parsed["rewritten"] == "linia 1\nlinia 2"


def test_check_uop_retries_once_after_malformed_response(monkeypatch):
    calls: list[dict] = []
    responses = iter(
        [
            "odpowiedź bez JSON",
            '{"issues":[],"rewritten":"Samodzielna realizacja usług.",'
            '"summary":"Brak znamion UoP."}',
        ]
    )

    def fake_analyze(content, request_id, system=None, **kwargs):
        calls.append(
            {
                "content": content,
                "request_id": request_id,
                "model": kwargs.get("model_override"),
            }
        )
        return next(responses)

    monkeypatch.setattr(uop_check, "analyze_with_ai", fake_analyze)
    monkeypatch.delenv("UOP_CHECK_MODEL", raising=False)

    result = uop_check.check_employment_hallmarks("Samodzielne testowanie systemu.")

    assert result == {
        "ok": True,
        "issues": [],
        "rewritten": "Samodzielna realizacja usług.",
        "summary": "Brak znamion UoP.",
    }
    assert [call["request_id"] for call in calls] == ["uop-check", "uop-check-retry"]
    # F8 (decyzja 16.09.2026): znamiona UoP na GPT Luna.
    assert all(call["model"] == "gpt-6-luna" for call in calls)
    assert "POPRZEDNIA ODPOWIEDŹ" in calls[1]["content"]


def test_check_uop_uses_english_retry_instruction(monkeypatch):
    calls: list[str] = []
    responses = iter(
        [
            "invalid",
            '{"issues":[],"rewritten":"Independent services.","summary":"OK."}',
        ]
    )

    def fake_analyze(content, *args, **kwargs):
        calls.append(content)
        return next(responses)

    monkeypatch.setattr(uop_check, "analyze_with_ai", fake_analyze)

    result = uop_check.check_employment_hallmarks(
        "Independent software testing services.", language="en"
    )

    assert result["ok"] is True
    assert "PREVIOUS RESPONSE WAS NOT VALID JSON" in calls[1]
    assert "POPRZEDNIA ODPOWIEDŹ" not in calls[1]


def test_normalize_result_rejects_non_object_issue_items():
    with pytest.raises(ValueError, match="non-object"):
        uop_check._normalize_result({"issues": [None, "invalid"]}, "source")


def test_check_uop_raises_after_two_malformed_responses(monkeypatch):
    monkeypatch.setattr(uop_check, "analyze_with_ai", lambda *args, **kwargs: "invalid")

    with pytest.raises(ValueError, match="twice"):
        uop_check.check_employment_hallmarks("Praca od 9:00 do 17:00.")


@pytest.mark.parametrize("language", ["pl", "en"])
def test_prompt_pins_partner_wording_for_the_service_provider(monkeypatch, language):
    """Redakcja AI musi nazywać stronę świadczącą usługi „Partnerem" — spójnie z
    treścią umowy B2B (Załącznik nr 3). Bez tego pinu model wstawiał do „Opisu
    projektu i zakresu usług" „Wykonawcę"/„Konsultanta"."""
    captured: list[str] = []

    def fake_analyze(content, *args, **kwargs):
        captured.append(content)
        return '{"issues":[],"rewritten":"Partner świadczy usługi.","summary":"OK."}'

    monkeypatch.setattr(uop_check, "analyze_with_ai", fake_analyze)

    uop_check.check_employment_hallmarks(
        "Konsultant realizuje zadania w projekcie.", language=language
    )

    prompt = captured[0]
    # Prompt pinuje „Partnera" jako jedyne dozwolone określenie…
    assert "Partner" in prompt
    # …i jawnie wymienia terminy zakazane (żeby model nie wstawił ich do redakcji).
    for forbidden in ("Wykonawca", "Konsultant", "Zleceniobiorca"):
        assert forbidden in prompt


# ── Ticket 5: redakcja AI nie dopisuje warunków współpracy ───────────────────


def _fake_response(rewritten: str, suggestion: str = "") -> str:
    import json

    return json.dumps(
        {
            "issues": [
                {"phrase": "godziny pracy", "why": "ryzyko", "suggestion": suggestion}
            ],
            "rewritten": rewritten,
            "summary": "Wymaga zmiany.",
        },
        ensure_ascii=False,
    )


@pytest.mark.parametrize(
    "added",
    [
        "Partner samodzielnie realizuje usługi na rzecz Klienta.",
        "Partner raportuje postępy osobom wskazanym przez Klienta.",
        "Usługi są świadczone zdalnie lub w siedzibie Klienta.",
        "Partner ponosi odpowiedzialność za rezultat usług.",
        "Partner może korzystać z podwykonawców.",
    ],
)
def test_rewrite_drops_added_cooperation_terms(monkeypatch, added):
    """Zdanie z Ticketu 5 („Konsultant będzie samodzielnie realizował usługi na
    rzecz Klienta”) i jego rodzeństwo nie trafiają do opisu, gdy rekrutacja
    o nich nie mówiła — reszta redakcji zostaje."""
    source = "Projekt migracji systemu płatności. Praca w godzinach 9-17."
    rewritten = f"Projekt migracji systemu płatności. {added}"
    monkeypatch.setattr(
        uop_check,
        "analyze_with_ai",
        lambda *a, **k: _fake_response(rewritten, suggestion=added),
    )

    result = uop_check.check_employment_hallmarks(source)

    assert result["rewritten"] == "Projekt migracji systemu płatności."
    assert result["issues"][0]["suggestion"] == ""


def test_rewrite_keeps_terms_present_in_the_source(monkeypatch):
    """Określenie przepisane z rekrutacji nie jest dopiskiem — zostaje."""
    source = "Samodzielne testowanie aplikacji mobilnej w zespole QA."
    rewritten = "Samodzielne testowanie aplikacji mobilnej w zespole QA."
    monkeypatch.setattr(
        uop_check, "analyze_with_ai", lambda *a, **k: _fake_response(rewritten)
    )

    assert uop_check.check_employment_hallmarks(source)["rewritten"] == rewritten


def test_rewrite_drops_only_the_added_list_item(monkeypatch):
    source = "Zakres: analiza wymagań, testy regresji."
    rewritten = (
        "Zakres obejmuje analizę wymagań; testy regresji; raportowanie do Klienta."
    )
    monkeypatch.setattr(
        uop_check, "analyze_with_ai", lambda *a, **k: _fake_response(rewritten)
    )

    assert (
        uop_check.check_employment_hallmarks(source)["rewritten"]
        == "Zakres obejmuje analizę wymagań; testy regresji."
    )


def test_rewrite_emptied_by_the_guard_falls_back_to_the_source(monkeypatch):
    source = "Testy aplikacji mobilnej."
    monkeypatch.setattr(
        uop_check,
        "analyze_with_ai",
        lambda *a, **k: _fake_response(
            "Konsultant będzie samodzielnie realizował usługi na rzecz Klienta."
        ),
    )

    assert uop_check.check_employment_hallmarks(source)["rewritten"] == source


def test_sentence_split_keeps_versions_and_abbreviations_together():
    pieces = uop_check._split_sentences(
        "Wersja 5.x i .NET. Zakres m.in. testy.\nKoniec"
    )

    assert pieces == ["Wersja 5.x i .NET. ", "Zakres m.in. testy.\n", "Koniec"]
    assert "".join(pieces) == "Wersja 5.x i .NET. Zakres m.in. testy.\nKoniec"


@pytest.mark.parametrize("language", ["pl", "en"])
def test_prompt_forbids_adding_cooperation_terms(monkeypatch, language):
    captured: list[str] = []

    def fake_analyze(content, *args, **kwargs):
        captured.append(content)
        return '{"issues":[],"rewritten":"x","summary":"OK."}'

    monkeypatch.setattr(uop_check, "analyze_with_ai", fake_analyze)
    uop_check.check_employment_hallmarks("Testy aplikacji.", language=language)

    prompt = captured[0].lower()
    # Stary prompt kazał proponować „samodzielność, własną organizację czasu,
    # możliwość podwykonawstwa” — to jest źródło dopisków z Ticketu 5.
    assert "możliwość podwykonawstwa)" not in prompt
    assert "possibility of subcontracting)" not in prompt
    if language == "pl":
        assert "nie dodawaj" in prompt
    else:
        assert "do not add" in prompt
