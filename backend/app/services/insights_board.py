"""Kokpit Rady (`/api/insights/board`) — liczenie bez warstwy HTTP (plan PR3).

Wyniesione z `app/api/insights_board.py` 23.09.2026, bo ma drugiego
konsumenta: miesięczny raport mailowy Rady (`tasks/kpi_email_reports.py`).
Dwie kopie tej arytmetyki rozjechałyby się przy pierwszej poprawce formuły —
router i raport wołają TĘ SAMĄ funkcję `compute_board`. Opis sześciu defektów
oryginału, których ten kod nie portuje, jest w docstringu routera.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analytics.periods import (
    ANALYTICS_TIMEZONE,
    Period,
    PeriodKind,
    resolve_period,
)
from app.models.contract import Contract
from app.services.contract_rates import (
    RATE_SCHEDULE_LOADS,
    REVENUE_BEARING_STATUSES,
)
from app.services.fx_service import rates_to_pln_by_date
from app.services.insights_board_money import (
    MONTH_LABELS_PL,
    fold_money,
    money,
    ratio,
    running_on,
)
from app.services.metric_definitions import (
    CLOSED_JOBS_WITH_PLACEMENT,
    FIRST_HIRED_PER_CANDIDATE_JOB,
)

logger = logging.getLogger(__name__)

# Ile miesięcy serii wraca w `trend`. 12 = pełny rok do porównania
# sezonowego; więcej i tak nie mieści się na wykresie rady.
TREND_MONTHS = 12

_TZ = ZoneInfo(ANALYTICS_TIMEZONE)

# Etykiety miesięcy po polsku, zamiast `strftime("%b")` — tamto zależy od
# locale kontenera, więc na prodzie i lokalnie potrafi dać różne napisy.


def _today_warsaw() -> date:
    return datetime.now(_TZ).date()


def _last_day_inside(period: Period) -> date:
    """Ostatni dzień NALEŻĄCY do okna.

    ``period.end`` to północ pierwszego dnia POZA oknem (półotwarte
    [start, end)), więc dzień wewnątrz to ``end`` minus doba.
    """
    return period.end.date() - timedelta(days=1)


def _finance_asof(period: Period, today: date) -> date:
    """Dzień, na który wyceniamy MRR w tym oknie.

    MRR to zdjęcie stanu, a nie suma za okres — trzeba wskazać dzień. Dla
    okna zamkniętego jest nim ostatni dzień okna (tak wyceniamy miniony
    miesiąc), dla okna trwającego — dzisiaj (bo ostatni dzień jeszcze nie
    nastąpił, a wycena na przyszłość udawałaby wiedzę o kontraktach, które
    do tego czasu mogą się skończyć). Okno w całości przyszłe wycenia się na
    swój pierwszy dzień: wynik będzie zwykle pusty, ale data pozostaje
    wewnątrz okna, którego dotyczy odpowiedź.
    """
    asof = min(_last_day_inside(period), today)
    return max(asof, period.start.date())


def _previous_period(period: Period) -> Period:
    """Poprzednie okno TEJ SAMEJ granulacji — mianownik porównania MoM.

    Dla okresów kalendarzowych kotwiczymy na pierwszym dniu bieżącego okna
    i cofamy o jedną jednostkę: arytmetyka granic (luty, kwartał, rok
    przestępny) zostaje w `periods.py`, zamiast być odejmowaniem 30 dni.
    Dla `custom` cofamy o dokładnie tę samą długość — innej definicji
    „poprzedniego" dla dowolnego zakresu nie ma.
    """
    if period.kind is PeriodKind.custom:
        span = period.end - period.start
        return Period(kind=period.kind, start=period.start - span, end=period.start)
    return resolve_period(period.kind, anchor=period.start.date(), offset=-1)


def _delta(current, previous) -> dict:
    """Porównanie dwóch liczb tej samej metryki, z jawną luką.

    ``change_pct`` jest ``None``, gdy poprzednia wartość to zero albo brak —
    wzrost „o nieskończoność" nie jest liczbą, a 0.0 czytałoby się jako „bez
    zmian".
    """
    if current is None or previous is None:
        return {
            "current": current,
            "previous": previous,
            "delta": None,
            "change_pct": None,
        }
    delta = current - previous
    return {
        "current": current,
        "previous": previous,
        "delta": round(delta, 2) if isinstance(delta, float) else delta,
        "change_pct": ratio(delta, previous) if previous else None,
    }


async def compute_board(
    db: AsyncSession, resolved: Period, *, today: Optional[date] = None
) -> dict:
    """Kokpit zarządu dla okna [start, end) — bez cache'u i bez bramek.

    Bramkę (`BoardReader`) i cache per okno trzyma router; raport mailowy
    liczy raz w miesiącu i cache'u nie potrzebuje.
    """
    today = today or _today_warsaw()
    previous = _previous_period(resolved)
    asof = _finance_asof(resolved, today)
    prev_asof = _finance_asof(previous, today)

    # ── Kamienie milowe w oknie ─────────────────────────────────────────────
    # `analytics_first_milestones` jest zdeduplikowane w definicji widoku
    # (rn = 1 per candidate_id × job_id × stage), więc dwa wiersze `hired` dla
    # tej samej pary liczą się RAZ. To jest kanoniczna definicja placementu
    # (D2) i nie wolno jej podmieniać na `count(candidate_stages)`.
    stage_rows = (
        (
            await db.execute(
                text(
                    """
                    SELECT fm.stage::text AS stage, count(*) AS cnt
                    FROM analytics_first_milestones fm
                    WHERE fm.first_reached_at >= :start
                      AND fm.first_reached_at < :end
                    GROUP BY 1
                    """
                ),
                {"start": resolved.start, "end": resolved.end},
            )
        )
        .mappings()
        .all()
    )
    counts = {row["stage"]: int(row["cnt"]) for row in stage_rows}
    placements = counts.get("hired", 0)

    prev_placements = int(
        (
            await db.execute(
                text(
                    """
                    SELECT count(*) AS cnt
                    FROM analytics_first_milestones fm
                    WHERE fm.stage::text = 'hired'
                      AND fm.first_reached_at >= :start
                      AND fm.first_reached_at < :end
                    """
                ),
                {"start": previous.start, "end": previous.end},
            )
        ).scalar()
        or 0
    )

    # ── Hit ratio: rekrutacje zamknięte w oknie, które skończyły się hire'em ─
    # Data ZAMKNIĘCIA jest w oknie, zatrudnienie liczy się kiedykolwiek —
    # ofertę zamkniętą w lipcu zwykle obsadzono wcześniej, a dopięcie
    # zatrudnienia do okna wycięłoby większość trafień i zaniżyło wskaźnik.
    hit_row = (
        (
            await db.execute(
                text(
                    """
                    SELECT
                      count(*) AS closed_total,
                      count(*) FILTER (WHERE filled.job_id IS NOT NULL)
                        AS closed_with_placement
                    FROM jobs j
                    LEFT JOIN LATERAL (
                      SELECT fm.job_id
                      FROM analytics_first_milestones fm
                      WHERE fm.job_id = j.id AND fm.stage::text = 'hired'
                      LIMIT 1
                    ) filled ON TRUE
                    WHERE j.status::text = 'closed'
                      AND j.closed_at >= :start
                      AND j.closed_at < :end
                    """
                ),
                {"start": resolved.start, "end": resolved.end},
            )
        )
        .mappings()
        .first()
    )
    jobs_closed = int(hit_row["closed_total"] or 0) if hit_row else 0
    jobs_closed_filled = int(hit_row["closed_with_placement"] or 0) if hit_row else 0

    # ── Seria 12 miesięcy ────────────────────────────────────────────────────
    months = [
        resolve_period("month", anchor=asof, offset=-i)
        for i in range(TREND_MONTHS - 1, -1, -1)
    ]
    trend_start = months[0].start
    trend_bucket_rows = (
        (
            await db.execute(
                text(
                    """
                    SELECT
                      to_char(
                        date_trunc(
                          'month',
                          fm.first_reached_at AT TIME ZONE 'Europe/Warsaw'
                        ),
                        'YYYY-MM'
                      ) AS bucket,
                      count(*) AS cnt
                    FROM analytics_first_milestones fm
                    WHERE fm.stage::text = 'hired'
                      AND fm.first_reached_at >= :start
                      AND fm.first_reached_at < :end
                    GROUP BY 1
                    """
                ),
                {"start": trend_start, "end": months[-1].end},
            )
        )
        .mappings()
        .all()
    )
    placements_by_month = {r["bucket"]: int(r["cnt"]) for r in trend_bucket_rows}

    # ── Kontrakty: JEDEN odczyt na całą odpowiedź ────────────────────────────
    # Stary board wykonywał osobne zapytanie na każdy z 12 miesięcy. Tu
    # ładujemy raz wszystko, co nachodzi na span serii (plus okno porównania,
    # które przy granulacji rocznej wychodzi poza 12 miesięcy), a wycenę
    # per dzień robi już `effective_rate_fields` na wczytanych harmonogramach.
    span_start = min(trend_start.date(), prev_asof)
    span_end = max(asof, prev_asof)
    contracts = (
        (
            await db.execute(
                select(Contract)
                .where(
                    Contract.status.in_(REVENUE_BEARING_STATUSES),
                    Contract.start_date.is_not(None),
                    Contract.start_date <= span_end,
                    or_(Contract.end_date.is_(None), Contract.end_date >= span_start),
                )
                .options(
                    selectinload(Contract.candidate),
                    # OBOWIĄZKOWE: bez tych trzech resolver stawek robi
                    # lazy-load w sesji async → MissingGreenlet → 500 bez CORS.
                    *RATE_SCHEDULE_LOADS,
                )
            )
        )
        .scalars()
        .all()
    )

    currencies = {
        currency
        for c in contracts
        for currency in (
            c.resolved_rate_client_currency,
            c.resolved_rate_candidate_currency,
        )
    }
    # Kursy na KAŻDY dzień wyceny naraz — jedno zapytanie zamiast N×M.
    valuation_dates = {asof, prev_asof} | {
        min(_last_day_inside(m), asof) for m in months
    }
    rates_by_date = await rates_to_pln_by_date(
        db, {d: currencies for d in valuation_dates}
    )

    current_fold = fold_money(
        running_on(contracts, asof), asof, rates_by_date.get(asof, {})
    )
    previous_fold = fold_money(
        running_on(contracts, prev_asof), prev_asof, rates_by_date.get(prev_asof, {})
    )

    missing_currencies: set = set(current_fold.missing_currencies) | set(
        previous_fold.missing_currencies
    )
    skipped_revenue = current_fold.skipped_revenue
    skipped_margin = current_fold.skipped_margin
    months_degraded: list = []

    trend_months: list = []
    for month in months:
        month_asof = min(_last_day_inside(month), asof)
        month_key = month.start.strftime("%Y-%m")
        fold = fold_money(
            running_on(contracts, month_asof),
            month_asof,
            rates_by_date.get(month_asof, {}),
        )
        missing_currencies |= set(fold.missing_currencies)
        if not fold.complete:
            months_degraded.append(month_key)
        trend_months.append(
            {
                "month": month_key,
                "label": f"{MONTH_LABELS_PL[month.start.month - 1]} {month.start.year}",
                # Dzień wyceny jest częścią odpowiedzi, bo bez niego nie da się
                # sprawdzić, dlaczego ostatni słupek różni się od kafla.
                "asof": month_asof.isoformat(),
                "placements": placements_by_month.get(month_key, 0),
                "revenue_monthly_pln": money(fold.revenue),
                "consultant_cost_monthly_pln": money(fold.cost),
                "margin_monthly_pln": money(fold.margin),
                "consultants": fold.consultants,
                "active_contracts": fold.active_contracts,
                "complete": fold.complete,
            }
        )

    degraded: Optional[dict] = None
    reasons: list = []
    if missing_currencies:
        reasons.append("fx_missing")
    if current_fold.without_cost_leg:
        reasons.append("cost_leg_missing")
    if reasons:
        message_parts: list = []
        if missing_currencies:
            # Podpowiedź MUSI zależeć od tego, gdzie leży luka. `refresh`
            # pobiera wyłącznie DZISIEJSZĄ tabelę NBP, więc na brakujące
            # miesiące historyczne nie działa — a to one wywołują ten
            # komunikat najczęściej (na produkcji: siedem kolejnych miesięcy
            # EUR przy kompletnym snapshocie na dziś). Podpowiedź, po której
            # nic się nie zmienia, uczy ignorować cały komunikat.
            waluty = ", ".join(sorted(missing_currencies))
            if months_degraded:
                fix = (
                    "uzupełnij historię: POST /api/fx/backfill?currency="
                    + sorted(missing_currencies)[0]
                )
            else:
                fix = "uzupełnij: POST /api/fx/refresh"
            message_parts.append(
                f"Brak kursu NBP dla walut: {waluty} — kwoty w tych walutach "
                f"są POMINIĘTE w sumach ({fix})."
            )
        if current_fold.without_cost_leg:
            message_parts.append(
                f"{current_fold.without_cost_leg} kontrakt(ów) bez stawki "
                "kandydata — ich marża jest nieznana i nie wchodzi do sumy."
            )
        degraded = {
            "reasons": reasons,
            # Liczniki mają WĘŻSZY zasięg niż lista walut i nazwy to mówią:
            # `kpi_*` opisuje wyłącznie kafel KPI (tam liczba kontraktów jest
            # policzalna), `currencies` zbiera całą odpowiedź (kafel +
            # porównanie + 12 miesięcy serii), a `months_affected` mówi, które
            # słupki są niepełne. Zsumowanie pominięć po dwunastu miesiącach
            # liczyłoby ten sam kontrakt dwanaście razy.
            "fx": {
                "currencies": sorted(missing_currencies),
                "kpi_contracts_excluded_from_revenue": skipped_revenue,
                "kpi_contracts_excluded_from_margin": skipped_margin,
                "months_affected": months_degraded,
            },
            "contracts_without_cost_leg": current_fold.without_cost_leg,
            "message": " ".join(message_parts),
        }
        logger.warning(
            "insights/board: degraded window=%s reasons=%s currencies=%s",
            resolved.cache_suffix,
            reasons,
            sorted(missing_currencies),
        )

    result = {
        "period": resolved.as_payload(),
        "kpis": {
            # Nazwa definicji jedzie w odpowiedzi, żeby konsument mógł ją
            # napisać na kaflu — trzy różne „placementy" w jednej aplikacji
            # to jest właśnie ta klasa pomyłki, którą D2 zamyka.
            "placements_definition": FIRST_HIRED_PER_CANDIDATE_JOB,
            "placements": placements,
            "verified": counts.get("verified", 0),
            "cv_sent": counts.get("cv_sent", 0),
            "interview": counts.get("interview", 0),
            "funnel_efficiency_pct": ratio(placements, counts.get("verified", 0)),
            "jobs_closed": jobs_closed,
            "jobs_closed_with_placement": jobs_closed_filled,
            # Definicja wypowiadalna jednym zdaniem — patrz docstring modułu p.2.
            "hit_ratio_pct": ratio(jobs_closed_filled, jobs_closed),
            "hit_ratio_definition": CLOSED_JOBS_WITH_PLACEMENT,
            "finance": {
                "asof": asof.isoformat(),
                "basis": "mrr_from_rate_schedules",
                "revenue_monthly_pln": money(current_fold.revenue),
                "consultant_cost_monthly_pln": money(current_fold.cost),
                "margin_monthly_pln": money(current_fold.margin),
                "margin_pct": ratio(current_fold.margin, current_fold.revenue),
                "active_consultants": current_fold.consultants,
                "active_contracts": current_fold.active_contracts,
                "priced_contracts": current_fold.priced_contracts,
                "contracts_without_cost_leg": current_fold.without_cost_leg,
                "complete": current_fold.complete,
            },
        },
        "trend": {"months": trend_months},
        "comparison": {
            "previous_period": previous.as_payload(),
            "previous_asof": prev_asof.isoformat(),
            "placements": _delta(placements, prev_placements),
            "revenue_monthly_pln": _delta(
                money(current_fold.revenue), money(previous_fold.revenue)
            ),
            "margin_monthly_pln": _delta(
                money(current_fold.margin), money(previous_fold.margin)
            ),
            "active_consultants": _delta(
                current_fold.consultants, previous_fold.consultants
            ),
            # Porównanie liczone z niekompletnych kwot jest porównaniem
            # niekompletnym — mówimy to wprost, zamiast pozwolić czytać deltę
            # jako fakt o biznesie.
            "complete": current_fold.complete and previous_fold.complete,
        },
        "degraded": degraded,
    }
    return result
