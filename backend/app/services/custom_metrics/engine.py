"""Silnik własnej metryki pulpitu.

Trzy reguły, które trzymają ten moduł uczciwym:

* **Uprawnienia są liczone od nowa przy każdym zapytaniu** — z sekcji konta
  i z ``resolve_dashboard_scope``, nie z zapisanego kafelka. Kafelek zapisany,
  gdy ktoś miał dostęp, nie pokaże danych po odebraniu uprawnień: silnik
  rzuca ``MetricAccessDenied``, a kafelek mówi „brak dostępu" zamiast zera.
* **Kwoty przez ``fold_money``** — tę samą funkcję co kafle Rady i tabele
  rok-do-roku. Dwie różne marże pod jedną nazwą na dwóch ekranach to błąd,
  którego nie da się wytłumaczyć użytkownikowi.
* **Redakcja kwot całościowa albo żadna.** Delivery Lead liczy wyłącznie
  klientów ze swojego portfela; prośba o klienta spoza portfela odmawia
  w całości, zamiast po cichu zsumować część.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import (
    DateTime,
    Integer,
    Text,
    cast,
    column,
    func,
    or_,
    select,
    table,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analytics.capabilities import AnalyticsCapability, user_has_capability
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.competence_category import CompetenceCategory
from app.models.contract import Contract, ContractStatus
from app.models.job import Job, JobStatus
from app.models.user import User, UserRole
from app.services.access_scope import (
    DashboardScope,
    ScopeKind,
    delivery_lead_scope_is_assigned,
    delivery_lead_sees_whole_delivery,
    resolve_dashboard_scope,
    resolve_delivery_lead_assigned_client_ids,
    resolve_delivery_lead_finance_client_ids,
)
from app.services.contract_rates import RATE_SCHEDULE_LOADS, REVENUE_BEARING_STATUSES
from app.services.custom_metrics.definition import (
    MILESTONE_STAGES,
    SOURCES,
    STAGE_LABELS_PL,
    MetricDefinition,
)
from app.services.custom_metrics.windows import (
    PERIOD_LABELS_PL,
    Window,
    month_end_snapshots,
    resolve_window,
    time_buckets,
)
from app.services.fx_service import rates_to_pln_by_date
from app.services.order_alert_policy import extended_order_alert_client_ids
from app.services.order_continuation import (
    ENDING_WITHOUT_CONTINUATION_DAYS,
    order_ending_without_continuation,
)
from app.services.insights_board_money import fold_money, money, running_on
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)

TZ = "Europe/Warsaw"
TOP_BUCKETS = 20
ORDERS_ENDING_DAYS = ENDING_WITHOUT_CONTINUATION_DAYS

_SOURCE_SECTION: dict[str, Optional[ProductSection]] = {
    "pipeline_moves": ProductSection.pipeline,
    "candidates": ProductSection.sourcing,
    "jobs": ProductSection.pipeline,
    "contracts": ProductSection.delivery,
    "orders": ProductSection.delivery,
    # Finanse mają własną bramkę (capability albo portfel DL), patrz niżej.
    "finance": None,
}
_SECTION_LABELS_PL = {
    ProductSection.pipeline: "Rekrutacje",
    ProductSection.sourcing: "Kandydaci",
    ProductSection.delivery: "Delivery",
}
_AUTHOR_LABELS_PL = {"me": "moje", "team": "mój zespół", "all": "cała firma"}

_MILESTONES = table(
    "analytics_first_milestones",
    column("candidate_id"),
    column("job_id"),
    column("stage"),
    column("first_reached_at"),
    column("first_moved_by"),
)


def _credited_milestones():
    """Kamienie milowe z kredytem jak w „Moje KPI" (rodzina A).

    Gdy metryka przypisuje ruchy LUDZIOM (autor „moje"/„mój zespół" albo
    podział po rekruterze), zasługę dostaje osoba z ``VERIFIER_ANCHORED_CTE``
    — pierwszy zaakceptowany weryfikator pary — a nie ten, kto kliknął etap
    (decyzja 22.09.2026). Bez tego kafelek „Zatrudnieni" (moje) liczył inną
    osobę niż panel „Moje KPI" obok. Liczby całej firmy bez podziału na ludzi
    zostają na widoku ``analytics_first_milestones`` (ta sama reguła D2 co
    Insights). Oba źródła pomijają wykluczone placementy (0343).
    """
    # Import lokalny: kpi_panel ciągnie kpi_engine, a silnik metryk nie
    # powinien ładować go przy imporcie modułu.
    from app.services.kpi_panel import VERIFIER_ANCHORED_CTE

    return (
        text(
            VERIFIER_ANCHORED_CTE
            + """
            SELECT candidate_id, job_id, stage, reached_at, credit_user
            FROM credited
            """
        )
        .columns(
            column("candidate_id", Integer),
            column("job_id", Integer),
            column("stage", Text),
            column("reached_at", DateTime(timezone=True)),
            column("credit_user", Integer),
        )
        .subquery("credited_milestones")
    )


class MetricAccessDenied(Exception):
    """Prośba wykracza poza uprawnienia — API mapuje na 403 z tym zdaniem."""


@dataclass
class MetricResult:
    value: Optional[float]
    previous_value: Optional[float] = None
    series: list[dict[str, Any]] = field(default_factory=list)
    unit: str = "count"
    scope_applied: str = "all"
    notes: list[str] = field(default_factory=list)
    period: dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "previous_value": self.previous_value,
            "series": self.series,
            "unit": self.unit,
            "scope_applied": self.scope_applied,
            "notes": self.notes,
            "period": self.period,
        }


# ── Uprawnienia ──────────────────────────────────────────────────────────────


def allowed_authors(scope: DashboardScope) -> tuple[str, ...]:
    """Jakie „czyje dane" wolno wybrać przy tym zakresie konta."""
    if scope.kind == ScopeKind.organization:
        return ("me", "all")
    if scope.kind == ScopeKind.delivery_clients:
        return ("me", "team", "all")
    if scope.kind == ScopeKind.recruitment_org:
        return ("me", "team")
    return ("me",)


def source_denial(user: User, source: str) -> Optional[str]:
    """Powód, dla którego to konto nie liczy tego źródła — albo ``None``."""
    section = _SOURCE_SECTION[source]
    if section is not None:
        if section_access_for_user(user, section) < SectionAccess.read:
            return (
                f"Brak dostępu do sekcji {_SECTION_LABELS_PL[section]} — "
                "poproś administratora o zmianę uprawnień."
            )
        return None
    if user_has_capability(user, AnalyticsCapability.VIEW_FINANCE):
        return None
    if user.has_role(UserRole.delivery_lead):
        # Runda 8 (R8-N10-2): kwoty portfela DL wszędzie indziej (profil
        # klienta, Analityka, „Moi klienci") stoją za sekcją Delivery — DL
        # z odebraną sekcją nie liczy ich też w kreatorze.
        if section_access_for_user(user, ProductSection.delivery) < SectionAccess.read:
            return (
                f"Brak dostępu do sekcji {_SECTION_LABELS_PL[ProductSection.delivery]}"
                " — poproś administratora o zmianę uprawnień."
            )
        return None
    return "Kwoty widzą Finanse, administrator i Delivery Lead dla swoich klientów."


async def _finance_client_boundary(
    user: User, db: AsyncSession
) -> Optional[frozenset[int]]:
    """``None`` = wszyscy klienci; zbiór = portfel Delivery Leada."""
    if user_has_capability(user, AnalyticsCapability.VIEW_FINANCE):
        return None
    portfolio = await resolve_delivery_lead_finance_client_ids(user, db)
    if not portfolio:
        raise MetricAccessDenied(
            "Nie masz przypisanych klientów, dla których widzisz kwoty."
        )
    return portfolio


# Źródła Delivery: Delivery Lead liczy tylko klientów swojego portfela.
_DELIVERY_CLIENT_SOURCES = frozenset({"contracts", "orders"})


async def _delivery_client_boundary(
    user: User, db: AsyncSession
) -> Optional[frozenset[int]]:
    """``None`` = wszyscy klienci; zbiór = portfel Delivery Leada.

    Kontrakty i zamówienia to dane modułów Delivery, a tam Delivery Lead widzi
    wyłącznie przypisanych klientów (decyzja Artura 26.09.2026). Do rundy 6
    audytu kafelki „Aktywne kontrakty" i „Kończące się zamówienia" liczyły całą
    firmę, więc DL widział na pulpicie liczby klientów spoza portfela. Warunki
    są lustrem ``resolve_delivery_lead_client_ids`` (``DL_CLIENT_SCOPE=all``
    i TCM+DL = cała organizacja, admin/Finanse i role bez DL = bez granicy) —
    liczone tutaj wprost, bo tamta funkcja przy „wszyscy" oddaje listę
    WSZYSTKICH id klientów, a ta w filtrze SQL to tysiące parametrów.
    """
    if not delivery_lead_scope_is_assigned() or delivery_lead_sees_whole_delivery(user):
        return None
    portfolio = await resolve_delivery_lead_assigned_client_ids(user, db)
    if portfolio is None:
        return None
    if not portfolio:
        raise MetricAccessDenied(
            "Nie masz przypisanych klientów — kontrakty i zamówienia liczysz "
            "tylko dla swojego portfela."
        )
    return portfolio


def _author_ids(
    definition: MetricDefinition, user: User, scope: DashboardScope
) -> Optional[frozenset[int]]:
    """``None`` = bez filtra autora; zbiór = tylko ci autorzy."""
    author = definition.filters.author
    if author not in allowed_authors(scope):
        allowed = ", ".join(_AUTHOR_LABELS_PL[a] for a in allowed_authors(scope))
        raise MetricAccessDenied(
            f"Twoje uprawnienia pozwalają liczyć tylko: {allowed}."
        )
    if author == "me":
        return frozenset({user.id})
    if author == "team":
        return scope.allowed_operator_user_ids or frozenset({user.id})
    return None


# ── Etykiety grup ────────────────────────────────────────────────────────────


async def _labels(db: AsyncSession, group_by: str, keys: list[Any]) -> dict[Any, str]:
    ids = [k for k in keys if isinstance(k, int)]
    if group_by == "stage":
        return {k: STAGE_LABELS_PL.get(str(k), str(k)) for k in keys}
    if not ids:
        return {}
    if group_by == "client":
        rows = await db.execute(
            select(Client.id, Client.name).where(Client.id.in_(ids))
        )
    elif group_by == "recruiter":
        rows = await db.execute(select(User.id, User.name).where(User.id.in_(ids)))
    elif group_by == "competence_category":
        rows = await db.execute(
            select(CompetenceCategory.id, CompetenceCategory.name_pl).where(
                CompetenceCategory.id.in_(ids)
            )
        )
    else:
        return {}
    return {row[0]: row[1] for row in rows.all()}


def _group_column(definition: MetricDefinition, cols: dict[str, Any], ts: Any):
    g = definition.group_by
    if g in ("week", "month"):
        # Kolumny DATE (kontrakty, zamówienia) nie mają strefy — `timezone()`
        # na nich zwróciłby przesunięty czas. Znaczniki czasu idą przez Warszawę.
        if cols.get("_ts_is_date"):
            return func.date_trunc(g, ts)
        return func.date_trunc(g, func.timezone(TZ, ts))
    return cols[g]


async def _grouped_series(
    db: AsyncSession,
    definition: MetricDefinition,
    window: Window,
    rows: list[tuple[Any, Any]],
) -> tuple[float, list[dict[str, Any]], list[str]]:
    notes: list[str] = []
    g = definition.group_by
    if g in ("week", "month"):
        counts = {
            (k.date() if hasattr(k, "date") else k).isoformat(): v
            for k, v in rows
            if k is not None
        }
        series = [
            {"key": key, "label": label, "value": float(counts.get(key, 0))}
            for key, label in time_buckets(window, g)
        ]
        return float(sum(s["value"] for s in series)), series, notes
    ordered = sorted(rows, key=lambda kv: -float(kv[1] or 0))
    if g == "stage":
        order = {s: i for i, s in enumerate(MILESTONE_STAGES)}
        ordered = sorted(rows, key=lambda kv: order.get(str(kv[0]), 99))
    labels = await _labels(db, g, [k for k, _ in ordered])
    series = []
    unassigned = 0.0
    for key, value in ordered:
        if key is None:
            unassigned += float(value or 0)
            continue
        series.append(
            {
                "key": str(key),
                "label": labels.get(key, f"#{key}"),
                "value": float(value or 0),
            }
        )
    total = sum(s["value"] for s in series) + unassigned
    if len(series) > TOP_BUCKETS:
        rest = sum(s["value"] for s in series[TOP_BUCKETS:])
        series = series[:TOP_BUCKETS]
        series.append({"key": "other", "label": "Pozostali", "value": rest})
    if unassigned:
        series.append(
            {"key": "unassigned", "label": "Bez przypisania", "value": unassigned}
        )
    return float(total), series, notes


# ── Źródła liczone SQL-em ────────────────────────────────────────────────────


def _pipeline_query(
    definition: MetricDefinition,
    window: Window,
    author_ids: Optional[frozenset[int]],
):
    # Przypisanie do ludzi = kredyt jak w „Moje KPI"; cała firma = widok.
    if author_ids is not None or definition.group_by == "recruiter":
        source = _credited_milestones()
        m = source.c
        stage = m.stage
        person = m.credit_user
        reached_at = m.reached_at
    else:
        source = _MILESTONES
        m = source.c
        stage = cast(m.stage, Text)
        person = m.first_moved_by
        reached_at = m.first_reached_at
    cols = {
        "client": Job.client_id,
        "recruiter": person,
        "stage": stage,
        "competence_category": Job.competence_category_id,
    }
    conds = [reached_at >= window.start, reached_at < window.end]
    if definition.stage:
        conds.append(stage == definition.stage)
    else:
        conds.append(stage.in_(MILESTONE_STAGES))
    if author_ids is not None:
        conds.append(person.in_(sorted(author_ids)))
    f = definition.filters
    if f.client_ids:
        conds.append(Job.client_id.in_(f.client_ids))
    if f.competence_category_ids:
        conds.append(Job.competence_category_id.in_(f.competence_category_ids))
    if f.job_ids:
        conds.append(m.job_id.in_(f.job_ids))
    base = source.join(Job, Job.id == m.job_id)
    return base, conds, cols, reached_at


def _candidates_query(
    definition: MetricDefinition,
    window: Window,
    author_ids: Optional[frozenset[int]],
):
    cols = {
        "recruiter": Candidate.created_by,
        "competence_category": Candidate.competence_category_id,
    }
    conds = [Candidate.created_at >= window.start, Candidate.created_at < window.end]
    if author_ids is not None:
        conds.append(Candidate.created_by.in_(sorted(author_ids)))
    if definition.filters.competence_category_ids:
        conds.append(
            Candidate.competence_category_id.in_(
                definition.filters.competence_category_ids
            )
        )
    return Candidate.__table__, conds, cols, Candidate.created_at


def _jobs_query(
    definition: MetricDefinition,
    window: Window,
    author_ids: Optional[frozenset[int]],
):
    cols = {
        "client": Job.client_id,
        "recruiter": Job.recruiter_id,
        "competence_category": Job.competence_category_id,
    }
    conds: list[Any] = []
    ts: Any = None
    if definition.measure == "open_now":
        conds.append(Job.status == JobStatus.published)
    elif definition.measure == "opened":
        ts = func.coalesce(Job.opened_at, Job.created_at)
        conds += [ts >= window.start, ts < window.end]
    else:
        ts = Job.closed_at
        conds += [ts >= window.start, ts < window.end]
    if author_ids is not None:
        ids = sorted(author_ids)
        conds.append(
            or_(
                Job.recruiter_id.in_(ids),
                Job.tac_id.in_(ids),
                Job.delivery_lead_id.in_(ids),
            )
        )
    f = definition.filters
    if f.client_ids:
        conds.append(Job.client_id.in_(f.client_ids))
    if f.competence_category_ids:
        conds.append(Job.competence_category_id.in_(f.competence_category_ids))
    return Job.__table__, conds, cols, ts


def _contracts_query(
    definition: MetricDefinition,
    window: Window,
    client_boundary: Optional[frozenset[int]] = None,
):
    cols = {"client": Contract.client_id, "_ts_is_date": True}
    conds: list[Any] = []
    ts: Any = None
    if definition.measure == "active_now":
        conds += [
            Contract.status.in_((ContractStatus.active, ContractStatus.ending)),
            or_(Contract.start_date.is_(None), Contract.start_date <= window.today),
        ]
    elif definition.measure == "started":
        ts = Contract.start_date
        conds += [
            Contract.status.in_(REVENUE_BEARING_STATUSES),
            ts >= window.start_date,
            ts < window.end_date,
        ]
    else:
        # Runda 8 (R8-N13-1): `terminated_at` przeżywa aneks przedłużenia.
        ts = func.coalesce(Contract.end_date, Contract.terminated_at)
        conds += [
            Contract.status == ContractStatus.ended,
            ts >= window.start_date,
            ts < window.end_date,
        ]
    if definition.filters.client_ids:
        conds.append(Contract.client_id.in_(definition.filters.client_ids))
    if client_boundary is not None:
        conds.append(Contract.client_id.in_(sorted(client_boundary)))
    return Contract.__table__, conds, cols, ts


def _orders_query(
    definition: MetricDefinition,
    window: Window,
    client_boundary: Optional[frozenset[int]] = None,
):
    # Start linii zamówienia zbiorczego = COALESCE(linia, grupa) — ta sama
    # reguła co `services/order_facts.py`.
    eff_start = func.coalesce(ClientOrder.start_date, ClientOrderGroup.start_date)
    cols = {"client": ClientOrder.client_id, "_ts_is_date": True}
    conds: list[Any] = []
    ts: Any = None
    if definition.measure == "ending_30_days":
        # Jedna reguła „kończy się bez kontynuacji" (audyt 24.09.2026, S1):
        # do tego dnia kafelek liczył też zamówienia z dodanym przedłużeniem
        # i linie MD wszystkich klientów (te kończy budżet, nie kalendarz),
        # więc pokazywał inną liczbę niż pigułka i panel „Moi klienci".
        # Linie BEZ budżetu MD (kosztowe) skaner domyka datą, więc liczą się
        # u każdego klienta — tak jak w dzwonku (audyt 24.09.2026, M9).
        conds.append(
            order_ending_without_continuation(
                window.today,
                window.today + timedelta(days=ORDERS_ENDING_DAYS),
                extended_client_ids=extended_order_alert_client_ids(),
                today=window.today,
                include_date_closed_lines=True,
            )
        )
    else:
        ts = eff_start
        conds += [
            ClientOrder.status.notin_(
                (ClientOrderStatus.cancelled, ClientOrderStatus.draft)
            ),
            ts >= window.start_date,
            ts < window.end_date,
        ]
    if definition.filters.client_ids:
        conds.append(ClientOrder.client_id.in_(definition.filters.client_ids))
    if client_boundary is not None:
        conds.append(ClientOrder.client_id.in_(sorted(client_boundary)))
    base = ClientOrder.__table__.outerjoin(
        ClientOrderGroup.__table__,
        ClientOrderGroup.id == ClientOrder.order_group_id,
    )
    return base, conds, cols, ts


async def _run_count(
    db: AsyncSession,
    definition: MetricDefinition,
    window: Window,
    author_ids: Optional[frozenset[int]],
    client_boundary: Optional[frozenset[int]] = None,
) -> tuple[float, list[dict[str, Any]], list[str]]:
    src = definition.source
    if src == "pipeline_moves":
        base, conds, cols, ts = _pipeline_query(definition, window, author_ids)
        measure = func.count()
    elif src == "candidates":
        base, conds, cols, ts = _candidates_query(definition, window, author_ids)
        measure = func.count()
    elif src == "jobs":
        base, conds, cols, ts = _jobs_query(definition, window, author_ids)
        measure = func.count()
    elif src == "contracts":
        base, conds, cols, ts = _contracts_query(definition, window, client_boundary)
        measure = func.count()
    else:
        base, conds, cols, ts = _orders_query(definition, window, client_boundary)
        measure = func.count()

    if definition.group_by == "none":
        value = (
            await db.execute(select(measure).select_from(base).where(*conds))
        ).scalar()
        return float(value or 0), [], []
    key = _group_column(definition, cols, ts).label("k")
    rows = (
        await db.execute(
            select(key, measure).select_from(base).where(*conds).group_by(key)
        )
    ).all()
    return await _grouped_series(db, definition, window, [(r[0], r[1]) for r in rows])


# ── Finanse ──────────────────────────────────────────────────────────────────

_FOLD_FIELD = {"revenue": "revenue", "margin": "margin", "cost": "cost"}


async def _run_finance(
    db: AsyncSession,
    definition: MetricDefinition,
    window: Window,
    boundary: Optional[frozenset[int]],
) -> tuple[Optional[float], list[dict[str, Any]], list[str], str]:
    requested = set(definition.filters.client_ids)
    if boundary is not None and requested - boundary:
        # Całościowa redakcja: klient spoza portfela = odmowa, nie częściowa suma.
        raise MetricAccessDenied(
            "Wybrani klienci są spoza Twojego portfela — kwot nie pokażemy."
        )
    clients = requested or (set(boundary) if boundary is not None else set())
    scope_applied = "portfolio" if boundary is not None and not requested else "all"

    stmt = (
        select(Contract)
        .where(
            Contract.status.in_(REVENUE_BEARING_STATUSES),
            Contract.start_date.is_not(None),
        )
        .options(selectinload(Contract.candidate), *RATE_SCHEDULE_LOADS)
    )
    if clients:
        stmt = stmt.where(Contract.client_id.in_(sorted(clients)))
    contracts = list((await db.execute(stmt)).scalars().all())
    currencies = {
        cur
        for c in contracts
        for cur in (c.resolved_rate_client_currency, c.resolved_rate_candidate_currency)
    }
    attr = _FOLD_FIELD[definition.measure]
    notes = [
        "Kwoty liczone z kontraktów w NEXUSIE (stawki z harmonogramów) — "
        "ewidencja kontraktów jest młodsza niż firma, więc starsze miesiące "
        "mogą być niepełne."
    ]

    def _value(fold: Any) -> Optional[float]:
        if not fold.complete:
            notes.append("Brak kursu waluty dla części kontraktów — kwota niepełna.")
        return money(getattr(fold, attr))

    if definition.group_by == "month":
        snaps = month_end_snapshots(window)
        rates = await rates_to_pln_by_date(
            db, {asof: currencies for _, _, asof in snaps}
        )
        series = []
        for key, label, asof in snaps:
            fold = fold_money(running_on(contracts, asof), asof, rates.get(asof, {}))
            series.append({"key": key, "label": label, "value": _value(fold)})
        value = series[-1]["value"] if series else None
        return value, series, sorted(set(notes)), scope_applied

    # Stan na koniec okresu (albo dziś, gdy okres trwa) — do 25.09.2026 każdy
    # okres liczył się na dziś, więc „marża w sierpniu" była dzisiejszym MRR.
    asof = window.asof
    if asof < window.today:
        notes.append(f"Kwoty według stanu na {asof.strftime('%d.%m.%Y')}.")
    rates = (await rates_to_pln_by_date(db, {asof: currencies})).get(asof, {})
    running = running_on(contracts, asof)
    total = _value(fold_money(running, asof, rates))
    if definition.group_by == "none":
        return total, [], sorted(set(notes)), scope_applied
    by_client: dict[int, list] = {}
    for c in running:
        by_client.setdefault(c.client_id, []).append(c)
    labels = await _labels(db, "client", list(by_client))
    series = [
        {
            "key": str(cid),
            "label": labels.get(cid, f"#{cid}"),
            "value": _value(fold_money(items, asof, rates)),
        }
        for cid, items in by_client.items()
    ]
    series.sort(key=lambda s: -(s["value"] or 0))
    if len(series) > TOP_BUCKETS:
        rest = [s["value"] for s in series[TOP_BUCKETS:] if s["value"] is not None]
        series = series[:TOP_BUCKETS] + [
            {"key": "other", "label": "Pozostali", "value": round(sum(rest), 2)}
        ]
    return total, series, sorted(set(notes)), scope_applied


# ── Wejście ──────────────────────────────────────────────────────────────────


async def evaluate_metric(
    db: AsyncSession,
    user: User,
    definition: MetricDefinition,
    *,
    today: date,
    scope: Optional[DashboardScope] = None,
) -> MetricResult:
    denial = source_denial(user, definition.source)
    if denial:
        raise MetricAccessDenied(denial)
    spec = SOURCES[definition.source]
    window = resolve_window(definition.period, today)
    snapshot = definition.measure in spec.snapshot_measures
    period_payload = {
        "key": definition.period,
        "label": "teraz" if snapshot else PERIOD_LABELS_PL[definition.period],
        "start": window.start_date.isoformat(),
        "end": (window.end_date - timedelta(days=1)).isoformat(),
    }

    if definition.source == "finance":
        boundary = await _finance_client_boundary(user, db)
        value, series, notes, applied = await _run_finance(
            db, definition, window, boundary
        )
        if definition.compare_previous:
            notes.append("Kwoty nie mają porównania z poprzednim okresem.")
        return MetricResult(
            value=value,
            series=series,
            unit="pln",
            scope_applied=applied,
            notes=notes,
            period=period_payload,
        )

    author_ids: Optional[frozenset[int]] = None
    applied = "all"
    if spec.supports_author:
        scope = scope or await resolve_dashboard_scope(user, db)
        author_ids = _author_ids(definition, user, scope)
        applied = definition.filters.author

    client_boundary: Optional[frozenset[int]] = None
    if definition.source in _DELIVERY_CLIENT_SOURCES:
        client_boundary = await _delivery_client_boundary(user, db)
        requested = set(definition.filters.client_ids)
        if client_boundary is not None and requested - client_boundary:
            # Lustro `_run_finance`: klient spoza portfela = odmowa całości,
            # nie cicha suma z samych „swoich" (runda 6 audytu).
            raise MetricAccessDenied(
                "Wybrani klienci są spoza Twojego portfela — tych danych nie pokażemy."
            )
        if client_boundary is not None and not requested:
            applied = "portfolio"

    value, series, notes = await _run_count(
        db, definition, window, author_ids, client_boundary
    )
    if (
        definition.source == "pipeline_moves"
        and author_ids is None
        and definition.group_by == "recruiter"
    ):
        # Runda 8 (R8-N10-7): podział po ludziach liczy zasługę jak „Moje
        # KPI" (kredyt weryfikatora, bez procesów spoza KPI), a liczba całej
        # firmy bez podziału — pierwsze wejście pary. Sumy mogą się różnić
        # i kafelek ma to powiedzieć, zamiast pokazać dwie liczby bez słowa.
        notes.append(
            "Podział po rekruterach liczy zasługę jak w „Moje KPI” — suma może "
            "różnić się od liczby całej firmy bez podziału."
        )
    previous: Optional[float] = None
    if definition.compare_previous:
        if snapshot:
            notes.append("Stan „teraz” nie ma porównania z poprzednim okresem.")
        else:
            prev_def = definition.model_copy(update={"group_by": "none"})
            previous, _, _ = await _run_count(
                db, prev_def, window.previous(), author_ids, client_boundary
            )
    return MetricResult(
        value=value,
        previous_value=previous,
        series=series,
        unit="count",
        scope_applied=applied,
        notes=notes,
        period=period_payload,
    )


async def access_fingerprint(
    db: AsyncSession, user: User, definition: MetricDefinition
) -> str:
    """Odcisk uprawnień, od których zależy wynik — część klucza cache.

    Runda 8 (R8-N10-4): wynik z cache (2 min) wychodził przed
    ``evaluate_metric``, a klucz nie niósł sekcji ani portfela, więc przez
    dwie minuty po odebraniu sekcji albo klienta kafelek dalej pokazywał dane.
    Ta funkcja sprawdza źródło PRZED cache (rzuca ``MetricAccessDenied``)
    i oddaje granicę klientów, która zmienia klucz przy każdej zmianie
    portfela albo capability.
    """
    denial = source_denial(user, definition.source)
    if denial:
        raise MetricAccessDenied(denial)
    boundary: Optional[frozenset[int]] = None
    if definition.source == "finance":
        boundary = await _finance_client_boundary(user, db)
    elif definition.source in _DELIVERY_CLIENT_SOURCES:
        boundary = await _delivery_client_boundary(user, db)
    if boundary is None:
        return "all"
    return ",".join(str(cid) for cid in sorted(boundary))


async def metric_catalog(db: AsyncSession, user: User) -> dict[str, Any]:
    """Źródła, miary, podziały i „czyje dane" dostępne DLA TEGO konta."""
    scope = await resolve_dashboard_scope(user, db)
    sources = []
    for key, spec in SOURCES.items():
        denial = source_denial(user, key)
        sources.append(
            {
                "key": key,
                "label": spec.label,
                "available": denial is None,
                "reason": denial,
                "measures": [
                    {
                        "key": mk,
                        "label": ml,
                        "snapshot": mk in spec.snapshot_measures,
                    }
                    for mk, ml in spec.measures.items()
                ],
                "group_by": list(spec.group_by),
                "filters": list(spec.filters),
                "supports_author": spec.supports_author,
            }
        )
    return {
        "sources": sources,
        "authors": list(allowed_authors(scope)),
        "stages": [{"key": s, "label": STAGE_LABELS_PL[s]} for s in MILESTONE_STAGES],
        "periods": [{"key": k, "label": v} for k, v in PERIOD_LABELS_PL.items()],
    }


__all__ = [
    "MetricAccessDenied",
    "access_fingerprint",
    "MetricResult",
    "allowed_authors",
    "evaluate_metric",
    "metric_catalog",
    "source_denial",
]
