"""Insights → Klienci / MRR: ranking klientów i skuteczność per klient.

D7: /insights jest jawnie otwarte dla KAŻDEJ zalogowanej roli (decyzja Artura
2026-08-31, plan §0 D7). Kwoty NIE są tu redagowane. Nie zastępuj guardu
``CurrentUser`` żadną capability — ``VIEW_FINANCE`` steruje 40+ innymi
powierzchniami (``analytics/capabilities.py:64-115``) i jego poszerzenie
wyciekłoby stawki konsultantów daleko poza Insights.

Dlaczego to jest NOWY router, a nie poszerzony guard istniejącego:

* ``/api/admin/clients-overview`` jest współdzielony z portalem DL
  (``frontend/src/lib/api/dlPortal.ts``) i stoi na ``FinanceReadUser``.
  Poszerzenie go otworzyłoby także TAMTĄ powierzchnię.
* ``/api/reports/clients`` jest współdzielony z profilem klienta
  (``frontend/src/app/clients/[id]/page.tsx``) i stoi na czterech rolach.

Liczenie nie jest tu kopiowane — mieszka w ``app/services/insights_clients.py``
i zasila OBIE powierzchnie. Cztery reguły, które ten moduł utrzymuje:

1. **Pieniądze z HARMONOGRAMÓW stawek**, nigdy z kolumn ``contracts.rate_*``
   (te niosą kwotę z ostatniego ZAPISU kontraktu). Szczegóły i pułapka
   ``MissingGreenlet`` — w docstringu serwisu.
2. **Placement = D2**: pierwsze ``hired`` per para (kandydat, oferta).
3. **Okno półotwarte [start, end)** z ``resolve_period``; klucz cache'u niesie
   to okno, inaczej liczby jednego okresu wyszłyby pod etykietą drugiego.
4. **Kafle to fold po TEJ SAMEJ liście**, którą zwraca endpoint — kafel będący
   sumą innych liczb niż widoczne pod nim nie daje się zweryfikować wzrokiem.
"""

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import (
    Period,
    PeriodError,
    PeriodKind,
    resolve_period,
)
from app.api.deps import CurrentUser
from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.core.cache import cache_get, cache_set
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.job import JobCloseReason
from app.schemas.money import to_whole_pln
from app.services.insights_clients import (
    ClientHitRatioRow,
    ClientRankingRow,
    compute_client_hit_ratio,
    compute_client_ranking,
    fold_hit_ratio_totals,
    fold_ranking_totals,
    ratio_pct,
)
from app.services.insights_hiring_managers import compute_hiring_manager_kpis

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)

CACHE_TTL_SECONDS = 300


def _resolve(
    kind: str,
    offset: int,
    anchor: date | None,
    date_from: date | None,
    date_to: date | None,
) -> Period:
    try:
        return resolve_period(
            kind, offset=offset, anchor=anchor, date_from=date_from, date_to=date_to
        )
    except PeriodError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


def _valuation_date(period: Period, today: date | None = None) -> date:
    """Dzień, na który wyceniamy stawki i kursy: ostatni dzień okna lub dziś.

    Okno jest półotwarte, więc ostatni dzień NALEŻĄCY do okresu to ``end - 1``.
    Przyszłość przycinamy do dziś: przyszłych kursów NBP nie ma, a wycena kroku
    harmonogramu, który jeszcze nie obowiązuje, pokazywałaby marżę, której nikt
    dziś nie fakturuje.

    „Dziś" bierzemy z `business_today()`, czyli z kalendarza Europe/Warsaw —
    TEGO SAMEGO, w którym `resolve_period` liczy granice okna. `date.today()`
    czyta zegar kontenera (na prodzie UTC), a między północą UTC a północą
    warszawską obie odpowiedzi się różnią. W tym oknie `min(last_day, today)`
    przycinał BIEŻĄCY i POPRZEDNI okres do tej samej daty, więc ranking
    bieżącego miesiąca wyceniał się ostatnim dniem miesiąca poprzedniego —
    innym krokiem harmonogramu i innym kursem NBP. Objaw jest cichy: liczba
    jest prawidłowa, tylko opisuje inny dzień.

    ``today`` jest wstrzykiwalne wyłącznie po to, żeby dało się przypiąć zegar
    w teście — spójnie z `resolve_period(now=...)` i `business_today()`.
    """
    last_day = (period.end - timedelta(days=1)).date()
    return min(last_day, today if today is not None else business_today())


def _money(value) -> int | None:
    """Kwota w PEŁNYCH złotych albo ``None``.

    Zaokrąglenie idzie na SKŁADNIKACH, nigdy na sumie — suma zaokrągleń nie
    równa się zaokrągleniu sumy, więc kafel liczony z surowych ``Decimal``
    różniłby się od sumy kolumny pod nim o złotówki (``app/schemas/money.py``).
    """
    if value is None:
        return None
    return to_whole_pln(value)


def _ranking_payload(row: ClientRankingRow) -> dict:
    # Nazwy pól są celowo lustrem ``OverviewRow`` — front podnosi
    # ``ClientsRanking.tsx`` 1:1 (plan §Etap 5) i nie ma tu czego przemapowywać.
    return {
        "client_id": row.client_id,
        "name": row.name,
        "industry": row.industry,
        "head_dl_id": row.head_dl_id,
        "head_dl_name": row.head_dl_name,
        "total_revenue_all_time": _money(row.total_revenue_all_time),
        "active_revenue": _money(row.active_revenue),
        "monthly_margin_total": _money(row.monthly_margin_total),
        "active_orders_count": row.active_orders_count,
        "active_consultants": row.active_consultants,
        "active_contracts": row.active_contracts,
        "framework_status": row.framework_status,
        "framework_expiry_date": row.framework_expiry_date.isoformat()
        if row.framework_expiry_date
        else None,
        # Brak kursu NBP kasuje kwotę z sumy po cichu — konsument musi móc
        # odróżnić „zero marży" od „nie policzyliśmy".
        "revenue_complete": row.revenue_complete,
        "margin_complete": row.margin_complete,
    }


def _hit_ratio_payload(row: ClientHitRatioRow) -> dict:
    return {
        "client_id": row.client_id,
        "client_name": row.client_name,
        "client_status": row.client_status,
        "closed_jobs": row.closed_jobs,
        "filled_jobs": row.filled_jobs,
        "lost_jobs": row.lost_jobs,
        "total_vacancies": row.total_vacancies,
        "placements": row.placements,
        "hit_ratio": row.hit_ratio,
        "fill_rate": row.fill_rate,
        "active_jobs": row.active_jobs,
        "target_achieved": row.target_achieved,
        "close_reasons": dict(row.close_reasons),
    }


@router.get("/ranking")
async def insights_clients_ranking(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", pattern="^(day|week|month|quarter|year|custom)$"),
    offset: int = Query(0, description="0 = bieżący okres, -1 = poprzedni zamknięty"),
    anchor: date | None = Query(None, description="dowolny dzień wewnątrz okresu"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
):
    """Ranking klientów: przychód lifetime, aktywne MRR, marża/mc, Head DL.

    Dostępne dla KAŻDEGO zalogowanego (decyzja D7).

    Okres steruje wyłącznie DNIEM WYCENY — którym krokiem harmonogramu stawek
    i którym kursem NBP liczymy marżę. Zbiór kontraktów to zawsze dzisiejsze
    umowy żywe (``active``/``ending``), bo „aktywny konsultant" musi znaczyć na
    tym ekranie to samo, co na profilu klienta i w portalu DL. Przychód
    ``total_revenue_all_time`` jest z definicji lifetime — okno go nie przycina.
    """
    resolved = _resolve(period, offset, anchor, date_from, date_to)
    on = _valuation_date(resolved)

    # Klucz NIESIE OKNO. Bez tego marża wyceniona na lipiec wyszłaby pod
    # etykietą sierpnia i nikt by się nie zorientował — obie liczby są
    # wiarygodne.
    cache_key = f"insights:clients:ranking:v1:{resolved.cache_suffix}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    rows = await compute_client_ranking(db, on=on)
    clients = [_ranking_payload(r) for r in rows]
    totals = fold_ranking_totals(rows)
    # Kwoty kafli sumują się z tych samych, już zaokrąglonych składników, które
    # front wyświetla w kolumnach — dzięki temu kafel „Suma MRR" da się
    # sprawdzić dodając kolumnę na ekranie.
    totals["monthly_margin_total"] = sum(
        c["monthly_margin_total"] or 0 for c in clients
    )
    totals["total_revenue_all_time"] = sum(
        c["total_revenue_all_time"] or 0 for c in clients
    )
    totals["active_revenue"] = sum(c["active_revenue"] or 0 for c in clients)

    result = {
        "period": resolved.as_payload(),
        "valuation": {
            "on": on.isoformat(),
            "basis": "live_contracts",
            "note": (
                "Marża/MRR to bieżące kontrakty (active/ending) wycenione "
                "stawkami z harmonogramów obowiązującymi w dniu wyceny. "
                "Przychód lifetime nie jest przycinany oknem."
            ),
        },
        "totals": totals,
        "clients": clients,
    }
    await cache_set(cache_key, result, ttl_seconds=CACHE_TTL_SECONDS)
    return result


def _sorted(rows: list[ClientHitRatioRow], sort: str) -> list[ClientHitRatioRow]:
    if sort == "volume":
        return sorted(rows, key=lambda r: r.closed_jobs, reverse=True)
    if sort == "name":
        return sorted(rows, key=lambda r: r.client_name.lower())
    # Domyślnie po skuteczności. Klienci bez policzalnego wskaźnika lądują na
    # końcu — `None` nie jest „najgorszym wynikiem", tylko brakiem wyniku.
    return sorted(
        rows,
        key=lambda r: (r.hit_ratio is not None, r.hit_ratio or 0.0, r.closed_jobs),
        reverse=True,
    )


def _parse_exclude_reasons(raw: str | None) -> set[JobCloseReason]:
    """CSV powodów zamknięcia → zbiór enumów.

    Nieznana wartość ODRZUCA żądanie (422), a nie jest po cichu pomijana:
    literówka w filtrze cicho poszerza mianownik i podnosi hit ratio, czego na
    ekranie nie widać (``reports.py:_parse_exclude_reasons`` gubi je milcząco).
    """
    if not raw:
        return set()
    out: set[JobCloseReason] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            out.add(JobCloseReason(token))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Nieznany powód zamknięcia: {token!r}. Dozwolone: "
                    f"{', '.join(r.value for r in JobCloseReason)}"
                ),
            ) from None
    return out


def _previous_window(
    resolved: Period,
    kind: str,
    offset: int,
    anchor: date | None,
) -> Period:
    """Okno bezpośrednio poprzedzające ``resolved``.

    Dla okresów kalendarzowych to poprzedni okres tej samej granulacji
    (``offset - 1``) — nie „minus 30 dni", bo luty i marzec mają różną długość
    i przesunięcie o stałą liczbę dni porównywałoby wycinki dwóch miesięcy.
    Dla ``custom`` przesuwamy o dokładną długość zakresu, bo kalendarzowego
    poprzednika taki zakres nie ma.
    """
    if resolved.kind is PeriodKind.custom:
        span = resolved.end - resolved.start
        return Period(
            kind=PeriodKind.custom,
            start=resolved.start - span,
            end=resolved.start,
        )
    return _resolve(kind, offset - 1, anchor, None, None)


@router.get("/hit-ratio")
async def insights_clients_hit_ratio(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query("year", pattern="^(day|week|month|quarter|year|custom)$"),
    offset: int = Query(0, description="0 = bieżący okres, -1 = poprzedni zamknięty"),
    anchor: date | None = Query(None, description="dowolny dzień wewnątrz okresu"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    min_closed: int = Query(0, ge=0, le=100),
    sort: str = Query("hit_ratio", pattern="^(hit_ratio|volume|name)$"),
    exclude_reasons: str | None = Query(
        None,
        description="CSV powodów zamknięcia wykluczonych z mianownika, "
        "np. 'paused,client_ghosted'",
    ),
    drop_pp: float = Query(
        20.0, ge=5.0, le=100.0, description="próg spadku hit ratio dla listy at-risk"
    ),
    at_risk_min_closed: int = Query(3, ge=1, le=100),
):
    """Skuteczność per klient w oknie + klienci ze spadkiem (at-risk).

    Dostępne dla KAŻDEGO zalogowanego (decyzja D7).

    ``placements`` liczy kamienie D2 — pierwsze ``hired`` per para
    (kandydat, oferta). ``reports.py:1080-1098`` liczy tu KAŻDY wiersz
    ``candidate_stages.stage='hired'``, więc para z dwoma podejściami
    procesowymi wchodzi tam dwa razy i zawyża ``fill_rate``. Na /insights
    obowiązuje jedna definicja placementu (plan §0 D2).
    """
    resolved = _resolve(period, offset, anchor, date_from, date_to)
    excluded = _parse_exclude_reasons(exclude_reasons)
    excluded_key = ",".join(sorted(r.value for r in excluded))

    cache_key = (
        f"insights:clients:hit-ratio:v1:{resolved.cache_suffix}"
        f":{min_closed}:{sort}:{excluded_key}:{drop_pp}:{at_risk_min_closed}"
    )
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    all_rows = await compute_client_hit_ratio(
        db, start=resolved.start, end=resolved.end, exclude_reasons=excluded or None
    )
    # Filtr NAJPIERW, fold POTEM. `reports.py` liczy `overall` po pełnym
    # zbiorze, a wyświetla przefiltrowany — kafel nie zgadza się wtedy z sumą
    # tabeli pod nim i nie da się tego sprawdzić wzrokiem.
    rows = [r for r in all_rows if r.closed_jobs >= min_closed]
    overall = fold_hit_ratio_totals(rows)

    previous = _previous_window(resolved, period, offset, anchor)
    prev_rows = await compute_client_hit_ratio(
        db, start=previous.start, end=previous.end, exclude_reasons=excluded or None
    )
    prev_by_client = {r.client_id: r for r in prev_rows}

    at_risk: list[dict] = []
    not_comparable = 0
    # Świadomie iterujemy `all_rows`, a NIE przefiltrowaną `rows`.
    #
    # `min_closed` jest filtrem WIDOKU (co pokazać w tabeli), a
    # `at_risk_min_closed` progiem OSTRZEŻENIA. Gdyby ostrzeżenia liczyły się
    # z przefiltrowanej listy, zawężenie tabeli po cichu WYGASZAŁOBY alerty —
    # użytkownik przesuwa suwak i ryzyko znika z ekranu, choć nie zniknęło
    # z rzeczywistości. Ukrywanie ostrzeżenia na podstawie preferencji
    # wyświetlania jest gorsze niż rozjazd zakresów.
    #
    # Rozjazd rozwiązujemy jawnie: koperta niesie `scope` i licznik klientów
    # zagrożonych, którzy NIE mieszczą się w widocznej tabeli, żeby UI mogło
    # to napisać zamiast zostawiać czytelnika z „1 zagrożony, ale nie widzę go
    # na liście".
    for curr in all_rows:
        if curr.closed_jobs < at_risk_min_closed or curr.hit_ratio is None:
            continue
        prev = prev_by_client.get(curr.client_id)
        if prev is None or prev.hit_ratio is None:
            # Poprzednie okno nie ma z czym porównywać. `reports.py` podstawia
            # tu 0.0, czyli twierdzi, że klient miał zerową skuteczność —
            # a on nie miał ANI JEDNEJ zamkniętej oferty. Liczymy takich
            # osobno, zamiast zmyślać im punkt odniesienia.
            not_comparable += 1
            continue
        delta_pp = round(curr.hit_ratio - prev.hit_ratio, 1)
        if delta_pp < -drop_pp:
            at_risk.append(
                {
                    **_hit_ratio_payload(curr),
                    "prev_hit_ratio": prev.hit_ratio,
                    "prev_closed_jobs": prev.closed_jobs,
                    "delta_pp": delta_pp,
                }
            )
    at_risk.sort(key=lambda r: r["delta_pp"])  # największy spadek u góry

    visible_ids = {r.client_id for r in rows}
    at_risk_outside_table = sum(
        1 for r in at_risk if r.get("client_id") not in visible_ids
    )

    result = {
        "period": resolved.as_payload(),
        # Wypisane wprost, żeby konsument nie musiał zgadywać, którą z trzech
        # definicji placementu w aplikacji ogląda.
        "placement_definition": "first_hired_per_candidate_and_job",
        "sort": sort,
        "min_closed": min_closed,
        "excluded_reasons": sorted(r.value for r in excluded),
        "clients": [_hit_ratio_payload(r) for r in _sorted(rows, sort)],
        "overall": overall,
        "at_risk": {
            # Zakres ostrzeżeń jest SZERSZY niż tabela — patrz komentarz przy
            # pętli wyżej. `outside_visible_table` mówi wprost, ilu klientów
            # zagrożonych nie mieści się w widocznej liście, żeby UI nie
            # zostawiło czytelnika z „1 zagrożony, ale nie widzę go na liście".
            "scope": "all_clients",
            "outside_visible_table": at_risk_outside_table,
            "previous_period": previous.as_payload(),
            "drop_threshold_pp": drop_pp,
            "min_closed": at_risk_min_closed,
            "clients": at_risk,
            # Klienci, których nie da się porównać — bez tej liczby pusta lista
            # at-risk czyta się jako „nikt nie spada", a znaczy „nie było czego
            # porównać".
            "not_comparable": not_comparable,
        },
    }
    await cache_set(cache_key, result, ttl_seconds=CACHE_TTL_SECONDS)
    return result


@router.get("/hiring-managers")
async def insights_hiring_managers(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query("year", pattern="^(day|week|month|quarter|year|custom)$"),
    offset: int = Query(0, description="0 = bieżący okres, -1 = poprzedni zamknięty"),
    anchor: date | None = Query(None, description="dowolny dzień wewnątrz okresu"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """Ranking hiring managerów po stronie klientów.

    Dostępne dla KAŻDEGO zalogowanego (decyzja D7). Legacy
    `/api/reports/hiring-managers` zostaje na swoich trzech rolach i na całej
    historii — ten endpoint go nie zmienia, tylko liczy to samo w oknie.

    Dwie rzeczy, które koperta mówi WPROST, bo bez nich kolumna znaczy co
    innego, niż wygląda:

    1. Okno filtruje REKRUTACJE po ``Job.created_at``. Kontrakty liczone są dla
       rekrutacji z okna, niezależnie od tego, kiedy same powstały — umowę
       z rekrutacji otwartej w lipcu zwykle podpisuje się później.
    2. ``contracts_active`` to MIGAWKA NA DZIŚ. ``ContractStatus`` nie ma
       historii, więc „ilu konsultantów pracowało w maju" jest z tych danych
       nieodtwarzalne. Liczba migawkowa podana pod etykietą okna czyta się jak
       stan historyczny i nie da się jej od niego odróżnić.
    """
    resolved = _resolve(period, offset, anchor, date_from, date_to)

    cache_key = f"insights:clients:hiring-managers:v1:{resolved.cache_suffix}:{limit}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    rows = await compute_hiring_manager_kpis(
        db, since=resolved.start, until=resolved.end
    )
    visible = rows[:limit]

    managers = [
        {
            "contact_id": r.contact_id,
            "contact_name": r.contact_name,
            "position": r.position,
            "client_id": r.client_id,
            "client_name": r.client_name,
            "jobs_total": r.jobs_total,
            "jobs_open": r.jobs_open,
            "contracts_total": r.contracts_total,
            "contracts_active": r.contracts_active,
            # Ile rekrutacji tego HM skończyło się kontraktem. `None` przy
            # zerze rekrutacji — „nie było czego dzielić" to co innego niż
            # „policzone i wyszło zero". Świadomie BEZ przycinania do 100%:
            # jedna rekrutacja z dwoma kontraktami daje 200% i to ma być
            # widoczne, a nie schowane pod sufitem.
            "contract_rate_pct": ratio_pct(r.contracts_total, r.jobs_total),
        }
        for r in visible
    ]

    # Kafle to FOLD po WIDOCZNEJ liście — kafel liczony z pełnego zbioru pod
    # przyciętą tabelą nie daje się sprawdzić dodając kolumnę na ekranie.
    jobs_total = sum(m["jobs_total"] for m in managers)
    jobs_open = sum(m["jobs_open"] for m in managers)

    result = {
        "period": resolved.as_payload(),
        "limit": limit,
        "managers": managers,
        "totals": {
            "managers": len(managers),
            "jobs_total": jobs_total,
            "jobs_open": jobs_open,
            "contracts_total": sum(m["contracts_total"] for m in managers),
            "contracts_active": sum(m["contracts_active"] for m in managers),
            # Puste okno daje `None`, nie 0.0 — inaczej „brak rekrutacji"
            # czytałoby się jako „zero otwartych", czyli jako obserwacja.
            "open_rate_pct": ratio_pct(jobs_open, jobs_total),
        },
        # Ilu HM odsiał `limit`. Bez tej liczby przycięta lista czyta się jako
        # komplet.
        "truncated": max(len(rows) - len(visible), 0),
        "scope": {
            "jobs": "job_created_at_in_window",
            "contracts": "contracts_of_jobs_in_window",
            "contracts_active_is_snapshot_now": True,
            "note": (
                "Okno filtruje rekrutacje po dacie utworzenia; kontrakty liczą "
                "się dla tych rekrutacji niezależnie od własnej daty. "
                "„Aktywni” to stan NA DZIŚ — statusy kontraktów nie mają "
                "historii, więc stanu z końca okna nie da się odtworzyć."
            ),
        },
    }
    await cache_set(cache_key, result, ttl_seconds=CACHE_TTL_SECONDS)
    return result
