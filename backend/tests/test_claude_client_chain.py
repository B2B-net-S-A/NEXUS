"""Zachowania wchłonięte do `call_claude` z `cv_generator_b2b/ai_client.py`.

Ten plik jest DOWODEM, że kasacja drugiego stosu dostawcy niczego nie zgubiła.
Do 0270 łańcuch modeli, cache promptu, wykrywanie ucięcia i odporność na
śmieci w env-ach żyły wyłącznie w kliencie generatora CV — czyli w miejscu,
którego bramka kwot, telemetria zdrowia i detektor niezadeklarowanych wywołań
w ogóle nie oglądały. Każde z tych zachowań ma tu własny test, zanim tamten
plik zniknie.

Trzy własności są tu pilnowane, bo ich naruszenie byłoby regresem cichym:

* pojedynczy model dalej re-raise'uje SUROWY wyjątek SDK (na tym stoi obsługa
  błędów dziesięciu wołających),
* ucięcie odpowiedzi domyślnie NIE rzuca (trzy ścieżki mają własną naprawę
  uciętego JSON-a i ona dziś działa),
* ucięcie liczy się jako sukces dostawcy i zużyte tokeny (wywołanie wróciło
  i zostało opłacone).
"""

from __future__ import annotations

import pytest

from app.models.ai_feature import AIFeatureKey
from app.services import ai_health, claude_client
from app.services.claude_client import (
    ClaudeError,
    ClaudeOverloaded,
    ClaudeTruncated,
    call_claude,
    call_claude_text,
    env_number,
    text_of,
)


class _FakeErr(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class _Usage:
    def __init__(self, i: int = 11, o: int = 7) -> None:
        self.input_tokens = i
        self.output_tokens = o


class _FakeMessage:
    def __init__(self, text: str = "ok", stop_reason: str | None = "end_turn") -> None:
        self.content = [type("Block", (), {"text": text})()]
        self.stop_reason = stop_reason
        self.usage = _Usage()


def _install(monkeypatch, side_effects):
    """Podmień klienta SDK; zwróć log wywołań (model + kwargs per próba)."""
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
    return seen


# ── Łańcuch modeli ───────────────────────────────────────────────────────────


def test_overloaded_primary_falls_back_to_the_next_model(monkeypatch):
    """Przeciążenie (529) jest per-PULA modelu, więc zejście na inną rodzinę
    ratuje generację zamiast wywalać ją w całości."""
    seen = _install(
        monkeypatch, [_FakeErr(529), _FakeErr(529), _FakeMessage("z opusa")]
    )
    message = call_claude(
        messages=[{"role": "user", "content": "x"}],
        model="claude-sonnet-4-6",
        max_tokens=64,
        api_key="k",
        max_retries=1,
        fallback_models=["claude-opus-4-8"],
    )
    assert text_of(message) == "z opusa"
    assert [c["model"] for c in seen] == [
        "claude-sonnet-4-6",
        "claude-sonnet-4-6",
        "claude-opus-4-8",
    ]


def test_a_4xx_does_not_cascade_to_the_fallback(monkeypatch):
    """Zły klucz albo zła nazwa modelu — każdy kolejny odrzuci to tak samo.
    Kaskada tylko maskowałaby błąd konfiguracji wolniejszym fallbackiem."""
    seen = _install(monkeypatch, [_FakeErr(400), _FakeMessage("nigdy")])
    with pytest.raises(_FakeErr):
        call_claude(
            messages=[{"role": "user", "content": "x"}],
            model="a",
            max_tokens=64,
            api_key="k",
            max_retries=0,
            fallback_models=["b"],
        )
    assert [c["model"] for c in seen] == ["a"]


def test_exhausted_chain_raises_the_clean_overload_error(monkeypatch):
    _install(monkeypatch, [_FakeErr(529), _FakeErr(529)])
    with pytest.raises(ClaudeOverloaded):
        call_claude(
            messages=[{"role": "user", "content": "x"}],
            model="a",
            max_tokens=64,
            api_key="k",
            max_retries=0,
            fallback_models=["b"],
        )


def test_single_model_still_reraises_the_raw_sdk_error(monkeypatch):
    """KONTRAKT ZGODNOŚCI. Dziesięciu wołających mapuje surowe typy SDK na
    własne kody błędów, a dwa testy w `test_claude_client.py` tego pilnują.
    Podmiana na własny typ przy braku fallbacku byłaby zmianą zrywającą
    przebraną za sprzątanie."""
    _install(monkeypatch, [_FakeErr(529)])
    with pytest.raises(_FakeErr):
        call_claude(
            messages=[{"role": "user", "content": "x"}],
            model="a",
            max_tokens=64,
            api_key="k",
            max_retries=0,
        )


def test_duplicate_models_in_the_chain_are_collapsed(monkeypatch):
    seen = _install(monkeypatch, [_FakeErr(529), _FakeMessage("b")])
    call_claude(
        messages=[{"role": "user", "content": "x"}],
        model="a",
        max_tokens=64,
        api_key="k",
        max_retries=0,
        fallback_models=["a", "b"],
    )
    assert [c["model"] for c in seen] == ["a", "b"]


# ── Ucięcie odpowiedzi ───────────────────────────────────────────────────────


def test_truncation_is_reported_but_does_not_raise_by_default(monkeypatch, caplog):
    """Trzy ścieżki naprawiają dziś ucięty JSON (`notes_insights_extractor`,
    parser profili Championa, generator CV). Bezwarunkowy wyjątek zamieniłby
    tę naprawę w martwy kod, a odzyskiwalny wynik w błąd."""
    _install(monkeypatch, [_FakeMessage('{"a": 1', stop_reason="max_tokens")])
    with caplog.at_level("WARNING"):
        message = call_claude(
            messages=[{"role": "user", "content": "x"}],
            model="a",
            max_tokens=64,
            api_key="k",
            max_retries=0,
        )
    assert text_of(message) == '{"a": 1'
    assert any("ucięta" in r.message for r in caplog.records)


def test_truncation_raises_when_the_caller_asks(monkeypatch):
    _install(monkeypatch, [_FakeMessage("x", stop_reason="max_tokens")])
    with pytest.raises(ClaudeTruncated):
        call_claude(
            messages=[{"role": "user", "content": "x"}],
            model="a",
            max_tokens=64,
            api_key="k",
            max_retries=0,
            raise_on_truncation=True,
        )


def test_truncation_never_triggers_the_fallback_chain(monkeypatch):
    """Ucięcie to problem DŁUGOŚCI TREŚCI — identyczny na każdym modelu.
    Kaskada płaciłaby drugi raz za ten sam, przewidywalny wynik."""
    seen = _install(
        monkeypatch,
        [_FakeMessage("x", stop_reason="max_tokens"), _FakeMessage("nigdy")],
    )
    with pytest.raises(ClaudeTruncated):
        call_claude(
            messages=[{"role": "user", "content": "x"}],
            model="a",
            max_tokens=64,
            api_key="k",
            max_retries=2,
            fallback_models=["b"],
            raise_on_truncation=True,
        )
    assert [c["model"] for c in seen] == ["a"]


def test_truncation_counts_as_a_healthy_call_and_spent_tokens(monkeypatch):
    """Wywołanie WRÓCIŁO i zostało opłacone. Zaliczenie go jako awarii
    otwierałoby circuit breaker na zdrowym dostawcy, a pominięcie tokenów
    zaniżałoby rachunek dokładnie tam, gdzie zużyto ich najwięcej."""
    from app.services.ai_quota import current_ai_call, declared_call
    from app.services.ai_quota import QuotaState
    from datetime import date

    ai_health.reset_providers_for_tests()
    _install(monkeypatch, [_FakeMessage("x", stop_reason="max_tokens")])

    state = QuotaState(used=1, limit=0, period_start=date(2026, 9, 1))
    with declared_call(AIFeatureKey.cv_generator, user_id=None, state=state):
        with pytest.raises(ClaudeTruncated):
            call_claude(
                messages=[{"role": "user", "content": "x"}],
                model="a",
                max_tokens=64,
                api_key="k",
                max_retries=0,
                raise_on_truncation=True,
            )
        context = current_ai_call()
        assert context is not None
        assert context.usage.input_tokens == 11
        assert context.usage.output_tokens == 7

    assert ai_health.provider_status("claude") == "ok"


# ── thinking / cache promptu ─────────────────────────────────────────────────


def test_thinking_is_disabled_by_default(monkeypatch):
    """Tokeny thinking liczą się do `max_tokens` i wypychają właściwą
    odpowiedź. MINDY była jedynym wołającym bez pinu — 400/800 tokenów bez
    rezerwy. Domyślna wartość tutaj likwiduje dwanaście kopii i tę lukę."""
    seen = _install(monkeypatch, [_FakeMessage()])
    call_claude(
        messages=[{"role": "user", "content": "x"}],
        model="a",
        max_tokens=64,
        api_key="k",
        max_retries=0,
    )
    assert seen[0]["thinking"] == {"type": "disabled"}


def test_explicit_thinking_wins_and_none_omits_the_parameter(monkeypatch):
    seen = _install(monkeypatch, [_FakeMessage(), _FakeMessage()])
    call_claude(
        messages=[{"role": "user", "content": "x"}],
        model="a",
        max_tokens=64,
        api_key="k",
        max_retries=0,
        thinking={"type": "enabled", "budget_tokens": 1024},
    )
    assert seen[0]["thinking"] == {"type": "enabled", "budget_tokens": 1024}

    call_claude(
        messages=[{"role": "user", "content": "x"}],
        model="a",
        max_tokens=64,
        api_key="k",
        max_retries=0,
        thinking=None,
    )
    assert "thinking" not in seen[1]


def test_system_prompt_is_marked_for_caching_on_request(monkeypatch):
    seen = _install(monkeypatch, [_FakeMessage(), _FakeMessage()])
    call_claude(
        messages=[{"role": "user", "content": "x"}],
        model="a",
        max_tokens=64,
        api_key="k",
        max_retries=0,
        system="długie statyczne instrukcje",
        cache_system=True,
    )
    assert seen[0]["system"] == [
        {
            "type": "text",
            "text": "długie statyczne instrukcje",
            "cache_control": {"type": "ephemeral"},
        }
    ]

    # Bez flagi prompt leci jak dotąd — inaczej zmiana dotknęłaby dziesięciu
    # wołających, którzy o cache nie prosili.
    call_claude(
        messages=[{"role": "user", "content": "x"}],
        model="a",
        max_tokens=64,
        api_key="k",
        max_retries=0,
        system="zwykły",
    )
    assert seen[1]["system"] == "zwykły"


# ── Helpery ──────────────────────────────────────────────────────────────────


def test_text_of_skips_non_text_blocks():
    """Modele Claude 5 potrafią zacząć od bloku thinking, więc `content[0].text`
    bywa pusty — objawiało się to niżej jako „nieprawidłowy JSON (znak 0)"."""

    class _Thinking:
        type = "thinking"

    message = type(
        "M",
        (),
        {
            "content": [
                _Thinking(),
                type("B", (), {"text": "część 1"})(),
                type("B", (), {"text": " i 2"})(),
            ]
        },
    )()
    assert text_of(message) == "część 1 i 2"


def test_call_claude_text_rejects_an_empty_response(monkeypatch):
    _install(monkeypatch, [_FakeMessage("   ")])
    with pytest.raises(ClaudeError):
        call_claude_text(
            messages=[{"role": "user", "content": "x"}],
            model="a",
            max_tokens=64,
            api_key="k",
            max_retries=0,
        )


@pytest.mark.parametrize("raw", ["", "   ", "nie-liczba"])
def test_env_number_survives_an_operator_slip(monkeypatch, raw):
    """`os.environ.get(name, str(default))` zwraca "" gdy klucz JEST ustawiony,
    ale pusty — a `int("")` rzuca. Literówka w Coolify nie może kończyć się
    gołym 500 w generacji CV."""
    monkeypatch.setenv("NEXUS_TEST_NUM", raw)
    assert env_number("NEXUS_TEST_NUM", 3, int) == 3


def test_env_number_reads_a_real_value(monkeypatch):
    monkeypatch.setenv("NEXUS_TEST_NUM", "7")
    assert env_number("NEXUS_TEST_NUM", 3, int) == 7
