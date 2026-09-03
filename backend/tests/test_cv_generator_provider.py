"""Polityka generatora CV na wspólnym kliencie (`cv_generator_b2b/provider.py`).

Następca `test_cv_generator_b2b_ai_client.py`. Tamten plik pilnował dwóch
rzeczy naraz: MECHANIZMÓW (łańcuch modeli, backoff, ucięcie, sklejanie bloków)
i WARTOŚCI strojonych pod ten produkt. Mechanizmy przeniosły się do
`call_claude` i mają własny plik — `test_claude_client_chain.py`. Tutaj zostaje
to, co jest decyzją generatora CV, plus mapowanie na jego typy błędów.

Mapa, żeby nikt nie uznał, że pokrycie spadło:

| dawny test | gdzie teraz |
|---|---|
| kaskada na przeciążeniu, dedup łańcucha | `test_claude_client_chain.py` |
| 4xx nie kaskaduje | `test_claude_client_chain.py` |
| ucięcie bez fallbacku | `test_claude_client_chain.py` |
| tekst gdy pierwszy blok to thinking | `test_claude_client_chain.py::test_text_of…` |
| brak bloku tekstowego → czysty błąd | `…::test_call_claude_text_rejects_an_empty_response` |
| śmieci w env nie wywalają wywołania | `…::test_env_number…` oraz test na dole tego pliku |
"""

from __future__ import annotations

import pytest

from app.services import claude_client
from app.services.cv_generator_b2b import provider
from app.services.cv_generator_b2b.provider import (
    CVGeneratorAIError,
    CVGeneratorOverloadedError,
    CVGeneratorTruncatedError,
    analyze_with_ai,
)


class _FakeErr(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class _FakeMessage:
    def __init__(self, text: str = "{}", stop_reason: str = "end_turn") -> None:
        self.content = [type("Block", (), {"text": text})()]
        self.stop_reason = stop_reason
        self.usage = type("U", (), {"input_tokens": 5, "output_tokens": 2})()


def _install(monkeypatch, side_effects):
    seen: list[dict] = []

    class _Msgs:
        def create(self, **kwargs):
            seen.append(kwargs)
            effect = side_effects[len(seen) - 1]
            if isinstance(effect, Exception):
                raise effect
            return effect

    class _Client:
        def __init__(self, **_kwargs) -> None:
            self.messages = _Msgs()

    monkeypatch.setattr(claude_client.anthropic, "Anthropic", _Client)
    monkeypatch.setattr(claude_client.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    return seen


@pytest.fixture(autouse=True)
def _declare_provider_calls():
    """Zadeklaruj wywołania AI na czas testów w tym pliku.

    Te testy podmieniają KLIENTA SDK, nie `call_claude` — więc realnie wchodzą
    w `_assert_declared`. Od 0270 CI biegnie z `AI_QUOTA_STRICT=true`, gdzie
    niezadeklarowane wywołanie rzuca `AIQuotaUngated`; bez tej deklaracji test
    padałby na bramce kwot zamiast sprawdzać to, po co istnieje (polityka
    ponowień, łańcuch modeli, telemetria zdrowia).

    Deklaracja, nie wyłączenie STRICT: dzięki temu testy przechodzą tą samą
    ścieżką, którą chodzi produkcja.
    """
    from datetime import date

    from app.models.ai_feature import AIFeatureKey
    from app.services.ai_quota import QuotaState, declared_call

    with declared_call(
        AIFeatureKey.scoring,
        user_id=None,
        state=QuotaState(used=1, limit=0, period_start=date(2026, 9, 1)),
    ):
        yield


# ── Łańcuch modeli z konfiguracji produktu ───────────────────────────────────


def test_default_chain_is_the_quality_pinned_pair(monkeypatch):
    """Sonnet 4.6 jest przypięty ZMIERZONĄ decyzją (rewert #628), nie
    przypadkiem. Test istnieje, żeby cicha zmiana domyślnej wartości nie
    przeszła jako sprzątanie."""
    monkeypatch.delenv("CV_B2B_MODEL", raising=False)
    monkeypatch.delenv("CV_B2B_FALLBACK_MODELS", raising=False)
    monkeypatch.setenv("CV_B2B_MAX_RETRIES", "1")
    seen = _install(monkeypatch, [_FakeErr(529), _FakeErr(529), _FakeMessage()])

    analyze_with_ai("dane", "req-1")

    assert [c["model"] for c in seen] == [
        "claude-sonnet-4-6",
        "claude-sonnet-4-6",
        "claude-opus-4-8",
    ]


def test_env_overrides_the_chain(monkeypatch):
    monkeypatch.setenv("CV_B2B_MODEL", "model-a")
    monkeypatch.setenv("CV_B2B_FALLBACK_MODELS", " model-b , model-a ,, model-c ")
    monkeypatch.setenv("CV_B2B_MAX_RETRIES", "0")
    seen = _install(monkeypatch, [_FakeErr(529), _FakeErr(529), _FakeMessage()])

    analyze_with_ai("dane", "req-2")

    # Duplikat `model-a` zwinięty, puste pozycje odsiane.
    assert [c["model"] for c in seen] == ["model-a", "model-b", "model-c"]


def test_empty_fallback_env_means_no_fallback(monkeypatch):
    """Pusty string to jawne „bez fallbacku", nie „użyj domyślnych"."""
    monkeypatch.setenv("CV_B2B_MODEL", "solo")
    monkeypatch.setenv("CV_B2B_FALLBACK_MODELS", "")
    monkeypatch.setenv("CV_B2B_MAX_RETRIES", "0")
    seen = _install(monkeypatch, [_FakeMessage()])

    analyze_with_ai("dane", "req-3")
    assert [c["model"] for c in seen] == ["solo"]


def test_model_override_does_not_inherit_the_cv_quality_pin(monkeypatch):
    """Analiza UoP i lint reguł to inne zadania niż generacja CV — nie mają
    dziedziczyć modelu przypiętego pod jakość CV, ale mają zachować wspólny
    łańcuch fallbacku."""
    monkeypatch.delenv("CV_B2B_MODEL", raising=False)
    monkeypatch.delenv("CV_B2B_FALLBACK_MODELS", raising=False)
    monkeypatch.setenv("CV_B2B_MAX_RETRIES", "0")
    seen = _install(monkeypatch, [_FakeMessage()])

    analyze_with_ai("tekst", "req-4", model_override="claude-haiku-4-5-20251001")

    assert seen[0]["model"] == "claude-haiku-4-5-20251001"


def test_empty_model_setting_refuses_before_touching_the_provider(monkeypatch):
    monkeypatch.setenv("CV_B2B_MODEL", "")
    called = _install(monkeypatch, [_FakeMessage()])
    with pytest.raises(CVGeneratorAIError):
        analyze_with_ai("dane", "req-5")
    assert called == []


# ── Mapowanie na typy błędów generatora ──────────────────────────────────────


def test_exhausted_chain_maps_to_a_retry_actionable_message(monkeypatch):
    """Operator ma zobaczyć „spróbuj za chwilę", nie surowy słownik błędu API."""
    monkeypatch.setenv("CV_B2B_MODEL", "a")
    monkeypatch.setenv("CV_B2B_FALLBACK_MODELS", "b")
    monkeypatch.setenv("CV_B2B_MAX_RETRIES", "0")
    _install(monkeypatch, [_FakeErr(529), _FakeErr(529)])

    with pytest.raises(CVGeneratorOverloadedError) as exc:
        analyze_with_ai("dane", "req-6")
    assert "przeciążona" in str(exc.value)


def test_overload_then_a_4xx_on_the_fallback_still_reads_as_overload(monkeypatch):
    """Krawędź warta testu: pierwszy model był PRZECIĄŻONY, więc warunek
    odwracalny nadal zachodzi — późniejsze ponowienie może trafić na
    odbudowany model podstawowy. Twardy błąd fallbacku nie może przykryć tej
    informacji komunikatem sugerującym złą konfigurację."""
    monkeypatch.setenv("CV_B2B_MODEL", "a")
    monkeypatch.setenv("CV_B2B_FALLBACK_MODELS", "b")
    monkeypatch.setenv("CV_B2B_MAX_RETRIES", "0")
    _install(monkeypatch, [_FakeErr(529), _FakeErr(400)])

    with pytest.raises(CVGeneratorOverloadedError):
        analyze_with_ai("dane", "req-7")


def test_truncation_maps_to_the_typed_error(monkeypatch):
    monkeypatch.setenv("CV_B2B_MODEL", "a")
    monkeypatch.setenv("CV_B2B_FALLBACK_MODELS", "")
    monkeypatch.setenv("CV_B2B_MAX_RETRIES", "0")
    _install(monkeypatch, [_FakeMessage('{"a":', stop_reason="max_tokens")])

    with pytest.raises(CVGeneratorTruncatedError):
        analyze_with_ai("dane", "req-8")


def test_a_4xx_maps_to_the_generic_error_not_overload(monkeypatch):
    """Błąd 4xx to konfiguracja, nie przeciążenie — mylny komunikat wysłałby
    operatora na ponawianie czegoś, co nigdy się nie uda."""
    monkeypatch.setenv("CV_B2B_MODEL", "a")
    monkeypatch.setenv("CV_B2B_FALLBACK_MODELS", "")
    monkeypatch.setenv("CV_B2B_MAX_RETRIES", "0")
    _install(monkeypatch, [_FakeErr(400)])

    with pytest.raises(CVGeneratorAIError) as exc:
        analyze_with_ai("dane", "req-9")
    assert not isinstance(exc.value, CVGeneratorOverloadedError)


def test_missing_api_key_refuses_before_touching_the_provider(monkeypatch):
    called = _install(monkeypatch, [_FakeMessage()])
    monkeypatch.setattr(provider, "_api_key", lambda: None)

    with pytest.raises(CVGeneratorAIError):
        analyze_with_ai("dane", "req-10")
    assert called == []


# ── Konfiguracja wywołania ───────────────────────────────────────────────────


def test_system_prompt_is_cached_because_instructions_are_static(monkeypatch):
    monkeypatch.setenv("CV_B2B_MODEL", "a")
    monkeypatch.setenv("CV_B2B_FALLBACK_MODELS", "")
    monkeypatch.setenv("CV_B2B_MAX_RETRIES", "0")
    seen = _install(monkeypatch, [_FakeMessage()])

    analyze_with_ai("dane", "req-11", system="instrukcje")

    assert seen[0]["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_thinking_is_pinned_off_and_can_be_restored_by_env(monkeypatch):
    """Pin ma znaczenie dopiero, gdy ktoś wybierze model Claude 5: tam adaptive
    thinking działa domyślnie, a jego tokeny wypychają JSON CV."""
    monkeypatch.setenv("CV_B2B_MODEL", "a")
    monkeypatch.setenv("CV_B2B_FALLBACK_MODELS", "")
    monkeypatch.setenv("CV_B2B_MAX_RETRIES", "0")
    seen = _install(monkeypatch, [_FakeMessage(), _FakeMessage()])

    monkeypatch.delenv("CV_B2B_THINKING", raising=False)
    analyze_with_ai("dane", "req-12")
    assert seen[0]["thinking"] == {"type": "disabled"}

    monkeypatch.setenv("CV_B2B_THINKING", "adaptive")
    analyze_with_ai("dane", "req-13")
    assert "thinking" not in seen[1]


@pytest.mark.parametrize("raw", ["", "   ", "nie-liczba"])
def test_an_operator_slip_in_env_does_not_crash_generation(monkeypatch, raw):
    """`CV_B2B_MAX_RETRIES=` w Coolify nie może kończyć się gołym 500."""
    monkeypatch.setenv("CV_B2B_MODEL", "a")
    monkeypatch.setenv("CV_B2B_FALLBACK_MODELS", "")
    monkeypatch.setenv("CV_B2B_MAX_RETRIES", raw)
    monkeypatch.setenv("CV_B2B_MAX_TOKENS", raw)
    seen = _install(monkeypatch, [_FakeMessage()])

    analyze_with_ai("dane", "req-14")
    assert seen[0]["max_tokens"] == 16384  # domyślna, nie wyjątek
