"""Insights → Zarząd: dashboard rady na danych natywnych NEXUSA.

Następca `GET /api/reports/board`, usuniętego 15.09.2026 (liczył powtórne
zatrudnienia z surowych wierszy etapów i nie miał już konsumenta — audyt
statystyk 14.09). Numery linii `reports.py` niżej opisują kod sprzed usunięcia.
Dostęp: kokpit z kwotami — admin · finance (``BoardReader``); tabele
rok-do-roku — także Head of Recruitment, ale bez metryk pieniężnych
(``BoardTrendReader``, decyzja Artura 24.09.2026: HoR nie widzi pieniędzy).

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
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import (
    Period,
    PeriodError,
    resolve_period,
)
from app.api.deps import BoardReader, BoardTrendReader
from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.core.cache import cache_get, cache_set, cache_single_flight
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.user import UserRole
from app.services.insights_board_yoy import (
    DEFAULT_YEARS,
    MAX_YEARS,
    compute_board_yoy,
    resolve_years,
    without_money,
)
from app.services.insights_board import _today_warsaw, compute_board

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)

CACHE_TTL_SECONDS = 300

# Siatka rok-do-roku opisuje ZAMKNIĘTE miesiące, które się już nie zmienią —
# jedynym ruchomym elementem jest miesiąc bieżący. Stąd TTL trzy razy dłuższy
# niż przy kaflach: to najdroższe zapytanie tej powierzchni.
YOY_CACHE_TTL_SECONDS = 900


def _resolve(kind: str, offset: int, anchor, date_from, date_to) -> Period:
    try:
        return resolve_period(
            kind, offset=offset, anchor=anchor, date_from=date_from, date_to=date_to
        )
    except PeriodError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("/board")
# Najdroższy endpoint tej powierzchni: ładuje WSZYSTKIE kontrakty aktywne
# w 13-miesięcznym oknie z trzema eager-loadowanymi harmonogramami stawek,
# a potem liczy kursy NBP dla maks. 13 dat wyceny.
#
# Cache (5 min) jest per OKNO, więc nie broni: rotowanie `offset=-1,-2,-3…`
# albo dowolnego `date_from`/`date_to` generuje nowy klucz przy każdym żądaniu
# i omija go w całości. Próg stoi na poziomie żądania, nie cache'u — także
# po zawężeniu dostępu do Rady (21.09.2026) konto z dostępem może go ominąć.
@limiter.limit("30/minute")
async def insights_board(
    request: Request,
    current_user: BoardReader,
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", pattern="^(day|week|month|quarter|year|custom)$"),
    offset: int = Query(0, description="0 = bieżący okres, -1 = poprzedni zamknięty"),
    anchor: Optional[date] = Query(None, description="dowolny dzień wewnątrz okresu"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
):
    """Kokpit zarządu dla okna [start, end).

    Widok Firma: tylko admin · finance (``BoardReader``, decyzja Artura
    24.09.2026 — Head of Recruitment nie widzi pieniędzy). Kwoty NIE są
    redagowane. Nie zastępuj tego guardu
    capability — `VIEW_FINANCE` steruje 40+ innymi powierzchniami
    (`app/analytics/capabilities.py:64-115`), a HoR go nie ma.
    """
    resolved = _resolve(period, offset, anchor, date_from, date_to)

    # Klucz NIESIE OKNO (`cache_suffix`). Stary board miał klucz stały, więc
    # dołożenie okresu bez zmiany klucza podałoby liczby jednego okna pod
    # etykietą drugiego. `v1` bumpujemy przy każdej zmianie formuły — inaczej
    # stara liczba wisi przez TTL pod nową etykietą.
    # v2 + dzień (runda 6 audytu): placementy okresu w toku porównujemy z tym
    # samym odcinkiem poprzedniego okresu, a ten odcinek rośnie z każdym dniem.
    today = _today_warsaw()
    cache_key = f"insights:board:v2:{resolved.cache_suffix}:{today.isoformat()}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    result = await compute_board(db, resolved, today=today)
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
    current_user: BoardTrendReader,
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

    Admin · finance · Head of Recruitment (``BoardTrendReader``). Head of
    Recruitment dostaje odpowiedź BEZ metryk pieniężnych (decyzja Artura
    24.09.2026) — redakcja na gotowym wyniku, cache jeden dla wszystkich.
    """
    resolved_years = resolve_years(end_year, years, _today_warsaw())
    # Klucz niesie LATA i dzień — bez daty siatka z wczoraj wisiałaby przez TTL
    # z wczorajszym miesiącem bieżącym.
    today = _today_warsaw()
    cache_key = (
        f"insights:board:yoy:v1:{resolved_years[0]}-{resolved_years[-1]}:{today}"
    )
    result = await cache_get(cache_key)
    if result is None:
        # Jeden wykonawca (runda 7, R7-N10-6): dwa równoległe wejścia admina
        # i Finansów liczyły wcześniej 60 wycen wszystkich kontraktów dwa razy.
        async with cache_single_flight(cache_key, db=db):
            result = await cache_get(cache_key)
            if result is None:
                result = await compute_board_yoy(db, resolved_years, today)
                await cache_set(cache_key, result, ttl_seconds=YOY_CACHE_TTL_SECONDS)
    if current_user.has_any_role(UserRole.admin, UserRole.finance):
        return result
    return without_money(result)
