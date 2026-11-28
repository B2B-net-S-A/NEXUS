"""Contracts for the compact, drillable recruitment activity dashboard."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


RecruitmentActivityMetric = Literal[
    "verification",
    "recommendation",
    "interview",
    "acceptance",
    "placement",
]
# „week” = tydzień (pon–niedz) wybranego dnia, jak cel „Rekomendacje w tygodniu”;
# „range” = dowolne dni od–do (okres z paska Insights). 17.10.2026.
RecruitmentActivityWindow = Literal["day", "week", "month", "range"]
RecruitmentActivityScope = Literal["person", "team"]
# Lista „Kto się liczy”: osoba, cały zespół albo kamienie bez osoby z zasługą.
RecruitmentActivityDetailScope = Literal["person", "team", "unattributed"]
# Gdzie para osoba × rekrutacja jest teraz (najnowszy wiersz etapu pary).
RecruitmentActivityDetailOrder = Literal["reached", "term"]
RecruitmentActivityState = Literal[
    "before_client",
    "waiting",
    "at_client",
    "hired",
    "rejected_by_client",
    "ended",
    "job_closed",
]


class RecruitmentActivityModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecruitmentActivityClient(RecruitmentActivityModel):
    """Klient do filtra (10.11.2026): wiersze okresu po filtrze roli."""

    id: int
    name: str
    count: int


class RecruitmentActivityPerson(RecruitmentActivityModel):
    id: int
    name: str
    role: str


class RecruitmentActivityMetricCounts(RecruitmentActivityModel):
    metric: RecruitmentActivityMetric
    day: int | None
    # Liczba okresu `period_start`–`period_end`: miesiąc albo wybrane od–do.
    month: int


class RecruitmentActivityProgress(RecruitmentActivityModel):
    current: int
    target: int
    progress_pct: float
    remaining: int


class RecruitmentActivityComparison(RecruitmentActivityModel):
    metric: Literal["verification", "placement"]
    personal_average: float | None
    team_average: float | None
    months: int
    period_start: date
    period_end: date
    people: int


class RecruitmentActivitySummaryResponse(RecruitmentActivityModel):
    generated_at: datetime
    day: date
    month: date
    # Dni, które liczy `metrics[].month` (włącznie) — miesiąc albo od–do.
    period_start: date | None = None
    period_end: date | None = None
    scope: RecruitmentActivityScope
    can_view_team_details: bool
    subject: RecruitmentActivityPerson | None = None
    selectable_people: list[RecruitmentActivityPerson] = Field(default_factory=list)
    metrics: list[RecruitmentActivityMetricCounts] = Field(default_factory=list)
    verification_progress: RecruitmentActivityProgress | None = None
    comparisons: list[RecruitmentActivityComparison] = Field(default_factory=list)
    # Klienci z ruchem w okresie (wszystkie etapy), tylko w zakresie zespołu.
    clients: list[RecruitmentActivityClient] = Field(default_factory=list)


class RecruitmentActivityCandidate(RecruitmentActivityModel):
    id: int
    name: str
    href: str


class RecruitmentActivityJob(RecruitmentActivityModel):
    id: int
    # Nazwa od klienta; ekrany wewnętrzne pokazują `working_title ?? title`
    # z numerem u klienta (trzy nazwy rekrutacji).
    title: str
    working_title: str | None = None
    client_reference: str | None = None
    client_name: str
    href: str


class RecruitmentActivityMargin(RecruitmentActivityModel):
    """Marża placementu (27.11.2026): zł/h z dnia startu, jak eksport „Placementy”.

    Stawki w swojej walucie, marża w PLN. ``missing`` = liczby nie ma
    (brak kontraktu, stawki albo kursu) — nigdy zgadnięta.
    """

    cost_per_hour: float | None = None
    client_per_hour: float | None = None
    cost_currency: str = "PLN"
    client_currency: str = "PLN"
    per_hour: float | None = None
    per_month: float | None = None
    percent: float | None = None
    # Kontrakt bez stawki klienta — wzięta stawka „do klienta” z rekrutacji.
    client_from_recruitment: bool = False
    missing: Literal["no_contract", "missing_rates", "fx_missing"] | None = None


class RecruitmentActivityMarginSummary(RecruitmentActivityModel):
    """Suma marży z wierszy okresu, które odbiorca widzi (przed filtrem stanu)."""

    per_hour: float
    per_month: float
    counted: int
    from_recruitment: int
    negative: int
    # Placementy klientów spoza portfela DL-a (bez kwot).
    hidden: int
    missing: int


class RecruitmentActivityDetailItem(RecruitmentActivityModel):
    candidate: RecruitmentActivityCandidate
    job: RecruitmentActivityJob
    credited_user: RecruitmentActivityPerson | None = None
    reached_at: datetime
    # Kto kliknął etap. Przy rekomendacji to zwykle Delivery Lead, a zasługa
    # idzie do osoby, która zweryfikowała kandydata.
    moved_by: RecruitmentActivityPerson | None = None
    state: RecruitmentActivityState | None = None
    state_stage: str | None = None
    state_since: datetime | None = None
    # Nazwa etapu z procesu klienta (np. „Wysłać do Cpro”); przy odrzuceniu
    # i rezygnacji — etap, na którym para odpadła.
    state_stage_name: str | None = None
    state_reason: str | None = None
    # W ilu rekrutacjach ta sama osoba liczy się w tym okresie (≥ 1).
    candidate_jobs: int = 1
    # Reguły: `services/client_interview_terms.py`.
    client_interview_at: datetime | None = None
    client_interview_tentative_at: datetime | None = None
    start_on: date | None = None
    # Tylko placementy i tylko dla odbiorcy z prawem do kwot klienta.
    margin: RecruitmentActivityMargin | None = None
    # Klient spoza portfela Delivery Leada: kwot nie ma, front pisze „—”.
    margin_hidden: bool = False


class RecruitmentActivityDetailResponse(RecruitmentActivityModel):
    generated_at: datetime
    metric: RecruitmentActivityMetric
    window: RecruitmentActivityWindow
    page: int
    page_size: int
    total: int
    items: list[RecruitmentActivityDetailItem] = Field(default_factory=list)
    # Dni od–do (włącznie), które lista pokazuje.
    period_start: date | None = None
    period_end: date | None = None
    scope: RecruitmentActivityDetailScope | None = None
    subject: RecruitmentActivityPerson | None = None
    # Różne osoby za `total` wierszami (jedna osoba w dwóch rekrutacjach to dwa wiersze).
    people: int = 0
    # Wiersze, w których etap kliknęła osoba z zasługą.
    moved_by_credited: int = 0
    # Liczba wierszy w każdym stanie dla całego okresu, przed filtrem `state`.
    states: dict[RecruitmentActivityState, int] = Field(default_factory=dict)
    state_filter: RecruitmentActivityState | None = None
    # Liczba w okresie przed filtrem `state` (`total` jest po filtrze) — razem
    # z `history_total`, czyli tak jak licznik celów.
    period_total: int = 0
    # Ile z `period_total` to tygodniowe wpisy DynaReportera (1.01–11.10.2026):
    # są w liczbie, ale nie na liście — DynaReporter nie zna kandydatów.
    history_total: int = 0
    # Klienci tego etapu w okresie po filtrze roli, przed filtrem klienta.
    clients: list[RecruitmentActivityClient] = Field(default_factory=list)
    # Marża placementów: „all” (Finanse), „portfolio” (DL — klienci z portfela),
    # None = lista bez kwot (Head of Recruitment, TCM, rekruter).
    margin_scope: Literal["all", "portfolio"] | None = None
    margin_summary: RecruitmentActivityMarginSummary | None = None


class RecruitmentActivityTeamTotalsResponse(RecruitmentActivityModel):
    """Liczby zespołu za dni od–do dla kilku etapów naraz (kafel „Wyniki
    zespołu”, 27.10.2026) — każda równa ``period_total`` listy „Kto się
    liczy” tego etapu w zakresie zespołu."""

    generated_at: datetime
    period_start: date
    period_end: date
    totals: dict[RecruitmentActivityMetric, int] = Field(default_factory=dict)
    # Ile z liczby to wpisy DynaReportera (bez osób na liście).
    history: dict[RecruitmentActivityMetric, int] = Field(default_factory=dict)
    # Klienci tych etapów w okresie po filtrze roli (filtr kafla, 10.11.2026).
    clients: list[RecruitmentActivityClient] = Field(default_factory=list)
