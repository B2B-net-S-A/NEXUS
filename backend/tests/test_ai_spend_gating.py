"""Wydatki na AI: co jest deklarowane, co jest oznaczone i co zatrzymuje kill-switch.

Trzy klasy defektów, każda cicha:

* wywołanie LLM obciążone kwotą, ale NIEZADEKLAROWANE — liczy się poprawnie,
  a na granicy providera loguje się jako „UNGATED", więc detektor, na którym
  stoi `AI_QUOTA_STRICT`, składa się głównie z fałszywych alarmów;
* awaria dostawcy zwijana po cichu do szablonu ze zmyślonymi widełkami
  płacowymi, w kształcie odpowiedzi nie do odróżnienia od wyjścia AI;
* powierzchnia Claude'a całkowicie poza systemem kwot, której główny wyłącznik
  AI nie zatrzymuje.

DB-free poza jawnie oznaczonym testem trasy.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.api import ai_writer


# ── ai_writer: deklaracja, wspólny klient, oznaczenie źródła ─────────────────


def test_generate_job_response_marks_its_source() -> None:
    """Szablon i wyjście AI muszą być rozróżnialne w kształcie odpowiedzi."""
    mock = ai_writer._generate_mock(
        ai_writer.GenerateJobRequest(title="Python Developer", seniority="senior")
    )
    assert mock.source == "template"
    assert mock.salary_range_suggestion == ""
    assert mock.requirements == ""
    assert mock.benefits == ""
    assert mock.nice_to_have == ""


@pytest.mark.asyncio
async def test_generate_with_claude_uses_the_shared_helper(monkeypatch) -> None:
    """Surowy `anthropic.Anthropic(...)` dziedziczył domyślne 600 s SDK, nie miał
    backoffu na 429/529, nie karmił circuit breakera i był niewidzialny dla
    bramki na granicy providera."""
    captured: dict[str, object] = {}

    class _Block:
        text = '{"title": "T", "description": "D", "requirements": "R", '
        text += '"nice_to_have": "N", "benefits": "B", '
        text += '"salary_range_suggestion": "S"}'

    class _Message:
        content = [_Block()]

    def fake_call_claude(**kwargs):
        captured.update(kwargs)
        return _Message()

    import app.services.claude_client as claude_client

    monkeypatch.setattr(claude_client, "call_claude", fake_call_claude)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    out = await ai_writer._generate_with_claude(
        ai_writer.GenerateJobRequest(title="Python Developer")
    )

    assert out.source == "claude"
    assert captured["model"] == ai_writer._JOB_WRITER_MODEL
    assert captured["max_tokens"] == 1500
    # Sonnet 5 liczy tokeny thinking do max_tokens i ucinał ten JSON.
    assert captured["thinking"] == {"type": "disabled"}


@pytest.mark.asyncio
async def test_missing_api_key_is_not_a_provider_failure(monkeypatch) -> None:
    """Brak klucza to fakt konfiguracji wdrożenia — i tylko on uprawnia szablon."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)

    with pytest.raises(ai_writer._ClaudeNotConfigured):
        await ai_writer._generate_with_claude(
            ai_writer.GenerateJobRequest(title="Python Developer")
        )


@pytest.mark.asyncio
async def test_claude_failure_returns_503_not_a_fabricated_template(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
) -> None:
    """Wymaga bazy (kwota). Awaria dostawcy nie może wyjść jako ogłoszenie.

    Przed poprawką KAŻDY wyjątek zwijał się do `_generate_mock` w identycznym
    kształcie odpowiedzi: rekruter dostawał zmyślone widełki płacowe i dosłowny
    placeholder „(uzupełnij)", brał to za wyjście AI i publikował u klienta.
    """

    async def boom(_request):
        raise RuntimeError("529 overloaded_error")

    monkeypatch.setattr(ai_writer, "_generate_with_claude", boom)

    resp = await app_client.post(
        "/api/ai/generate-job",
        headers=app_auth_headers,
        json={"title": "Python Developer", "seniority": "senior"},
    )

    assert resp.status_code == 503, resp.text
    assert "uzupełnij" not in resp.text


@pytest.mark.asyncio
async def test_missing_key_still_yields_a_labelled_template(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
) -> None:
    """Wymaga bazy (kwota). Bez klucza (dev/local) szablon zostaje — OZNACZONY."""

    async def not_configured(_request):
        raise ai_writer._ClaudeNotConfigured("no key")

    monkeypatch.setattr(ai_writer, "_generate_with_claude", not_configured)

    resp = await app_client.post(
        "/api/ai/generate-job",
        headers=app_auth_headers,
        json={"title": "Python Developer", "seniority": "senior"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["source"] == "template"


# ── MINDY: własny kubełek kwoty (`mindy_chat`) ───────────────────────────────


@pytest.mark.asyncio
async def test_mindy_charges_its_own_quota_bucket(monkeypatch) -> None:
    """MINDY nie miała żadnego `AIFeatureKey`, więc zaseedowanie limitów dla
    pozostałych kluczy dowodliwie by jej nie tknęło — nie było czego ograniczyć.

    Kubełek musi być WŁASNY i nieść id użytkownika: doklejenie MINDY do cudzego
    klucza schowałoby jej wydatek w cudzym raporcie zużycia."""
    from app.api import dynareporter_mindy
    from app.models.ai_feature import AIFeatureKey
    from app.services import ai_quota

    seen: dict[str, object] = {}

    async def _accept(_db, feature, user_id=None, *, units=1):
        seen["feature"] = feature
        seen["user_id"] = user_id
        return None

    monkeypatch.setattr(ai_quota, "check_and_increment", _accept)

    async with dynareporter_mindy._mindy_quota(object(), 11):
        # Wewnątrz bloku wywołanie jest ZADEKLAROWANE — inaczej `call_claude`
        # loguje je na granicy dostawcy jako „UNGATED" mimo poprawnego licznika.
        assert ai_quota.current_ai_call() is not None

    assert seen == {"feature": AIFeatureKey.mindy_chat, "user_id": 11}


@pytest.mark.asyncio
async def test_mindy_quota_propagates_refusal(monkeypatch) -> None:
    """Master toggle, wyłączona funkcja i wyczerpany sufit lecą tą samą drogą."""
    from app.api import dynareporter_mindy
    from app.services import ai_quota

    async def _refuse(_db, feature, user_id=None, *, units=1):
        raise ai_quota.AIQuotaExceeded(feature, "Funkcje AI są wyłączone globalnie")

    monkeypatch.setattr(ai_quota, "check_and_increment", _refuse)

    with pytest.raises(ai_quota.AIQuotaExceeded):
        async with dynareporter_mindy._mindy_quota(object(), 11):
            pytest.fail("blok nie może się wykonać po odmowie kwoty")


def test_mindy_refusal_becomes_503_with_a_reason() -> None:
    """Wyczerpany limit czytany jako gołe 500 kończy zgłoszeniem do supportu."""
    from app.api import dynareporter_mindy
    from app.models.ai_feature import AIFeatureKey
    from app.services.ai_quota import AIQuotaExceeded

    exc = dynareporter_mindy._quota_exceeded_response(
        AIQuotaExceeded(AIFeatureKey.mindy_chat, "Miesięczny limit wyczerpany", 20, 20)
    )
    assert exc.status_code == 503
    assert exc.detail["feature"] == "mindy_chat"
    assert exc.detail["limit"] == 20


def test_mindy_message_content_has_a_ceiling() -> None:
    """Bez sufitu uwierzytelniony użytkownik kontrolował cały, płatny prompt."""
    from pydantic import ValidationError

    from app.api.dynareporter_mindy import MindyChatRequest

    with pytest.raises(ValidationError):
        MindyChatRequest(messages=[{"role": "user", "content": "x" * 4001}])

    ok = MindyChatRequest(messages=[{"role": "user", "content": "x" * 4000}])
    assert len(ok.messages) == 1


def test_both_mindy_handlers_are_behind_the_quota() -> None:
    """Bramka musi stać przy KAŻDYM handlerze — nowy endpoint w tym module
    domyślnie znowu stałby poza systemem kwot."""
    import inspect

    from app.api import dynareporter_mindy

    for name in ("commentary", "chat"):
        src = inspect.getsource(getattr(dynareporter_mindy, name))
        assert "_mindy_quota(" in src, name
        assert "limiter.limit" in src, name
