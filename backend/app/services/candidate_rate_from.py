"""„Stawka od” — najniższa stawka kandydata z ostatnich 18 miesięcy.

Decyzje Artura 04.10.2026: kandydat podaje różne stawki na różne role, a AI
i filtry nie mogą chować go przed rekrutacją, na którą kiedyś zgodził się za
mniej. Reguła (czysta funkcja :func:`compute`):

1. Obserwacja = stawka PLN/h netto z datą (``candidate_rate_observations``).
   Zakres liczy się dolną granicą; inna waluta albo jednostka nie liczy się.
2. Okno: ostatnie 18 miesięcy.
3. Jawne minimum (telefon praktykanta, „Ustaw minimum”, checkbox przy
   „Zweryfikowany”) unieważnia starsze, niższe stawki.
4. „Nie licz jako minimum” rekrutera wyłącza jedną obserwację. Odstających
   nie wykluczamy automatycznie.
5. Wynik = minimum z tego, co zostało; bez obserwacji w oknie — ostatnia
   znana stawka z oznaczeniem ``stale``.

Czytelnicy NIE sięgają po ``expected_rate_hourly`` ani ``rate_from_hourly``
wprost — tylko przez :func:`effective_rate` / :func:`effective_rate_sql`
(pilnuje ``tests/test_rate_from_readers_guard.py``). Przed pierwszym
przeliczeniem kandydata i przy wyłączonej fladze obowiązuje stawka profilu.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import case, literal, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from zoneinfo import ZoneInfo

from app.core.scheduling import DEFAULT_TZ, business_today
from app.services.candidate_rate_observations import RateObservation, collect

logger = logging.getLogger(__name__)

RATE_FROM_WINDOW_MONTHS = 18

# Powód, dla którego obserwacja liczy się albo nie liczy do minimum.
REASON_MINIMUM = "minimum"
REASON_COUNTS = "counts"
REASON_EXCLUDED = "excluded"
REASON_OUTSIDE_WINDOW = "outside_window"
REASON_SUPERSEDED = "superseded"
REASON_NOT_COMPARABLE = "not_comparable"


def enabled() -> bool:
    return bool(getattr(settings, "CANDIDATE_RATE_FROM_ENABLED", True))


def window_start(today: date) -> date:
    """Pierwszy dzień okna: ``today`` minus 18 miesięcy (koniec miesiąca przycięty)."""
    month_index = today.year * 12 + (today.month - 1) - RATE_FROM_WINDOW_MONTHS
    year, month = divmod(month_index, 12)
    month += 1
    for day in range(today.day, 0, -1):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return date(year, month, 1)  # pragma: no cover


def _day(value: Optional[datetime]) -> Optional[date]:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(ZoneInfo(DEFAULT_TZ)).date()
    return value.date()


@dataclass
class RateFrom:
    amount: Optional[Decimal]
    at: Optional[datetime]
    source: Optional[str]
    job_id: Optional[int]
    key: Optional[str]
    stale: bool
    reasons: dict[str, str] = field(default_factory=dict)
    #: Ostatnio podana porównywalna stawka (bez wyłączonych) i ich liczba.
    latest_amount: Optional[Decimal] = None
    latest_at: Optional[datetime] = None
    count: int = 0


def _sort_key(obs: RateObservation) -> tuple:
    at = obs.at or datetime.min.replace(tzinfo=timezone.utc)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return (at, obs.key)


def compute(
    observations: Iterable[RateObservation],
    excluded_keys: Iterable[str],
    today: date,
) -> RateFrom:
    excluded = set(excluded_keys)
    start = window_start(today)
    reasons: dict[str, str] = {}
    usable: list[RateObservation] = []
    for obs in observations:
        if obs.amount_hourly is None or obs.not_comparable:
            reasons[obs.key] = REASON_NOT_COMPARABLE
        elif obs.key in excluded:
            reasons[obs.key] = REASON_EXCLUDED
        else:
            usable.append(obs)

    in_window = [o for o in usable if (_day(o.at) or date.min) >= start]
    for obs in usable:
        if obs not in in_window:
            reasons[obs.key] = REASON_OUTSIDE_WINDOW

    minimums = sorted((o for o in in_window if o.explicit_minimum), key=_sort_key)
    eligible = in_window
    if minimums:
        floor = minimums[-1]
        floor_key = _sort_key(floor)
        eligible = []
        for obs in in_window:
            if _sort_key(obs) < floor_key and obs.amount_hourly < floor.amount_hourly:
                reasons[obs.key] = REASON_SUPERSEDED
            else:
                eligible.append(obs)

    latest = max(usable, key=_sort_key) if usable else None
    summary = {
        "reasons": reasons,
        "latest_amount": latest.amount_hourly if latest else None,
        "latest_at": latest.at if latest else None,
        "count": len(usable),
    }

    if eligible:
        # Najniższa kwota; przy remisie najnowsza (jej data opisuje „od kiedy”).
        newest_first = sorted(eligible, key=_sort_key, reverse=True)
        best = min(newest_first, key=lambda o: o.amount_hourly)
        for obs in eligible:
            reasons[obs.key] = REASON_COUNTS
        reasons[best.key] = REASON_MINIMUM
        return RateFrom(
            amount=best.amount_hourly,
            at=best.at,
            source=best.source,
            job_id=best.job_id,
            key=best.key,
            stale=False,
            **summary,
        )

    if latest is not None:
        # Nic w oknie: ostatnia znana stawka, oznaczona jako nieaktualna.
        reasons[latest.key] = REASON_MINIMUM
        return RateFrom(
            amount=latest.amount_hourly,
            at=latest.at,
            source=latest.source,
            job_id=latest.job_id,
            key=latest.key,
            stale=True,
            **summary,
        )
    return RateFrom(None, None, None, None, None, False, **summary)


# ── Czytanie efektywnej stawki ──────────────────────────────────────────────


def effective_rate(candidate: Any) -> tuple[Optional[Decimal], Optional[str]]:
    """``(kwota, waluta)`` stawki, którą czytają filtry, AI i plakietki.

    Po przeliczeniu: „Stawka od” (zawsze PLN, także ``None`` = brak stawki).
    Przed przeliczeniem albo przy wyłączonej fladze: stawka profilu z walutą,
    którą wołający interpretuje jak dotąd.
    """
    if enabled() and getattr(candidate, "rate_from_computed_at", None) is not None:
        amount = getattr(candidate, "rate_from_hourly", None)
        return (amount, "PLN" if amount is not None else None)
    return (
        getattr(candidate, "expected_rate_hourly", None),
        getattr(candidate, "expected_rate_currency", None),
    )


def effective_rate_at(candidate: Any) -> Optional[datetime]:
    """Kiedy kandydat OSTATNIO podał stawkę (do „stawka nieaktualna”).

    Data najnowszej stawki, nie najniższej — minimum sprzed 10 miesięcy przy
    stawce potwierdzonej tydzień temu nie jest „nieaktualną stawką”.
    """
    if enabled() and getattr(candidate, "rate_from_computed_at", None) is not None:
        return getattr(candidate, "rate_latest_at", None)
    return getattr(candidate, "profile_rate_updated_at", None)


def effective_rate_sql(model: Any):  # type: ignore[no-untyped-def]
    """SQL-owe lustro :func:`effective_rate` — kolumna kwoty."""
    if not enabled():
        return model.expected_rate_hourly
    return case(
        (model.rate_from_computed_at.is_not(None), model.rate_from_hourly),
        else_=model.expected_rate_hourly,
    )


def effective_currency_sql(model: Any):  # type: ignore[no-untyped-def]
    """SQL-owe lustro :func:`effective_rate` — kolumna waluty."""
    if not enabled():
        return model.expected_rate_currency
    return case(
        (model.rate_from_computed_at.is_not(None), literal("PLN")),
        else_=model.expected_rate_currency,
    )


def effective_rate_raw_sql(alias: str = "c") -> str:
    """To samo dla surowego SQL-a (``text()``) — kwota."""
    if not enabled():
        return f"{alias}.expected_rate_hourly"
    return (
        f"(CASE WHEN {alias}.rate_from_computed_at IS NOT NULL "
        f"THEN {alias}.rate_from_hourly ELSE {alias}.expected_rate_hourly END)"
    )


def effective_rate_at_raw_sql(alias: str = "c") -> str:
    if not enabled():
        return f"{alias}.profile_rate_updated_at"
    return (
        f"(CASE WHEN {alias}.rate_from_computed_at IS NOT NULL "
        f"THEN {alias}.rate_latest_at ELSE {alias}.profile_rate_updated_at END)"
    )


def rate_summary(candidate: Any) -> dict[str, Any]:
    """Pola „Stawki od” w odpowiedziach API (lista, podgląd, propozycje).

    Przed przeliczeniem kandydata albo przy wyłączonej fladze: stawka profilu
    (tylko PLN — inna waluta nie jest porównywalna) i brak historii.
    """
    computed = (
        enabled() and getattr(candidate, "rate_from_computed_at", None) is not None
    )
    amount, currency = effective_rate(candidate)
    if str(currency or "PLN").strip().upper() not in {"", "PLN"}:
        amount = None
    return {
        "rate_from_hourly": amount,
        "rate_from_at": getattr(candidate, "rate_from_at", None) if computed else None,
        "rate_from_stale": bool(getattr(candidate, "rate_from_stale", False))
        if computed
        else False,
        "rate_latest_hourly": getattr(candidate, "rate_latest_hourly", None)
        if computed
        else None,
        "rate_latest_at": getattr(candidate, "rate_latest_at", None)
        if computed
        else None,
        "rate_observation_count": getattr(candidate, "rate_observation_count", None)
        if computed
        else None,
    }


async def this_job_rates(
    db: AsyncSession, job_id: int, candidate_ids: Iterable[int]
) -> dict[int, dict[str, Any]]:
    """Stawka podana w TEJ rekrutacji (karta albo okno „Zweryfikowany”).

    Najnowsza porównywalna obserwacja z ``job_id`` — do „W tej rekrutacji”
    obok „Stawki od” (decyzja Artura 04.10.2026). Brak = kandydata o tę rolę
    nie pytano.
    """
    observations = await collect(db, candidate_ids)
    out: dict[int, dict[str, Any]] = {}
    for cid, items in observations.items():
        same_job = [
            o
            for o in items
            if o.job_id == job_id
            and o.amount_hourly is not None
            and not o.not_comparable
        ]
        if not same_job:
            continue
        newest = max(same_job, key=_sort_key)
        out[cid] = {
            "amount": newest.amount_hourly,
            "raw": newest.raw,
            "at": newest.at,
            "source": newest.source,
        }
    return out


# ── Przeliczenie ────────────────────────────────────────────────────────────


def _same_moment(a: Optional[datetime], b: Optional[datetime]) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    return abs((a - b).total_seconds()) < 1


def _same_amount(a: Optional[Decimal], b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return Decimal(str(a)).quantize(Decimal("0.01")) == Decimal(str(b)).quantize(
        Decimal("0.01")
    )


@dataclass(frozen=True)
class RateDecision:
    key: str
    observed_amount: Optional[Decimal]
    observed_at: Optional[datetime]
    decided_by: Optional[int]


async def load_decisions(
    db: AsyncSession, candidate_ids: Iterable[int]
) -> dict[int, list[RateDecision]]:
    ids = sorted({int(c) for c in candidate_ids})
    out: dict[int, list[RateDecision]] = {cid: [] for cid in ids}
    if not ids:
        return out
    rows = await db.execute(
        text(
            "SELECT candidate_id, observation_key, observed_amount, observed_at, "
            "decided_by FROM candidate_rate_decisions "
            "WHERE candidate_id = ANY(:ids) AND decision = 'exclude'"
        ),
        {"ids": ids},
    )
    for cid, key, amount, at, by in rows.all():
        out.setdefault(cid, []).append(RateDecision(key, amount, at, by))
    return out


def active_exclusions(
    observations: Iterable[RateObservation], decisions: Iterable[RateDecision]
) -> dict[str, Optional[int]]:
    """Klucze wyłączone z minimum → kto wyłączył.

    Decyzja dotyczy KONKRETNEJ stawki (kwota + data), nie klucza: karta
    przelicza swoje pole przy każdej nowej notatce, a „bieżąca stawka profilu”
    zmienia się z formularza i scalania — nowa wartość pod tym samym kluczem
    znowu liczy się do minimum (przegląd kodu 04.10.2026).
    """
    by_key = {d.key: d for d in decisions}
    out: dict[str, Optional[int]] = {}
    for obs in observations:
        decision = by_key.get(obs.key)
        if decision is None:
            continue
        if _same_amount(obs.amount_hourly, decision.observed_amount) and _same_moment(
            obs.at, decision.observed_at
        ):
            out[obs.key] = decision.decided_by
    return out


_UPDATE_SQL = text(
    "UPDATE candidates SET rate_from_hourly = :amount, rate_from_at = :at, "
    "rate_from_source = :source, "
    "rate_from_job_id = (SELECT id FROM jobs WHERE id = :job_id), "
    "rate_from_stale = :stale, rate_from_computed_at = now(), "
    "rate_latest_hourly = :latest, rate_latest_at = :latest_at, "
    "rate_observation_count = :count "
    "WHERE id = :id"
)


async def recompute(
    db: AsyncSession,
    candidate_ids: Iterable[int],
    *,
    today: Optional[date] = None,
    skip_locked: bool = False,
) -> list[int]:
    """Przelicz „Stawkę od” i zdejmij kandydatów z kolejki. Zwraca zmienionych.

    Kolejność jest ważna (przegląd kodu 04.10.2026, wyścig z równoległym
    zapisem): najpierw blokada wierszy kandydatów, potem odczyt wpisów kolejki
    (z datą), dopiero potem obserwacje. Z kolejki znika wyłącznie wpis z datą
    przeczytaną tutaj — zmiana zapisana w trakcie podbija datę (wyzwalacz)
    i zostaje do przeliczenia. Pętla (``skip_locked``) pomija kandydatów
    zablokowanych przez żądanie i nigdy na nic nie czeka — bez zakleszczeń.

    Zapis surowym SQL-em — ``updated_at`` zostaje nietknięte (alerty
    zapisanych wyszukiwań czytają tę datę jako „kandydat się zmienił”).
    """
    ids = sorted({int(c) for c in candidate_ids})
    if not ids:
        return []
    today = today or business_today()
    lock = "FOR NO KEY UPDATE SKIP LOCKED" if skip_locked else "FOR NO KEY UPDATE"
    locked = (
        await db.execute(
            text(
                "SELECT id, rate_from_hourly, rate_from_computed_at FROM candidates "
                f"WHERE id = ANY(:ids) ORDER BY id {lock}"
            ),
            {"ids": ids},
        )
    ).all()
    before = {row[0]: (row[1], row[2]) for row in locked}
    ids = sorted(before)
    if not ids:
        return []
    queued = (
        await db.execute(
            text(
                "SELECT candidate_id, queued_at FROM candidate_rate_from_queue "
                "WHERE candidate_id = ANY(:ids)"
            ),
            {"ids": ids},
        )
    ).all()
    observations = await collect(db, ids)
    decisions = await load_decisions(db, ids)
    changed: list[int] = []
    params = []
    for cid in ids:
        items = observations.get(cid, [])
        excluded = active_exclusions(items, decisions.get(cid, []))
        result = compute(items, set(excluded), today)
        params.append(
            {
                "id": cid,
                "amount": result.amount,
                "at": result.at,
                "source": result.source,
                "job_id": result.job_id,
                "stale": result.stale,
                "latest": result.latest_amount,
                "latest_at": result.latest_at,
                "count": result.count,
            }
        )
        old_amount, old_computed = before[cid]
        if old_computed is None or old_amount != result.amount:
            changed.append(cid)
    if params:
        await db.execute(_UPDATE_SQL, params)
    if queued:
        await db.execute(
            text(
                "DELETE FROM candidate_rate_from_queue WHERE candidate_id IN ("
                "SELECT q.candidate_id FROM candidate_rate_from_queue q "
                "JOIN unnest(CAST(:qids AS integer[]), CAST(:qts AS timestamptz[])) "
                "AS c(id, ts) ON q.candidate_id = c.id AND q.queued_at = c.ts "
                "FOR UPDATE OF q SKIP LOCKED)"
            ),
            {"qids": [row[0] for row in queued], "qts": [row[1] for row in queued]},
        )
    if changed:
        from app.services.match_score_cache import mark_stale_for_candidates

        await mark_stale_for_candidates(db, changed)
    return changed


async def recompute_safely(db: AsyncSession, candidate_ids: Iterable[int]) -> None:
    """Przeliczenie w ścieżce zapisu użytkownika — nigdy nie cofa jego zapisu.

    Błąd zostaje w kolejce (wyzwalacz już dopisał kandydata), więc dokończy
    go pętla ``candidate_rate_from``.
    """
    if not enabled():
        return
    try:
        async with db.begin_nested():
            await recompute(db, candidate_ids)
    except Exception as exc:  # noqa: BLE001 — zapis użytkownika ważniejszy
        logger.warning("rate_from recompute failed (%s)", type(exc).__name__)


async def requeue_expiring(db: AsyncSession, *, today: Optional[date] = None) -> int:
    """Kandydaci, których minimum wypadło z okna 18 miesięcy — do przeliczenia.

    Okno przesuwa się z każdym dniem, a wyzwalacze reagują tylko na zmiany
    danych. Bez tego stara niska stawka zostawałaby „Stawką od” na zawsze,
    a historia stawek (liczona na żywo) pokazywałaby co innego niż profil.
    """
    start = window_start(today or business_today())
    result = await db.execute(
        text(
            "INSERT INTO candidate_rate_from_queue (candidate_id, queued_at) "
            "SELECT id, clock_timestamp() FROM candidates "
            "WHERE rate_from_computed_at IS NOT NULL AND NOT rate_from_stale "
            "AND rate_from_at < :start "
            "ON CONFLICT (candidate_id) DO NOTHING"
        ),
        {"start": datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)},
    )
    return result.rowcount or 0


async def process_queue(db: AsyncSession, *, limit: int = 500) -> int:
    """Jedna paczka kolejki; zwraca liczbę przeliczonych kandydatów.

    Wpisy czytamy bez blokady — o pominięciu zablokowanych kandydatów
    decyduje ``recompute(skip_locked=True)``; pominięci zostają w kolejce.
    """
    rows = await db.execute(
        text(
            "SELECT candidate_id FROM candidate_rate_from_queue "
            "ORDER BY queued_at, candidate_id LIMIT :limit"
        ),
        {"limit": limit},
    )
    ids = [row[0] for row in rows.all()]
    if not ids:
        return 0
    await recompute(db, ids, skip_locked=True)
    return len(ids)
