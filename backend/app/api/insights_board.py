"""Insights → Zarząd: dashboard rady na danych natywnych NEXUSA.

Następca `GET /api/reports/board` (`reports.py:1512`). Stary endpoint ZOSTAJE
nietknięty za `FinanceReadUser` — jest wołany spoza /insights i poszerzenie
jego guardu wyciekłoby P&L na powierzchnie, których właściciel nie otwierał.
Tutaj obowiązuje D7: KAŻDA zalogowana rola, bez redakcji kwot.

Sześć defektów oryginału, których ten moduł NIE portuje:

1. **Placement liczony jako każdy wiersz `candidate_stages` ze `stage='hired'`**
   (`reports.py:1642-1650`). `candidate_stages` nie ma UNIQUE na
   (candidate_id, job_id, stage), więc powrót kandydata do etapu albo drugie
   podejście procesowe liczyło się drugi raz. Kanoniczna definicja (D2) to
   PIERWSZE `hired` per para (kandydat, oferta) — czyli wiersz widoku
   `analytics_first_milestones`, gdzie deduplikacja jest częścią definicji
   widoku (`ROW_NUMBER() ... rn = 1`), a nie czymś, o czym trzeba pamiętać
   w każdym zapytaniu.

2. **`avg_hit_ratio` = `placements_ytd / COUNT(wszystkich ofert YTD)`**
   (`reports.py:1607`). To nie jest hit ratio niczego: licznik i mianownik
   opisują różne populacje (zatrudnienia w dowolnych ofertach vs oferty
   założone w tym roku), a wynik jest podpisany etykietą, której nie realizuje.
   Tutaj wskaźnik ma definicję, którą da się wypowiedzieć jednym zdaniem:
   ile procent rekrutacji ZAMKNIĘTYCH w oknie skończyło się zatrudnieniem.
   Data zamknięcia jest w oknie, a zatrudnienie liczy się kiedykolwiek —
   ofertę zamkniętą w lipcu zwykle obsadzono w czerwcu, więc dopięcie
   zatrudnienia do okna wycięłoby większość trafień.

3. **Przetargi** — poza zakresem decyzją właściciela. Zero pól `tender*`.
   Oryginalny `tender_win_rate` liczył „wygrane" jako oferty typu tender
   zamknięte z `priority IN (high, urgent)` (`reports.py:1621-1626`), co nie
   ma nic wspólnego z wygraniem przetargu — stąd trwałe 0%.

4. **Brak kursu NBP po cichu kasował pieniądze.** `_fold_finance_pln`
   (`reports.py:105-120`) robi `continue`, więc kwota wypada z sumy, a kafel
   obok pokazuje pewną liczbę; baner na dole strony tego nie cofa. Tutaj
   pominięcia są LICZONE i wracają w kopercie jako `degraded`, razem z listą
   walut — żeby zdegradować dało się sam kafel, nie stronę.

5. **Pieniądze z cache'owanych kolumn `contracts.rate_*`** (R5). Kolumna
   trzyma wartość z ostatniego ZAPISU kontraktu, więc stawka progresywna
   i aneks z datą, która już nadeszła, pokazują tu starą kwotę. Wszystko
   liczymy `effective_rate_fields` — tą samą funkcją, którą
   `api.contracts._effective_rate_fields` tylko aliasuje (importujemy ją
   z warstwy serwisowej, bo import `api.*` → `api.*` po to, żeby policzyć
   marżę, kończy się kopią funkcji i cichym rozjazdem).
   Konsekwencja operacyjna: `RATE_SCHEDULE_LOADS` jest OBOWIĄZKOWE przy
   każdym `select(Contract)` w tym pliku — bez tych trzech `selectinload`
   resolver robi lazy-load w sesji async, czyli `MissingGreenlet` → 500 bez
   nagłówków CORS, który front pokazuje jako „Network Error".

6. **Zero okna.** Stary klucz cache'u to stała `reports:board:v4-…`, a okres
   liczył się od 1 stycznia „do teraz" bez górnej granicy. Tutaj okno jest
   półotwarte [start, end) z `resolve_period`, a klucz cache'u niesie
   `period.cache_suffix` — inaczej liczby jednego okresu wyszłyby pod
   etykietą drugiego i nikt by się nie dowiedział, bo obie są wiarygodne.

Czego świadomie NIE ma:

* **`top_dl`** — oryginał brał „kto najczęściej kliknął `hired`"
  (`reports.py:1587-1602`), co mierzy operatora systemu, nie Delivery Leada.
  Uczciwa wersja wymaga `_compute_dl_metrics`, a ten helper przyjmuje wyłącznie
  `period_start` (okno bez górnej granicy) i mieszka w `reports.py`. Ranking DL
  ma dostać własny router (`/api/insights/delivery-leads`) razem z oknem;
  wstawianie tu liczby „na razie" byłoby portem defektu.
* **Zrealizowane przychody z `finance_monthly_results`** — plan (§Etap 6)
  wymaga ich jako DRUGIEGO, jawnie rozdzielonego źródła; dopasowanie idzie po
  wolnym tekście bez FK (`finance.py:192-194`), więc ma własny ciężar i własny
  wiersz „niedopasowane". Nie mieszamy go z MRR w jednej kolumnie i nie
  dokładamy tutaj po cichu.
"""

# UWAGA: BEZ `from __future__ import annotations`. Moduł UŻYWA `@limiter.limit`,
# a ten import zamieniłby `Annotated` w parametry Query (PEP 563 + slowapi #579)
# i poprawne żądanie dostawałoby 422.

import logging
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analytics.periods import (
    ANALYTICS_TIMEZONE,
    Period,
    PeriodError,
    PeriodKind,
    resolve_period,
)
from app.services.metric_definitions import (
    CLOSED_JOBS_WITH_PLACEMENT,
    FIRST_HIRED_PER_CANDIDATE_JOB,
)
from app.api.deps import CurrentUser
from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.core.cache import cache_get, cache_set
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.contract import Contract
from app.services.contract_rates import (
    RATE_SCHEDULE_LOADS,
    REVENUE_BEARING_STATUSES,
)
from app.services.insights_board_yoy import (
    DEFAULT_YEARS,
    MAX_YEARS,
    compute_board_yoy,
    resolve_years,
)
from app.services.insights_board_money import (
    MONTH_LABELS_PL,
    fold_money,
    money,
    ratio,
    running_on,
)
from app.services.fx_service import rates_to_pln_by_date

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)

CACHE_TTL_SECONDS = 300

# Siatka rok-do-roku opisuje ZAMKNIĘTE miesiące, które się już nie zmienią —
# jedynym ruchomym elementem jest miesiąc bieżący. Stąd TTL trzy razy dłuższy
# niż przy kaflach: to najdroższe zapytanie tej powierzchni.
YOY_CACHE_TTL_SECONDS = 900

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


def _resolve(kind: str, offset: int, anchor, date_from, date_to) -> Period:
    try:
        return resolve_period(
            kind, offset=offset, anchor=anchor, date_from=date_from, date_to=date_to
        )
    except PeriodError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


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


@router.get("/board")
# Najdroższy endpoint tej powierzchni: ładuje WSZYSTKIE kontrakty aktywne
# w 13-miesięcznym oknie z trzema eager-loadowanymi harmonogramami stawek,
# a potem liczy kursy NBP dla maks. 13 dat wyceny.
#
# Cache (5 min) jest per OKNO, więc nie broni: rotowanie `offset=-1,-2,-3…`
# albo dowolnego `date_from`/`date_to` generuje nowy klucz przy każdym żądaniu
# i omija go w całości. Po D7 endpoint jest otwarty dla każdej zalogowanej roli,
# więc próg musi stać na poziomie żądania, nie cache'u.
@limiter.limit("30/minute")
async def insights_board(
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", pattern="^(day|week|month|quarter|year|custom)$"),
    offset: int = Query(0, description="0 = bieżący okres, -1 = poprzedni zamknięty"),
    anchor: Optional[date] = Query(None, description="dowolny dzień wewnątrz okresu"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
):
    """Kokpit zarządu dla okna [start, end).

    D7: /insights jest jawnie otwarte dla KAŻDEJ zalogowanej roli (decyzja
    Artura 2026-08-31, plan §0 D7). Kwoty NIE są redagowane. Nie zastępuj tego
    guardu capability — `VIEW_FINANCE` steruje 40+ innymi powierzchniami
    (`app/analytics/capabilities.py:64-115`) i jego poszerzenie wyciekłoby
    stawki konsultantów daleko poza Insights.
    """
    resolved = _resolve(period, offset, anchor, date_from, date_to)
    previous = _previous_period(resolved)

    # Klucz NIESIE OKNO (`cache_suffix`). Stary board miał klucz stały, więc
    # dołożenie okresu bez zmiany klucza podałoby liczby jednego okna pod
    # etykietą drugiego. `v1` bumpujemy przy każdej zmianie formuły — inaczej
    # stara liczba wisi przez TTL pod nową etykietą.
    cache_key = f"insights:board:v1:{resolved.cache_suffix}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    today = _today_warsaw()
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
    await cache_set(cache_key, result, ttl_seconds=CACHE_TTL_SECONDS)
    return result


@router.get("/board/yoy")
# Najdroższy endpoint całej powierzchni: trzy lata × dwanaście miesięcy to 36
# wycen WSZYSTKICH kontraktów żywych w danym dniu, każda przez harmonogramy
# stawek. Dlatego TTL jest dłuższy niż przy kaflach (15 min zamiast 5): tabela
# opisuje zamknięte miesiące, które się już nie zmienią, a jedyny ruchomy
# element to miesiąc bieżący.
@limiter.limit("10/minute")
async def insights_board_yoy(
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    end_year: Optional[int] = Query(
        None, ge=2000, le=2100, description="ostatni rok siatki (domyślnie bieżący)"
    ),
    years: int = Query(
        DEFAULT_YEARS,
        ge=2,
        le=MAX_YEARS,
        description="ile lat wstecz łącznie z `end_year`",
    ),
):
    """Tabele rok-do-roku Rady: miesiąc × rok dla każdej metryki.

    Świadomie BEZ paska okresu — ta powierzchnia z definicji patrzy na pełne
    lata kalendarzowe, a wpuszczenie tu `period`/`offset` dałoby siatkę
    „ostatnie 12 miesięcy" podpisaną nazwami miesięcy, czyli dwie różne rzeczy
    pod jedną etykietą. Okno wybiera się latami.

    D7: KAŻDA zalogowana rola, bez redakcji kwot — jak reszta /insights.
    """
    resolved_years = resolve_years(end_year, years, _today_warsaw())
    # Klucz niesie LATA i dzień — bez daty siatka z wczoraj wisiałaby przez TTL
    # z wczorajszym miesiącem bieżącym.
    today = _today_warsaw()
    cache_key = (
        f"insights:board:yoy:v1:{resolved_years[0]}-{resolved_years[-1]}:{today}"
    )
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    result = await compute_board_yoy(db, resolved_years, today)
    await cache_set(cache_key, result, ttl_seconds=YOY_CACHE_TTL_SECONDS)
    return result
