"""AI feature quota check + usage counter.

Lifted from `app.models.ai_feature` semantics:
- `AIMasterToggle.enabled = False` → all AI calls blocked.
- `AIFeatureConfig.enabled = False` for a given feature → that feature blocked.
- `AIFeatureConfig.monthly_limit > 0` → check current-month count vs limit.
- `monthly_limit = 0` → unlimited.

Usage: call `await check_and_increment(db, feature, user_id)` at the top of
any AI-touching endpoint. Raises `AIQuotaExceeded` if blocked — the API layer
should catch and convert to HTTP 503.

Atomicity:
- Toggle/limit reads plus an independently committed operation.
- Race: if two requests pass the check simultaneously they both increment
  past the limit by 1. Acceptable for our scale (≤200 users) — exact
  enforcement would need SELECT … FOR UPDATE which adds latency. Quota is
  advisory, not security.
"""

from __future__ import annotations

import contextvars
import logging
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_metering import AIOperation, AIProviderCall

from app.models.ai_feature import (
    AIFeatureConfig,
    AIFeatureKey,
    AIMasterToggle,
    AIUsageLog,
)

logger = logging.getLogger(__name__)


class AIQuotaExceeded(Exception):
    """Raised when an AI call is blocked by toggle or quota."""

    def __init__(
        self,
        feature: AIFeatureKey,
        reason: str,
        used: int = 0,
        limit: int = 0,
    ):
        super().__init__(f"AI quota for {feature.value} blocked: {reason}")
        self.feature = feature
        self.reason = reason
        self.used = used
        self.limit = limit


@dataclass
class QuotaState:
    used: int
    limit: int
    period_start: date
    operation_id: str | None = None

    @property
    def remaining(self) -> int:
        if self.limit == 0:
            return 2**31 - 1  # effectively unlimited
        return max(0, self.limit - self.used)


def _current_period_start() -> date:
    """First day of the current calendar month, UTC."""
    now = datetime.now(timezone.utc).date()
    return now.replace(day=1)


async def get_master_enabled(db: AsyncSession) -> bool:
    """Read the singleton master toggle. Defaults to True if row missing."""
    result = await db.execute(
        select(AIMasterToggle.enabled).where(AIMasterToggle.id == 1)
    )
    enabled = result.scalar_one_or_none()
    return True if enabled is None else bool(enabled)


async def get_feature_config(
    db: AsyncSession, feature: AIFeatureKey
) -> Optional[AIFeatureConfig]:
    """Look up the per-feature config. Missing row = treat as disabled."""
    result = await db.execute(
        select(AIFeatureConfig).where(AIFeatureConfig.feature == feature)
    )
    return result.scalar_one_or_none()


async def get_usage(
    db: AsyncSession,
    feature: AIFeatureKey,
    user_id: Optional[int],
    period_start: Optional[date] = None,
) -> int:
    """Sum of calls for (feature, user, period). Returns 0 if no row."""
    period = period_start or _current_period_start()
    stmt = select(func.coalesce(func.sum(AIUsageLog.count), 0)).where(
        AIUsageLog.feature == feature,
        AIUsageLog.period_start == period,
    )
    if user_id is not None:
        stmt = stmt.where(AIUsageLog.user_id == user_id)
    else:
        stmt = stmt.where(AIUsageLog.user_id.is_(None))

    result = await db.execute(stmt)
    count = result.scalar_one_or_none() or 0
    measured = await db.scalar(
        select(func.coalesce(func.sum(AIOperation.units), 0)).where(
            AIOperation.feature == feature.value,
            AIOperation.period_start == period,
            AIOperation.actor_key
            == (f"user:{user_id}" if user_id is not None else "system"),
        )
    )
    return int(count + (measured or 0))


async def get_total_usage_for_period(
    db: AsyncSession,
    feature: AIFeatureKey,
    period_start: Optional[date] = None,
) -> int:
    """Sum across all users for a given (feature, period). Used by Settings UI."""
    from sqlalchemy import func

    period = period_start or _current_period_start()
    result = await db.execute(
        select(func.coalesce(func.sum(AIUsageLog.count), 0)).where(
            AIUsageLog.feature == feature,
            AIUsageLog.period_start == period,
        )
    )
    legacy = int(result.scalar() or 0)
    measured = await db.scalar(
        select(func.coalesce(func.sum(AIOperation.units), 0)).where(
            AIOperation.feature == feature.value,
            AIOperation.period_start == period,
        )
    )
    return legacy + int(measured or 0)


async def get_usage_summary_for_period(
    db: AsyncSession,
    period_start: Optional[date] = None,
) -> dict[str, tuple[int, int, int]]:
    """Zbiorcze zużycie per funkcja w okresie: (wywołania, tokeny_in, tokeny_out).

    JEDEN ``GROUP BY`` zamiast pętli ``get_total_usage_for_period`` per funkcja
    (N+1) w panelu Ustawienia → AI — tokeny podwoiłyby ten koszt. Kolumna
    ``feature`` czytana jako TEKST: prod trzyma w ``ai_usage_log`` wiersze po
    funkcjach przemianowanych/usuniętych (``embeddings``, ``matching``, …),
    a hydratacja enumem przy odczycie rzuciłaby ``LookupError`` na całym
    ``select()`` (ta sama pułapka co w ``ai_settings`` i sondzie zdrowia).
    Klucze spoza ``AIFeatureKey`` wołający po prostu pomija.
    """
    from sqlalchemy import Text, cast, func

    period = period_start or _current_period_start()
    result = await db.execute(
        select(
            cast(AIUsageLog.feature, Text),
            func.coalesce(func.sum(AIUsageLog.count), 0),
            func.coalesce(func.sum(AIUsageLog.input_tokens), 0),
            func.coalesce(func.sum(AIUsageLog.output_tokens), 0),
        )
        .where(AIUsageLog.period_start == period)
        .group_by(cast(AIUsageLog.feature, Text))
    )
    counts = {str(feat): int(count or 0) for feat, count, _tin, _tout in result.all()}
    operations = await db.execute(
        select(AIOperation.feature, func.sum(AIOperation.units))
        .where(AIOperation.period_start == period)
        .group_by(AIOperation.feature)
    )
    for feature, count in operations.all():
        counts[feature] = counts.get(feature, 0) + int(count)
    from app.services.ai_metering import measured_usage

    measured = await measured_usage(db, period)
    # Historical token aggregates are untrustworthy. Keep them in storage for
    # reconciliation, but never blend them into the new measured totals.
    return {
        feature: (
            count,
            int(measured.get(feature, {}).get("input_tokens") or 0),
            int(measured.get(feature, {}).get("output_tokens") or 0),
        )
        for feature, count in counts.items()
    }


async def check_and_increment(
    db: AsyncSession,
    feature: AIFeatureKey,
    user_id: Optional[int] = None,
    *,
    units: int = 1,
    commit_with_caller: bool = False,
) -> QuotaState:
    """Atomic-ish quota check + increment.

    Raises ``AIQuotaExceeded`` if blocked. Returns post-increment state on
    success. Admission normally commits independently of business work.
    Durable queues may set ``commit_with_caller`` to persist admission together
    with their job. They MUST commit before dispatching any provider call.

    ``units`` obsługuje operacje, które są JEDNĄ decyzją użytkownika, ale
    kilkoma wywołaniami modelu — dziś tylko lint reguł CV (jedno pole = jedno
    wywołanie). Naliczenie ich z góry, jednym sprawdzeniem, zachowuje
    „wszystko albo nic": rekruter dostaje pełną ocenę albo czyste 503, nigdy
    połowy przy wyczerpanym limicie w środku pętli. Przy ``units=1`` warunek
    blokady jest identyczny co do znaku z poprzednim (``total_used >= limit``).
    """
    if units < 1:
        raise ValueError("units musi być dodatnie")
    # 1. Master toggle
    master = await get_master_enabled(db)
    if not master:
        raise AIQuotaExceeded(feature, "Funkcje AI są wyłączone globalnie")

    # 2. Per-feature toggle + limit.
    #
    # A MISSING row means "enabled, no ceiling" — fail-open, matching
    # `AIFeatureConfig.enabled`'s own default. This module used to fail-closed
    # while `match_justification_service._gate_and_count` failed open on the
    # same question, so whether an unseeded feature worked depended on which of
    # two copies of this logic the request happened to reach. That second copy
    # is gone; this is the one behaviour.
    #
    # Fail-open has a real cost, and on prod it is not hypothetical — but the
    # missing half is NOT the row. All 11 `AIFeatureKey` rows exist there and
    # every one of them still carries the column default `monthly_limit = 0`,
    # which this module documents as "no ceiling". So the branch below can
    # never fire for any feature, and seeding more rows would change nothing:
    # only a positive number does, and picking it is an admin decision
    # (Ustawienia → AI writes `monthly_limit` straight into this column).
    # `/api/health.checks.ai_features` therefore lists every key WITHOUT a
    # positive ceiling — a missing row and a row at 0 alike — as a spend
    # warning, not an outage.
    config = await get_feature_config(db, feature)
    if config is not None and not config.enabled:
        raise AIQuotaExceeded(feature, "Funkcja AI wyłączona w ustawieniach")

    limit = config.monthly_limit if config is not None else 0
    period = _current_period_start()
    total_used = await get_total_usage_for_period(db, feature, period)

    if limit > 0 and total_used + units > limit:
        raise AIQuotaExceeded(
            feature,
            "Miesięczny limit wyczerpany",
            used=total_used,
            limit=limit,
        )

    # A distinct, durable operation replaces the nullable monthly upsert.
    # No FK to caller-owned records and no locks shared with its transaction.
    # Business rollback must not refund an admitted provider call.
    from app.core.database import AsyncSessionLocal

    operation_id = str(uuid4())
    operation = AIOperation(
        id=operation_id,
        feature=feature.value,
        actor_key=f"user:{user_id}" if user_id is not None else "system",
        period_start=period,
        units=units,
    )
    if commit_with_caller:
        db.add(operation)
        await db.flush()
    else:
        async with AsyncSessionLocal() as metering_db:
            metering_db.add(operation)
            await metering_db.commit()
    return QuotaState(
        used=total_used + units,
        limit=limit,
        period_start=period,
        operation_id=operation_id,
    )


# ── Provider-boundary gate ───────────────────────────────────────────────────
#
# A decorator on the route was the obvious design and would not have worked:
# three of the five paths that reach Claude without a quota check are not
# routes at all — `fireflies_sync` is a background loop, CV enrichment is a
# `BackgroundTask`, and `enrich_from_call` sits in a CloudTalk webhook. A
# route decorator never touches any of them, which is precisely how they came
# to be ungated while every handler looked correctly wrapped.
#
# So the gate stands at the provider boundary instead: `call_claude` is the one
# place nearly all traffic funnels through, and it can ask "was this call
# declared?" regardless of what kind of caller made it.

_AI_CALL_CONTEXT: contextvars.ContextVar[Optional["AiCallContext"]] = (
    contextvars.ContextVar("ai_call_context", default=None)
)


@dataclass
class TokenUsage:
    """Tokeny zebrane w obrębie JEDNEJ zadeklarowanej operacji AI.

    Mutowalny akumulator, a nie zwracana wartość, bo wypełnia go inna warstwa
    niż ta, która go czyta: `call_claude` jest synchroniczne i biegnie
    w `run_in_threadpool`, a odczytuje `ai_feature` po powrocie do pętli
    zdarzeń. `anyio.to_thread.run_sync` kopiuje MAPĘ contextvarów, nie
    wartości — więc wątek roboczy i wołający trzymają TEN SAM obiekt i
    mutacja jest widoczna po obu stronach. Na tym stoi cały mechanizm.

    Sumujemy, nie nadpisujemy: jedna operacja bywa łańcuchem wywołań
    (mapa-redukcja transkryptu Championa, dwie próby sprawdzenia UoP,
    fallback na kolejny model). Rachunek dotyczy operacji, nie ostatniego
    round-tripu.
    """

    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, *, input_tokens: Optional[int], output_tokens: Optional[int]) -> None:
        """Dolicz jedno udane wywołanie. `None`/śmieci są ignorowane.

        Dostawca zwraca `usage` jako obiekt SDK, a przy nietypowej odpowiedzi
        pole potrafi być `None`. Telemetria nie ma prawa wywrócić wywołania,
        za które już zapłacono — dlatego tu nie ma miejsca na wyjątek.
        """
        for name, value in (
            ("input_tokens", input_tokens),
            ("output_tokens", output_tokens),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                continue
            if value > 0:
                setattr(self, name, getattr(self, name) + value)

    def any(self) -> bool:
        return self.input_tokens > 0 or self.output_tokens > 0


@dataclass(frozen=True)
class AiCallContext:
    feature: AIFeatureKey
    user_id: Optional[int]
    state: QuotaState
    # `frozen=True` zabrania PODMIANY atrybutu, nie mutacji obiektu, na który
    # wskazuje — więc akumulator może tu mieszkać bez odmrażania reszty.
    usage: TokenUsage = field(default_factory=TokenUsage)
    pending_responses: list[dict] = field(default_factory=list)


class AIQuotaUngated(RuntimeError):
    """An LLM call was made outside `async with ai_feature(...)`."""


def record_token_usage(
    *, input_tokens: Optional[int], output_tokens: Optional[int]
) -> None:
    """Dolicz tokeny do zadeklarowanej operacji AI, jeśli jakaś jest w zasięgu.

    Wołane z granicy dostawcy po UDANYM wywołaniu. Brak kontekstu to nie błąd:
    tak wygląda wywołanie niezadeklarowane, które ma własny detektor
    (`claude_client._assert_declared`) — dublowanie go tutaj zamieniłoby
    telemetrię w drugą bramkę.
    """
    context = _AI_CALL_CONTEXT.get()
    if context is None:
        return
    context.usage.add(input_tokens=input_tokens, output_tokens=output_tokens)


async def _persist_token_usage(context: "AiCallContext") -> None:
    """Retry buffered provider responses; idempotent by provider event ID."""
    if not context.pending_responses:
        return
    try:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            for event in context.pending_responses:
                await session.execute(
                    pg_insert(AIProviderCall).values(**event).on_conflict_do_nothing()
                )
            await session.commit()
        context.pending_responses.clear()
    except Exception:
        logger.critical(
            "ai-metering: usage remains unpersisted operation=%s",
            context.state.operation_id,
            exc_info=True,
        )


@asynccontextmanager
async def ai_feature(
    db: AsyncSession,
    feature: AIFeatureKey,
    *,
    user_id: Optional[int] = None,
    units: int = 1,
):
    """Admit and durably count an operation before calling the provider.

    Quota reads use the caller's session; the operation and provider responses
    use independent short transactions. No metering row is locked across AI.
    The context (including its accumulator) propagates into worker threads.
    """
    # Nested declarations of the SAME feature do not charge twice. A handler
    # may declare the call and then hand off to a service that declares it
    # again — one user action is one unit, and making the count depend on how
    # deep the call stack happens to be would be a quota that drifts with
    # refactors rather than with usage.
    active = _AI_CALL_CONTEXT.get()
    if active is not None and active.feature == feature:
        yield active.state
        return

    state = await check_and_increment(db, feature, user_id=user_id, units=units)
    context = AiCallContext(feature=feature, user_id=user_id, state=state)
    token = _AI_CALL_CONTEXT.set(context)
    try:
        yield state
    finally:
        _AI_CALL_CONTEXT.reset(token)
        # Tokeny dopisujemy PO zdjęciu kontekstu i we własnej sesji — patrz
        # `_persist_token_usage`. Zagnieżdżona deklaracja tej samej cechy
        # wychodzi wyżej (`return` przed tym blokiem), więc zapis robi
        # wyłącznie najbardziej zewnętrzny `ai_feature` i nie ma podwójnego
        # liczenia.
        await _persist_token_usage(context)


def current_ai_call() -> Optional[AiCallContext]:
    """The declared AI call in scope, if any."""
    return _AI_CALL_CONTEXT.get()


@contextmanager
def declared_call(
    feature: AIFeatureKey,
    *,
    user_id: Optional[int],
    state: QuotaState,
):
    """Zadeklaruj wywołanie AI, które zostało JUŻ naliczone gdzie indziej.

    Istnieje dla dokładnie jednego kształtu: handler nalicza kwotę i odsyła
    odpowiedź, a pieniądze wydaje `BackgroundTasks` PO jego zamknięciu —
    wtedy contextvar ustawiony przez `ai_feature` już nie żyje (`reset`
    w `finally`), więc bramka na granicy dostawcy widzi wywołanie jako
    niezadeklarowane. Dotyczy generacji CV B2B i CV próbnego reguł klienta.

    Rozważone i odrzucone: `contextvars.copy_context()` (Starlette nie
    wystawia `context=` dla `BackgroundTasks`) oraz parametr `declared_feature`
    w `call_claude` (przenosi deklarację do warstwy dostawcy i psuje własność
    „jest dokładnie jedna bramka, i to ona pyta o kontekst").

    **To jest z definicji „deklaruj bez płacenia", więc jedyne dopuszczalne
    użycie to `QuotaState` pochodzący z wcześniejszego `check_and_increment`
    dla TEJ SAMEJ operacji.** Wywołanie z wymyślonym stanem obchodzi sufit
    i główny wyłącznik — nie ma tu bramki, która by to złapała, bo cały sens
    tego prymitywu polega na jej braku. Bramka stoi w handlerze i tam ma
    zostać: odmowa w tle zostawiłaby wiersz „failed" zamiast czytelnego 503.

    Provider responses are persisted at the synchronous provider boundary,
    also for background jobs. A failed write is retried when leaving this scope.
    """
    context = AiCallContext(feature=feature, user_id=user_id, state=state)
    token = _AI_CALL_CONTEXT.set(context)
    try:
        yield
    finally:
        _AI_CALL_CONTEXT.reset(token)
        if context.pending_responses:
            from app.services.ai_metering import persist_response

            for event in context.pending_responses:
                if not persist_response(event):
                    logger.critical(
                        "ai-metering: background usage unpersisted event=%s",
                        event["event_key"],
                    )
