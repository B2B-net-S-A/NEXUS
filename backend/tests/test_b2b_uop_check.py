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
    assert all(call["model"] == "claude-sonnet-5" for call in calls)
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
