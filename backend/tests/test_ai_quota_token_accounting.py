"""Tokeny w logu zużycia + `declared_call` — dwa prymitywy z migracji 0270.

Powód istnienia: alarm o skoku wydatków AI jest — po decyzji z 24.08 o braku
sufitów — JEDYNĄ ochroną budżetu, a liczy WYWOŁANIA. Jedna generacja CV B2B
(16 384 tokeny outputu, łańcuch dwóch modeli) waży w nim tyle co jedna linia
MINDY, więc alarm milczy dokładnie wtedy, gdy rachunek rośnie najszybciej.

Cały mechanizm zbierania tokenów stoi na jednej, nieoczywistej własności:
`anyio.to_thread.run_sync` kopiuje MAPĘ contextvarów, nie wartości — więc
`call_claude`, biegnąc w wątku roboczym, mutuje TEN SAM obiekt `TokenUsage`,
który po powrocie czyta `ai_feature`. Gdyby kopiowała wartości, tokeny ginęłyby
po cichu przy każdym wywołaniu i nic by tego nie zgłosiło. Dlatego ta własność
ma tu własny test, a nie jest założeniem w komentarzu.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from app.core.config import settings
from app.models.ai_feature import AIFeatureKey
from app.services import ai_quota, claude_client
from app.services.ai_quota import (
    AIQuotaUngated,
    AiCallContext,
    QuotaState,
    TokenUsage,
    current_ai_call,
    declared_call,
    record_token_usage,
)

BACKEND = Path(__file__).resolve().parents[1]


def _state() -> QuotaState:
    from datetime import date

    return QuotaState(used=1, limit=0, period_start=date(2026, 9, 1))


# ── Akumulator ───────────────────────────────────────────────────────────────


def test_usage_sums_across_calls_because_one_operation_is_a_chain():
    """Jedna operacja bywa łańcuchem: mapa-redukcja transkryptu, dwie próby
    UoP, fallback na kolejny model. Rachunek dotyczy operacji, nie ostatniego
    round-tripu — więc nadpisywanie zaniżałoby koszt tam, gdzie jest najwyższy.
    """
    usage = TokenUsage()
    usage.add(input_tokens=100, output_tokens=10)
    usage.add(input_tokens=250, output_tokens=40)
    assert (usage.input_tokens, usage.output_tokens) == (350, 50)
    assert usage.any() is True


@pytest.mark.parametrize(
    "bad",
    [None, "1200", True, False, -5, 3.5],
    ids=["none", "string", "true", "false", "negative", "float"],
)
def test_garbage_from_the_provider_is_ignored_not_raised(bad):
    """`usage` bywa niepełne przy nietypowej odpowiedzi. Telemetria nie ma
    prawa wywrócić wywołania, za które JUŻ zapłacono — a `True` jest tu
    osobnym przypadkiem, bo w Pythonie `isinstance(True, int)` to prawda
    i bez jawnego odsiania bool doliczyłby jeden token.
    """
    usage = TokenUsage()
    usage.add(input_tokens=bad, output_tokens=bad)
    assert (usage.input_tokens, usage.output_tokens) == (0, 0)
    assert usage.any() is False


def test_recording_without_a_declared_call_is_a_no_op():
    """Brak kontekstu to nie błąd — od wykrywania niezadeklarowanych wywołań
    jest `_assert_declared`. Druga bramka w telemetrii tylko dublowałaby sygnał.
    """
    assert current_ai_call() is None
    record_token_usage(input_tokens=10, output_tokens=1)  # nie rzuca


def test_recording_inside_a_declared_call_accumulates():
    with declared_call(AIFeatureKey.uop_check, user_id=7, state=_state()):
        record_token_usage(input_tokens=120, output_tokens=8)
        record_token_usage(input_tokens=30, output_tokens=2)
        context = current_ai_call()
        assert context is not None
        assert (context.usage.input_tokens, context.usage.output_tokens) == (150, 10)


async def test_tokens_recorded_in_a_worker_thread_reach_the_caller():
    """TO JEST TEN TEST. Cały zapis tokenów zależy od tego, że kopia kontekstu
    w wątku roboczym wskazuje na TEN SAM akumulator. `call_claude` jest
    synchroniczne i wołane przez `run_in_threadpool` — gdyby kopiowanie
    contextvarów duplikowało wartość, mutacja zostawałaby w wątku, a licznik
    tokenów pokazywałby zero przy w pełni działającym systemie.
    """
    from starlette.concurrency import run_in_threadpool

    with declared_call(AIFeatureKey.cv_generator, user_id=None, state=_state()):
        context = current_ai_call()
        assert context is not None

        def _in_worker() -> None:
            # Dokładnie to, co robi `claude_client._record_tokens`.
            record_token_usage(input_tokens=16_384, output_tokens=4_096)

        await run_in_threadpool(_in_worker)

        assert context.usage.input_tokens == 16_384
        assert context.usage.output_tokens == 4_096


def test_provider_boundary_records_usage_from_the_message():
    """`_record_tokens` czyta `message.usage` — to jedyne miejsce widzące je
    dla WSZYSTKICH wołających naraz."""

    class _Usage:
        input_tokens = 1_000
        output_tokens = 250

    class _Message:
        usage = _Usage()

    with declared_call(AIFeatureKey.scoring, user_id=1, state=_state()):
        claude_client._record_tokens(_Message())
        context = current_ai_call()
        assert context is not None
        assert (context.usage.input_tokens, context.usage.output_tokens) == (1_000, 250)


def test_provider_boundary_survives_a_message_without_usage():
    with declared_call(AIFeatureKey.scoring, user_id=1, state=_state()):
        claude_client._record_tokens(object())  # brak `usage`
        context = current_ai_call()
        assert context is not None
        assert context.usage.any() is False


# ── declared_call ────────────────────────────────────────────────────────────


def test_declared_call_satisfies_the_provider_gate_and_resets_after(monkeypatch):
    """Powód istnienia prymitywu: generacja CV B2B wydaje pieniądze w
    `BackgroundTasks`, PO zamknięciu handlera, gdy contextvar z `ai_feature`
    już nie żyje. Pod STRICT takie wywołanie rzuciłoby `AIQuotaUngated` mimo
    poprawnie naliczonej kwoty.
    """
    monkeypatch.setattr(settings, "AI_QUOTA_STRICT", True)

    with pytest.raises(AIQuotaUngated):
        claude_client._assert_declared("claude-sonnet-5")

    with declared_call(AIFeatureKey.cv_generator, user_id=3, state=_state()):
        claude_client._assert_declared("claude-sonnet-5")  # nie rzuca

    # Kontekst MUSI zniknąć po bloku — inaczej kolejne zadanie w tym samym
    # wątku dziedziczyłoby cudzą deklarację i wydawało pieniądze pod nią.
    assert current_ai_call() is None
    with pytest.raises(AIQuotaUngated):
        claude_client._assert_declared("claude-sonnet-5")


def test_declared_call_does_not_charge_anything():
    """Prymityw z definicji nie nalicza — naliczenie zrobił handler. Test
    pilnuje, żeby nikt nie „naprawił" tego przez dołożenie tu obciążenia:
    byłoby wtedy liczone dwa razy na jedną operację."""
    source = (BACKEND / "app/services/ai_quota.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "declared_call"
    )
    called = {
        node.func.id
        for node in ast.walk(func)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    } | {
        node.func.attr
        for node in ast.walk(func)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "check_and_increment" not in called
    assert not any(name.startswith("execute") for name in called)


# `declared_call` obchodzi sufit i główny wyłącznik — z założenia, bo cały jego
# sens polega na braku bramki. Runtime nie odróżni prawdziwego `QuotaState` od
# wymyślonego, więc jedyną egzekwowalną ochroną jest lista miejsc, którym wolno
# go użyć. Ta lista ma tylko maleć. Wzorzec: `_BARE_CHARGE_BASELINE`.
# Dwa miejsca, oba z tego samego powodu: wydatek dzieje się w `BackgroundTasks`,
# po zamknięciu handlera, gdy contextvar z `ai_feature` już nie żyje. Kwota
# w obu jest naliczona WYŻEJ, w handlerze — tutaj następuje wyłącznie
# deklaracja. Lista ma tylko maleć.
_DECLARED_CALL_ALLOWLIST: set[str] = {
    "app/api/cv_generator_b2b.py",
    "app/api/client_cv_rules.py",
}


def _files_using_declared_call() -> set[str]:
    found: set[str] = set()
    for path in (BACKEND / "app").rglob("*.py"):
        if str(path.relative_to(BACKEND)) == "app/services/ai_quota.py":
            continue  # definiuje prymityw, nie używa go
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and (
                (isinstance(node.func, ast.Name) and node.func.id == "declared_call")
                or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "declared_call"
                )
            ):
                found.add(str(path.relative_to(BACKEND)))
    return found


def test_declared_call_does_not_spread():
    new = _files_using_declared_call() - _DECLARED_CALL_ALLOWLIST
    assert not new, (
        "`declared_call` deklaruje wywołanie AI BEZ naliczania kwoty — każde "
        "nowe użycie obchodzi sufit i główny wyłącznik. Dopisz plik do "
        "allowlisty świadomie, razem z uzasadnieniem:\n"
        + "\n".join(f"  {p}" for p in sorted(new))
    )


def test_declared_call_allowlist_has_no_stale_entries():
    """Strażnik strażnika: martwy wpis udaje dług, którego nie ma."""
    stale = _DECLARED_CALL_ALLOWLIST - _files_using_declared_call()
    assert not stale, f"już nieużywane, usuń z allowlisty: {sorted(stale)}"


# ── Zapis do bazy ────────────────────────────────────────────────────────────


async def test_persisting_tokens_never_raises_even_when_the_write_fails(monkeypatch):
    """`_persist_token_usage` wisi w `finally`. Wyjątek stąd przykryłby
    prawdziwy wyjątek z bloku wołającego — czyli zamieniłby awarię generacji
    w niezwiązany błąd bazy."""

    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("baza padła")

        async def __aexit__(self, *_):
            return False

    import app.core.database as database

    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _Boom())

    context = AiCallContext(
        feature=AIFeatureKey.uop_check, user_id=None, state=_state()
    )
    context.usage.add(input_tokens=10, output_tokens=1)
    await ai_quota._persist_token_usage(context)  # nie rzuca


async def test_zero_usage_does_not_touch_the_database(monkeypatch):
    """Większość operacji AI nie raportuje tokenów (fallbacki, odmowy przed
    wywołaniem). Otwieranie sesji dla zera byłoby zapytaniem na każde z nich."""
    opened = False

    def _factory():
        nonlocal opened
        opened = True
        raise AssertionError("nie wolno otwierać sesji dla zerowego zużycia")

    import app.core.database as database

    monkeypatch.setattr(database, "AsyncSessionLocal", _factory)

    context = AiCallContext(
        feature=AIFeatureKey.uop_check, user_id=None, state=_state()
    )
    await ai_quota._persist_token_usage(context)
    assert opened is False


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="wymaga PostgreSQL (realny wiersz ai_usage_log)",
)
async def test_tokens_land_on_the_usage_row():
    """Pełna ścieżka: naliczenie → wywołanie → tokeny w tym samym wierszu."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.ai_feature import AIUsageLog
    from app.services.ai_quota import ai_feature

    feature = AIFeatureKey.uop_check

    async def _row_tokens() -> tuple[int, int]:
        async with AsyncSessionLocal() as session:
            row = (
                await session.execute(
                    select(AIUsageLog.input_tokens, AIUsageLog.output_tokens).where(
                        AIUsageLog.feature == feature,
                        AIUsageLog.period_start == ai_quota._current_period_start(),
                        AIUsageLog.user_id.is_(None),
                    )
                )
            ).first()
        return (0, 0) if row is None else (row[0], row[1])

    before = await _row_tokens()

    async with AsyncSessionLocal() as db:
        async with ai_feature(db, feature):
            await db.commit()  # wzorzec „naliczamy dopuszczenie" z handlerów
            record_token_usage(input_tokens=777, output_tokens=111)

    after = await _row_tokens()
    assert after == (before[0] + 777, before[1] + 111)
