"""Fala 3: hydraulika parsera + runner masowego uzupełniania pól z CV.

Trzy rzeczy, które ten plik przybija, bo każda była realną decyzją:

* prompt MASOWY nie zawiera pól generatywnych, a prompt INTERAKTYWNY pozostaje
  nietknięty (jego hash wchodzi w klucze cache i steruje zachowaniem ścieżki
  rekrutera);
* kwota gasi wyłącznie PŁATNY krok parsera — darmowe fallbacki działają dalej,
  a w biegu masowym wyczerpana kwota zatrzymuje BIEG, nie wiersz;
* `[]` w skills liczy się jako puste (33 625 wierszy trzyma pustą tablicę).
"""

from types import SimpleNamespace

import pytest

from app.services.cv_field_backfill import _empty_now
from app.services.llm_prompts import CV_ENRICHMENT, CV_ENRICHMENT_BULK


def test_bulk_prompt_has_no_generative_fields():
    """Backfill prosi o fakty, nie o polszczyznę.

    `professional_profile` i `career_summary` to ~35-40% tokenów wyjścia
    (wyjście = ~59% rachunku przy Haiku) i zarazem najtrudniejsza kompetencja
    dla tańszego modelu. Wycięcie ich jest tańsze i bezpieczniejsze naraz.
    """

    rendered = CV_ENRICHMENT_BULK.render(cv_text="x")
    assert "professional_profile" not in rendered
    assert "career_summary" not in rendered
    # pola celu zostają
    for field in ("skills", "city", "years_it_experience", "education"):
        assert field in rendered, field


def test_interactive_prompt_is_untouched():
    """Zmiana treści CV_ENRICHMENT zmienia zachowanie ścieżki rekrutera i
    unieważnia cache oparty o hash promptu — dlatego wariant masowy jest NOWYM
    szablonem, a ten test zamraża, że stary nie drgnął."""

    assert CV_ENRICHMENT.name == "cv_enrichment"
    assert CV_ENRICHMENT.version == 5
    rendered = CV_ENRICHMENT.render(cv_text="x")
    assert "professional_profile" in rendered
    assert "career_summary" in rendered


def test_empty_skills_list_counts_as_empty():
    """33 625 wierszy trzyma skills='[]'; realną listę ma ~600 osób.

    Gdyby `[]` liczyło się jako wypełnione, backfill ominąłby praktycznie
    całą populację, dla której powstał.
    """

    candidate = SimpleNamespace(skills=[], city=None, years_it_experience=None)
    assert _empty_now(candidate) == {"skills", "city", "years_it_experience"}

    candidate = SimpleNamespace(
        skills=[{"name": "Python"}], city="Kraków", years_it_experience=5
    )
    assert _empty_now(candidate) == set()


class _FakeUsage:
    input_tokens = 3111
    output_tokens = 642


class _FakeBlock:
    text = '{"city": "Kraków", "_confidence": {"city": 0.9}}'


class _FakeMessage:
    content = [_FakeBlock()]
    usage = _FakeUsage()


@pytest.mark.asyncio
async def test_parse_with_claude_captures_usage_and_template_identity(monkeypatch):
    """`message.usage` szło do kosza — a bez niego kosztorys biegu to zgadywanka."""

    from app.core.config import settings
    from app.services import claude_client
    from app.services.cv_parser import _parse_with_claude
    from app.services.llm_prompts import CV_ENRICHMENT_BULK

    seen: dict = {}

    def fake_call_claude(**kwargs):
        seen.update(kwargs)
        return _FakeMessage()

    monkeypatch.setattr(claude_client, "call_claude", fake_call_claude)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(settings, "CV_ENRICHMENT_ENABLED", True, raising=False)

    parsed = await _parse_with_claude(
        "CV treść", model="claude-haiku-4-5-20251001", template=CV_ENRICHMENT_BULK
    )

    assert parsed is not None
    assert seen["model"] == "claude-haiku-4-5-20251001"
    assert parsed["_source"] == "claude:cv_enrichment_bulk:v1"
    assert parsed["_usage"] == {
        "model": "claude-haiku-4-5-20251001",
        "input_tokens": 3111,
        "output_tokens": 642,
    }


@pytest.mark.asyncio
async def test_quota_gates_only_the_paid_step_fallbacks_survive(monkeypatch):
    """Wyczerpana kwota NIE może gasić darmowych heurystyk.

    Onboarding z CV bez LLM nadal wyciąga kontakt regexem — kwota na płatny
    model nie jest powodem, żeby stracić także to, co nic nie kosztuje.
    """

    from app.services import cv_parser as parser_module
    from app.services.ai_quota import AIQuotaExceeded

    async def exploding_claude(*args, **kwargs):  # pragma: no cover - nie wolno
        raise AssertionError("płatny krok nie może być wywołany przy odmowie kwoty")

    monkeypatch.setattr(parser_module, "_parse_with_claude", exploding_claude)

    class _DenyingFeature:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            from app.models.ai_feature import AIFeatureKey

            raise AIQuotaExceeded(AIFeatureKey.cv_parser, "limit")

        async def __aexit__(self, *exc):
            return False

    import app.services.ai_quota as quota_module

    monkeypatch.setattr(quota_module, "ai_feature", _DenyingFeature)

    # Ollama wyłączona wprost (Settings pydantica nie przyjmie obcego pola) —
    # wynik MUSI przyjść z darmowego regexu.
    async def no_ollama(*args, **kwargs):
        return None

    monkeypatch.setattr(parser_module, "_parse_with_ollama", no_ollama)

    result = await parser_module.parse_cv(
        "Jan Kowalski\njan.kowalski@example.com\n+48 600 123 456",
        db=object(),  # cokolwiek nie-None: włącza gałąź bramkowaną
    )

    assert result["email"] == "jan.kowalski@example.com"


@pytest.mark.asyncio
async def test_backfill_run_stops_on_quota_not_per_row(monkeypatch):
    """Kwota to hamulec organizacyjny — bieg staje, kursor zostaje."""

    from app.services import cv_field_backfill as runner
    from app.services.ai_quota import AIQuotaExceeded

    class _DenyingFeature:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            from app.models.ai_feature import AIFeatureKey

            raise AIQuotaExceeded(AIFeatureKey.cv_backfill, "limit miesięczny")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(runner, "ai_feature", _DenyingFeature)

    candidate = SimpleNamespace(
        id=7, skills=[], city=None, years_it_experience=None, raw_cv_text="x" * 300
    )

    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return self._rows

    class _FakeDb:
        def __init__(self):
            self.calls = 0

        async def execute(self, *_a, **_k):
            self.calls += 1
            return _FakeResult([candidate] if self.calls == 1 else [])

        async def commit(self):
            pass

    stats = await runner.backfill_cv_fields(_FakeDb())

    assert stats["stopped_reason"].startswith("quota")
    assert stats["last_id"] == 7, "kursor musi wskazywać, od czego wznowić"
