"""Ranking klientów i hit ratio — jedna implementacja dla dwóch powierzchni.

Moduł powstał, bo `/api/admin/clients-overview` (portal DL, admin/finance) i
nowy `/api/insights/clients` (D7: każdy zalogowany) muszą pokazywać TE SAME
liczby. Jedynym sposobem na to jest jedno zapytanie, nie dwa podobne: kopia SQL
rozjeżdża się cicho, bo obie odpowiedzi wyglądają wiarygodnie i nikt ich obok
siebie nie kładzie. Dlatego guard i kształt odpowiedzi zostają w routerach —
tutaj jest wyłącznie liczenie.

Trzy decyzje, które trzymają ten moduł uczciwym:

1. **Pieniądze idą z HARMONOGRAMÓW stawek, nigdy z kolumn `contracts.rate_*`.**
   Kolumna niesie kwotę z ostatniego ZAPISU kontraktu, więc krok progresywny
   albo aneks z datą, która już nadeszła, pokazywały tu marżę pierwszego
   okresu. Resolver to `app.services.contract_rates.effective_rate_fields`
   (ten sam obiekt co `app.api.contracts._effective_rate_fields`), a
   `RATE_SCHEDULE_LOADS` MUSI być w `options()` każdego zapytania o kontrakty —
   bez tego `effective_*_rate` robi lazy-load w sesji async i leci
   `MissingGreenlet`, czyli HTTP 500 bez nagłówków CORS („Network Error" w UI).

2. **Placement = D2: PIERWSZE `hired` per para (kandydat, oferta)**, czyli
   wiersz widoku `analytics_first_milestones`. `reports.py:1080-1098` liczy tu
   KAŻDY wiersz `candidate_stages.stage='hired'` — para z dwoma podejściami
   procesowymi jest tam liczona dwa razy i zawyża `fill_rate`. Jedna definicja
   na całej stronie /insights (plan §0 D2).

3. **Zerowy mianownik daje `None`, nigdy `0.0`.** „Nie było czego dzielić" to
   co innego niż „policzone i wyszło zero" — na ekranie oceniającym klientów to
   jest różnica między brakiem próby a porażką. Procentu NIE przycinamy do 100:
   wynik powyżej stu procent znaczy, że kolejność etapów nie trzyma się kupy,
   i ma być widoczny.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Integer, column, func, select, table
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.client import Client
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus
from app.models.job import Job, JobCloseReason, JobStatus
from app.models.recruitment_pipeline import PipelineStage
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User
from app.services.client_identity import (
    client_display_name_expression,
    visible_client_predicates,
)
from app.services.contract_rates import RATE_SCHEDULE_LOADS, effective_rate_fields
from app.services.contractor_identity import count_unique_contractors
from app.services.fx_service import amount_to_pln_with_rate, rates_to_pln
from app.services.order_revenue import order_revenue_rows_to_pln

__all__ = [
    "HIT_RATIO_TARGET_PCT",
    "LIVE_CONTRACT_STATUSES",
    "ClientHitRatioRow",
    "ClientRankingRow",
    "compute_client_hit_ratio",
    "compute_client_ranking",
    "fold_hit_ratio_totals",
    "fold_ranking_totals",
    "margin_lookup_pln",
    "ratio_pct",
]


# „Konsultant pracuje u tego klienta" = active LUB ending. Dzienny cron
# ``contract_alerts._promote_statuses`` przestawia active→ending 30 dni przed
# końcem, a konsultant w ostatnim miesiącu wciąż pracuje i wciąż fakturuje —
# liczenie samego ``active`` zdejmowało go z liczby głów i wycinało całą jego
# marżę, przez co ten ekran przeczył profilowi klienta i banerowi wygasających.
LIVE_CONTRACT_STATUSES = (ContractStatus.active, ContractStatus.ending)

# Próg wejścia do Ligi Mistrzów DL (InfraReporter). Stała jest tu skopiowana
# świadomie: import z `app.api.reports` wciągnąłby cały router raportów do
# warstwy serwisowej, a to dokładnie ta zależność, którą `contract_rates`
# zdejmowało z `api.contracts`.
HIT_RATIO_TARGET_PCT = 30.0

# Widok kamieni milowych (migracja 0184) — pierwsze wejście na etap per para
# (kandydat, oferta). Deklaracja przez `table()`, a nie surowy `text()`, bo
# `in_()` na liście identyfikatorów ma wtedy poprawne bindowanie niezależnie od
# sterownika. ``stage`` MUSI nieść typ enuma, a nie ``String``: w bazie kolumna
# jest natywnym ``pipelinestage``, a porównanie z parametrem tekstowym wywraca
# się na „operator does not exist: pipelinestage = character varying".
_first_milestones = table(
    "analytics_first_milestones",
    column("candidate_id", Integer),
    column("job_id", Integer),
    column("stage", SAEnum(PipelineStage, name="pipelinestage")),
)


def ratio_pct(numerator: int, denominator: int) -> Optional[float]:
    """Udział procentowy albo ``None`` przy zerowym mianowniku.

    NIE zwraca 0.0 i NIE przycina do 100 — patrz decyzja 3 w docstringu modułu.
    """
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 1)


async def margin_lookup_pln(
    db: AsyncSession,
    contracts: list[Contract],
    on: date,
) -> tuple[dict[int, Decimal], set[int]]:
    """Marża miesięczna per klient, obie nogi stawki przewalutowane na PLN.

    Zwracany zbiór to klienci, dla których choć jeden wyceniony kontrakt
    potrzebuje niedostępnego kursu. Wołający zostawia ich marżę jako ``None``
    zamiast po cichu publikować sumę częściową — brak kursu NBP kasuje kwotę
    z sumy i kafel obok pokazuje wtedy pewną, zaniżoną liczbę.
    """

    currencies = {
        currency
        for contract in contracts
        for currency in (
            contract.resolved_rate_client_currency,
            contract.resolved_rate_candidate_currency,
        )
    }
    fx_rates = await rates_to_pln(db, currencies, on)
    totals: dict[int, Decimal] = {}
    incomplete: set[int] = set()
    for contract in contracts:
        fields = effective_rate_fields(contract, on)
        raw_client = fields["monthly_rate_client"]
        raw_candidate = fields["monthly_rate_candidate"]
        if raw_client is None or raw_candidate is None:
            continue
        client_fx = fx_rates.get(contract.resolved_rate_client_currency)
        candidate_fx = fx_rates.get(contract.resolved_rate_candidate_currency)
        client_pln, client_complete = amount_to_pln_with_rate(raw_client, client_fx)
        candidate_pln, candidate_complete = amount_to_pln_with_rate(
            raw_candidate, candidate_fx
        )
        if not client_complete or not candidate_complete:
            incomplete.add(contract.client_id)
            continue
        assert client_pln is not None and candidate_pln is not None
        margin_pln = client_pln - candidate_pln
        totals[contract.client_id] = (
            totals.get(contract.client_id, Decimal("0")) + margin_pln
        )
    for client_id in incomplete:
        totals.pop(client_id, None)
    return totals, incomplete


@dataclass(frozen=True)
class ClientRankingRow:
    """Wiersz rankingu klientów; wszystkie kwoty w PLN.

    Nazwy pól są lustrem ``app.schemas.admin_clients_overview.OverviewRow`` —
    router admina waliduje ten obiekt wprost (``from_attributes``), więc każda
    rozbieżność wyszłaby jako zmiana JEGO odpowiedzi.
    """

    client_id: int
    name: str
    industry: Optional[str]
    head_dl_id: Optional[int]
    head_dl_name: Optional[str]
    total_revenue_all_time: Optional[Decimal]
    active_revenue: Optional[Decimal]
    monthly_margin_total: Optional[Decimal]
    active_orders_count: int
    active_consultants: int
    active_contracts: int
    framework_status: Optional[str]
    framework_expiry_date: Optional[date]
    # Flagi degradacji — router /insights renderuje po nich kafel jako
    # niepełny. Router admina ich nie czyta (jego schemat ich nie deklaruje),
    # więc ich obecność niczego mu nie zmienia.
    revenue_complete: bool
    margin_complete: bool


async def compute_client_ranking(
    db: AsyncSession,
    *,
    on: date,
) -> list[ClientRankingRow]:
    """Ranking klientów wyceniony stawkami obowiązującymi dnia ``on``.

    Zbiór kontraktów to ZAWSZE dzisiejsze umowy żywe (``active``/``ending``);
    ``on`` steruje wyłącznie tym, KTÓRY krok harmonogramu i KTÓRY kurs NBP
    wchodzi do wyceny. Rozdzielenie tych dwóch rzeczy jest świadome — zmiana
    zbioru kontraktów na point-in-time byłaby inną definicją „aktywnego
    konsultanta" niż ta, którą pokazuje profil klienta i portal DL.
    """
    # Nazwa prezentowana + tylko widoczne wiersze — ta sama para reguł co
    # `my_clients.py` / `search.py`. Surowe `Client.name` pokazywałoby nazwę
    # sprzed ręcznej poprawki (na prodzie 24/160 klientów), a brak filtra
    # dorzucał scalone duplikaty jako wiersze z zerami. Sortowanie po
    # `lower(effective_name)` jest tie-breakiem widocznej kolejności: końcowy
    # sort po revenue jest STABILNY, a większość klientów ma revenue NULL.
    effective_name = client_display_name_expression()
    client_rows = list(
        (
            await db.execute(
                select(Client, effective_name.label("effective_name"))
                .where(*visible_client_predicates())
                .order_by(func.lower(effective_name).asc(), Client.id.asc())
            )
        ).all()
    )

    rev_rows = list(
        (
            await db.execute(
                select(
                    ClientOrder.client_id,
                    ClientOrder.status,
                    ClientOrder.currency,
                    func.coalesce(func.sum(ClientOrder.total_value), 0).label(
                        "sum_val"
                    ),
                    func.count().label("cnt"),
                )
                .where(ClientOrder.status != ClientOrderStatus.cancelled)
                .group_by(
                    ClientOrder.client_id,
                    ClientOrder.status,
                    ClientOrder.currency,
                )
            )
        )
    )
    rev_lookup, rev_incomplete = await order_revenue_rows_to_pln(db, rev_rows, on)
    active_order_counts: dict[int, int] = {}
    for r in rev_rows:
        if r.status == ClientOrderStatus.active:
            active_order_counts[r.client_id] = active_order_counts.get(
                r.client_id, 0
            ) + int(r.cnt or 0)

    # Head DL = klient ma assignment z is_head=True. Jeśli admin nie zaznaczył
    # nikogo jako Head (większość klientów), fallback do dowolnego DL
    # przypisanego do klienta — bez niego kolumna „Head DL" pokazuje „brak"
    # dla 156/158 klientów.
    head_dl_rows = list(
        (
            await db.execute(
                select(
                    DeliveryLeadClientAssignment.client_id,
                    DeliveryLeadClientAssignment.is_head,
                    User.id,
                    User.name,
                )
                .join(
                    User, User.id == DeliveryLeadClientAssignment.delivery_lead_user_id
                )
                # Preferuj is_head=true (sortowanie po nim DESC), tie-break
                # po user.id DESC (nowsze konto @inframinds.eu).
                .order_by(
                    DeliveryLeadClientAssignment.is_head.desc(),
                    User.id.desc(),
                )
            )
        )
    )
    head_dl_lookup: dict[int, tuple[int, str]] = {}
    for r in head_dl_rows:
        # Pierwszy wpis per client_id wygrywa (order_by gwarantuje, że to
        # is_head=True, jeśli istnieje).
        if r.client_id not in head_dl_lookup:
            head_dl_lookup[r.client_id] = (r.id, r.name)

    fc_rows = list(
        (
            await db.execute(
                select(
                    ClientFrameworkContract.client_id,
                    ClientFrameworkContract.status,
                    ClientFrameworkContract.expiry_date,
                )
                .where(
                    ClientFrameworkContract.status.in_(
                        (
                            FrameworkContractStatus.active,
                            FrameworkContractStatus.pending_signature,
                        )
                    ),
                )
                .order_by(
                    ClientFrameworkContract.client_id,
                    ClientFrameworkContract.effective_date.desc().nullslast(),
                )
            )
        )
    )
    fc_lookup: dict[int, tuple[str, object]] = {}
    for r in fc_rows:
        if r.client_id not in fc_lookup:
            fc_lookup[r.client_id] = (r.status.value, r.expiry_date)

    # 1 Contract = 1 kontraktor (brak M:N), więc `Contract.client_id` daje
    # komplet kontraktorów u klienta bez joina do zamówień.
    margin_rows = list(
        (
            await db.execute(
                select(Contract)
                .options(*RATE_SCHEDULE_LOADS, selectinload(Contract.candidate))
                .where(Contract.status.in_(LIVE_CONTRACT_STATUSES))
            )
        ).scalars()
    )
    contractor_candidates: dict[int, list] = {}
    active_contracts_lookup: dict[int, int] = {}
    for r in margin_rows:
        active_contracts_lookup[r.client_id] = (
            active_contracts_lookup.get(r.client_id, 0) + 1
        )
        if r.candidate is not None:
            contractor_candidates.setdefault(r.client_id, []).append(r.candidate)
    margin_lookup, margin_incomplete = await margin_lookup_pln(db, margin_rows, on)

    items: list[ClientRankingRow] = []
    for c, effective in client_rows:
        rev = rev_lookup.get(c.id, {"total": None, "active": None})
        revenue_complete = c.id not in rev_incomplete
        head = head_dl_lookup.get(c.id)
        fc = fc_lookup.get(c.id)
        items.append(
            ClientRankingRow(
                client_id=c.id,
                name=effective,
                industry=getattr(c, "industry", None),
                head_dl_id=head[0] if head else None,
                head_dl_name=head[1] if head else None,
                total_revenue_all_time=(rev["total"] or None)
                if revenue_complete
                else None,
                active_revenue=(rev["active"] or None) if revenue_complete else None,
                monthly_margin_total=margin_lookup.get(c.id),
                active_orders_count=active_order_counts.get(c.id, 0),
                active_consultants=count_unique_contractors(
                    contractor_candidates.get(c.id, [])
                ),
                active_contracts=active_contracts_lookup.get(c.id, 0),
                framework_status=fc[0] if fc else None,
                framework_expiry_date=fc[1] if fc else None,
                revenue_complete=revenue_complete,
                margin_complete=c.id not in margin_incomplete,
            )
        )

    items.sort(key=lambda r: r.total_revenue_all_time or 0, reverse=True)
    return items


def fold_ranking_totals(rows: Iterable[ClientRankingRow]) -> dict:
    """Kafle policzone z DOKŁADNIE tych wierszy, które zwraca lista.

    Kafel będący sumą innych liczb niż widoczne pod nim nie daje się
    zweryfikować wzrokiem — a niezweryfikowalny kafel z kwotą jest gorszy niż
    brak kafla. Dlatego to jest fold po liście, nie drugie zapytanie.

    Zaokrąglenie do pełnych złotych robi WOŁAJĄCY, na składnikach: suma
    zaokrągleń ≠ zaokrąglenie sumy, więc kafel liczony z surowych ``Decimal``
    różniłby się od sumy kolumny o złotówki (patrz `app/schemas/money.py`).
    """
    rows = list(rows)
    return {
        "clients": len(rows),
        # „Aktywny klient" = pracuje u niego dziś co najmniej jeden konsultant.
        # Definicja jest ta sama, z której wyliczana jest kolumna obok.
        "active_clients": sum(1 for r in rows if r.active_contracts > 0),
        "active_consultants": sum(r.active_consultants for r in rows),
        "active_contracts": sum(r.active_contracts for r in rows),
        "active_orders_count": sum(r.active_orders_count for r in rows),
        "monthly_margin_complete": all(r.margin_complete for r in rows),
        "revenue_complete": all(r.revenue_complete for r in rows),
    }


@dataclass(frozen=True)
class ClientHitRatioRow:
    """Skuteczność per klient w oknie [start, end) po ``jobs.closed_at``."""

    client_id: int
    client_name: str
    client_status: Optional[str]
    closed_jobs: int
    filled_jobs: int
    lost_jobs: int
    total_vacancies: int
    placements: int
    hit_ratio: Optional[float]
    fill_rate: Optional[float]
    active_jobs: int
    target_achieved: Optional[bool]
    close_reasons: dict[str, int]


def _enum_value(raw: object, *, default: str) -> str:
    """Wartość enuma albo ``default`` — legacy NULL-e są w tych kolumnach realne."""
    if raw is None:
        return default
    return getattr(raw, "value", None) or str(raw)


async def compute_client_hit_ratio(
    db: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    exclude_reasons: Optional[set[JobCloseReason]] = None,
) -> list[ClientHitRatioRow]:
    """Hit ratio i fill rate per klient dla ofert zamkniętych w oknie.

    - mianownik ``closed_jobs`` = ``Job.status='closed'`` i
      ``closed_at ∈ [start, end)`` — okno PÓŁOTWARTE, jak wszędzie w /insights;
    - ``placements`` = kamienie D2 (pierwsze ``hired`` per para kandydat×oferta)
      dla tych ofert. `reports.py:1080-1098` liczy tu każdy wiersz
      ``candidate_stages.stage='hired'``, więc para z dwoma podejściami
      procesowymi wchodzi tam dwa razy i zawyża ``fill_rate``;
    - moment samego ``hired`` NIE jest przycinany oknem: hire zamyka ofertę,
      nie odwrotnie, więc przycięcie zgubiłoby placement sprzed zamknięcia;
    - ``active_jobs`` to SNAPSHOT opublikowanych ofert — świadomie poza oknem,
      bo odpowiada na pytanie „co u tego klienta stoi otwarte TERAZ".
    """
    effective_name = client_display_name_expression()
    jobs_q = (
        select(
            Job.id,
            Job.client_id,
            Job.headcount,
            Job.close_reason,
            effective_name.label("client_name"),
            Client.status.label("client_status"),
        )
        .join(Client, Job.client_id == Client.id)
        .where(
            Job.status == JobStatus.closed,
            Job.closed_at.isnot(None),
            Job.closed_at >= start,
            Job.closed_at < end,
            *visible_client_predicates(),
        )
    )
    if exclude_reasons:
        jobs_q = jobs_q.where(
            (Job.close_reason.is_(None)) | (Job.close_reason.notin_(exclude_reasons))
        )
    jobs_rows = (await db.execute(jobs_q)).all()

    per_client: dict[int, dict] = {}
    job_to_client: dict[int, int] = {}
    for r in jobs_rows:
        job_to_client[r.id] = r.client_id
        bucket = per_client.setdefault(
            r.client_id,
            {
                "client_id": r.client_id,
                "client_name": r.client_name,
                "client_status": _enum_value(r.client_status, default="unknown")
                if r.client_status is not None
                else None,
                "closed_jobs": 0,
                "total_vacancies": 0,
                "filled_job_ids": set(),
                "placements": 0,
                "active_jobs": 0,
                "close_reasons": {},
            },
        )
        bucket["closed_jobs"] += 1
        bucket["total_vacancies"] += int(r.headcount or 1)
        key = _enum_value(r.close_reason, default="unknown")
        bucket["close_reasons"][key] = bucket["close_reasons"].get(key, 0) + 1

    if job_to_client:
        placement_rows = (
            await db.execute(
                select(
                    _first_milestones.c.job_id,
                    func.count().label("cnt"),
                )
                .where(
                    _first_milestones.c.stage == PipelineStage.hired,
                    _first_milestones.c.job_id.in_(list(job_to_client)),
                )
                .group_by(_first_milestones.c.job_id)
            )
        ).all()
        for r in placement_rows:
            client_id = job_to_client.get(r.job_id)
            if client_id is None:
                continue
            per_client[client_id]["filled_job_ids"].add(r.job_id)
            per_client[client_id]["placements"] += int(r.cnt)

    active_rows = (
        await db.execute(
            select(Job.client_id, func.count(Job.id).label("cnt"))
            .where(Job.status == JobStatus.published, Job.client_id.isnot(None))
            .group_by(Job.client_id)
        )
    ).all()
    for r in active_rows:
        if r.client_id in per_client:
            per_client[r.client_id]["active_jobs"] = int(r.cnt)

    out: list[ClientHitRatioRow] = []
    for bucket in per_client.values():
        closed = bucket["closed_jobs"]
        filled = len(bucket["filled_job_ids"])
        hit_ratio = ratio_pct(filled, closed)
        out.append(
            ClientHitRatioRow(
                client_id=bucket["client_id"],
                client_name=bucket["client_name"],
                client_status=bucket["client_status"],
                closed_jobs=closed,
                filled_jobs=filled,
                lost_jobs=max(closed - filled, 0),
                total_vacancies=bucket["total_vacancies"],
                placements=bucket["placements"],
                hit_ratio=hit_ratio,
                fill_rate=ratio_pct(bucket["placements"], bucket["total_vacancies"]),
                active_jobs=bucket["active_jobs"],
                # Nieznany wskaźnik nie „nie osiągnął progu" — to dwie różne
                # rzeczy i zlanie ich w `False` maluje klienta bez ani jednej
                # zamkniętej oferty na czerwono.
                target_achieved=None
                if hit_ratio is None
                else hit_ratio >= HIT_RATIO_TARGET_PCT,
                close_reasons=bucket["close_reasons"],
            )
        )
    return out


def fold_hit_ratio_totals(rows: Iterable[ClientHitRatioRow]) -> dict:
    """Podsumowanie policzone z tych samych wierszy, które widać w tabeli."""
    rows = list(rows)
    total_closed = sum(r.closed_jobs for r in rows)
    total_filled = sum(r.filled_jobs for r in rows)
    total_placements = sum(r.placements for r in rows)
    total_vacancies = sum(r.total_vacancies for r in rows)
    with_ratio = [r for r in rows if r.hit_ratio is not None]
    return {
        "total_clients": len(rows),
        "clients_with_closed_jobs": len(with_ratio),
        "total_closed_jobs": total_closed,
        "total_filled_jobs": total_filled,
        "total_lost_jobs": max(total_closed - total_filled, 0),
        "total_vacancies": total_vacancies,
        "total_placements": total_placements,
        "global_hit_ratio": ratio_pct(total_filled, total_closed),
        "global_fill_rate": ratio_pct(total_placements, total_vacancies),
        # Średnia po klientach z policzalnym wskaźnikiem. Bez takich klientów
        # to `None`, nie 0.0 — zero czytałoby się jako „wszyscy mają zero".
        "avg_hit_ratio": round(
            sum(r.hit_ratio or 0.0 for r in with_ratio) / len(with_ratio), 1
        )
        if with_ratio
        else None,
        "avg_fill_rate": round(
            sum(r.fill_rate or 0.0 for r in with_ratio) / len(with_ratio), 1
        )
        if with_ratio
        else None,
        "target_count": sum(1 for r in rows if r.target_achieved),
        "hit_ratio_target_pct": HIT_RATIO_TARGET_PCT,
    }
