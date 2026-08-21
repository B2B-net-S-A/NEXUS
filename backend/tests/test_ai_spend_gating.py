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
    # Widełki w szablonie są WYMYŚLONE — to jest powód istnienia pola `source`.
    assert mock.salary_range_suggestion
    assert "(uzupełnij)" in mock.requirements


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


# ── MINDY: powierzchnia bez `AIFeatureKey`, ale pod kill-switchem ────────────


@pytest.mark.asyncio
async def test_mindy_refuses_when_the_master_ai_switch_is_off(monkeypatch) -> None:
    """MINDY nie ma własnego klucza kwoty, więc główny wyłącznik był jej jedyną
    możliwą bramką — i do tej pory jej nie dotyczył."""
    from fastapi import HTTPException

    from app.api import dynareporter_mindy
    from app.services import ai_quota

    async def master_off(_db):
        return False

    monkeypatch.setattr(ai_quota, "get_master_enabled", master_off)

    with pytest.raises(HTTPException) as exc:
        await dynareporter_mindy._ensure_ai_master_enabled(object())

    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_mindy_passes_when_the_master_ai_switch_is_on(monkeypatch) -> None:
    from app.api import dynareporter_mindy
    from app.services import ai_quota

    async def master_on(_db):
        return True

    monkeypatch.setattr(ai_quota, "get_master_enabled", master_on)
    await dynareporter_mindy._ensure_ai_master_enabled(object())  # nie rzuca


def test_mindy_message_content_has_a_ceiling() -> None:
    """Bez sufitu uwierzytelniony użytkownik kontrolował cały, płatny prompt."""
    from pydantic import ValidationError

    from app.api.dynareporter_mindy import MindyChatRequest

    with pytest.raises(ValidationError):
        MindyChatRequest(messages=[{"role": "user", "content": "x" * 4001}])

    ok = MindyChatRequest(messages=[{"role": "user", "content": "x" * 4000}])
    assert len(ok.messages) == 1


def test_both_mindy_handlers_are_behind_the_master_switch() -> None:
    """Bramka musi stać przy KAŻDYM handlerze — nowy endpoint w tym module
    domyślnie znowu stałby poza systemem kwot."""
    import inspect

    from app.api import dynareporter_mindy

    for name in ("commentary", "chat"):
        src = inspect.getsource(getattr(dynareporter_mindy, name))
        assert "_ensure_ai_master_enabled" in src, name
        assert "limiter.limit" in src, name
