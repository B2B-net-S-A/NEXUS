"""Kształt raportu kompetencji wysyłanego mailem w 24 godziny (decyzje Artura 25.11.2026).

Raport dostaje osoba, która wysłała z nowej strony b2bnetwork.ai CV razem z warunkami
(stawka, tryb pracy, dni w biurze, miasta, start). Silnik (`competence_report_engine`)
składa ``ReportSnapshot``, mail (`competence_report_email`) go rysuje, kolejka
rekrutera i strona tokenu go pokazują. Snapshot leży w ``competence_reports.snapshot``
(JSONB), więc mail wysłany po 23 godzinach pokazuje to samo, co rekruter widział w kolejce.

Zasady treści (plan: b2bnetwork-www ``docs/raport-24h-wdrozenie.md``):
- stawki rynku tylko z rozmów (``candidates.rate_latest_hourly``), grupa co najmniej
  ``MIN_GROUP`` osób, przy mniejszej szersza grupa i ``widened=True``;
- projekty bez nazwy klienta, budżet zaokrąglony w dół do 5 zł;
- wariant ``limited`` (CV spoza IT, brak roli albo stawek) nie ma sekcji ze stawką.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1
MIN_GROUP = 30

ContractForm = Literal["b2b", "uop", "any"]
WorkMode = Literal["remote", "hybrid", "onsite"]
StartWhen = Literal["now", "1m", "2-3m", "browsing"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReportConditions(_Frozen):
    """Warunki z formularza, dosłownie jak je podał kandydat (``competence_reports.conditions``)."""

    rate: int = Field(ge=1, le=2000, description="oczekiwana stawka, zł/h netto")
    current_rate: Optional[int] = Field(default=None, ge=1, le=2000)
    contract: ContractForm = "b2b"
    modes: tuple[WorkMode, ...] = ()
    office_days_max: Optional[int] = Field(default=None, ge=0, le=5)
    office_cities: tuple[str, ...] = ()
    start: Optional[StartWhen] = None


class ReportProfile(_Frozen):
    """Jak odczytaliśmy CV: pokazujemy to w nagłówku maila, żeby kandydat mógł poprawić."""

    role_label: str = Field(
        description="np. „Java”, „Tester”, kategoria kompetencji albo główna technologia"
    )
    years: Optional[int] = None
    city: Optional[str] = None


class MarketGroup(_Frozen):
    role_label: str
    years_bucket: Optional[str] = Field(default=None, description="np. „8+”, „5–8”")
    city: Optional[str] = None
    widened: bool = Field(
        default=False, description="grupa poszerzona, bo węższa miała < MIN_GROUP osób"
    )


class MarketRate(_Frozen):
    group: MarketGroup
    p25: int
    median: int
    p75: int
    n: int = Field(ge=MIN_GROUP)


class RatePosition(_Frozen):
    expected: int
    expected_vs_median_pct: int = Field(
        description="zaokrąglone, ujemne = poniżej mediany"
    )
    current: Optional[int] = None
    current_vs_median_pct: Optional[int] = None


class FunnelStep(_Frozen):
    key: Literal["tech", "office_days", "location", "budget", "contract"]
    label: str
    count: int = Field(ge=0)


class Lever(_Frozen):
    """Jedna zmiana warunku i ile projektów by dodała (pokazujemy tylko gain >= 1)."""

    key: Literal[
        "office_days_plus1", "extra_city", "rate_to_median", "remote_to_hybrid"
    ]
    label: str
    hint: Optional[str] = None
    gain: int = Field(ge=1)


class TechPremium(_Frozen):
    name: str
    premium: int = Field(description="różnica median zł/h w tej samej grupie")
    months: Optional[int] = Field(default=None, description="miesiące użycia z CV")


class MissingTech(_Frozen):
    name: str
    premium: Optional[int] = None
    jobs: int = Field(ge=1, description="w ilu otwartych projektach jest wymagana")
    of: int = Field(ge=1, description="z ilu projektów z główną technologią kandydata")


class ReportJob(_Frozen):
    job_id: int = Field(
        description="tylko do kolejki rekrutera; mail i strona tokenu go nie pokazują"
    )
    title: str = Field(description="publiczny tytuł, bez nazwy klienta")
    budget_max: Optional[int] = Field(
        default=None, description="zaokrąglony w dół do 5 zł"
    )
    skills: tuple[str, ...] = ()
    place: Optional[str] = Field(
        default=None, description="np. „Kraków, 2 dni w biurze” albo „zdalnie”"
    )
    meets: bool
    miss_reason: Optional[str] = Field(
        default=None, description="np. „o 1 dzień w biurze za dużo”"
    )


class ReportOwner(_Frozen):
    user_id: int
    name: str


class ReportSnapshot(_Frozen):
    version: int = SCHEMA_VERSION
    variant: Literal["full", "limited"] = "full"
    conditions: ReportConditions
    profile: ReportProfile
    market: Optional[MarketRate] = None
    rate_position: Optional[RatePosition] = None
    funnel: tuple[FunnelStep, ...] = ()
    levers: tuple[Lever, ...] = ()
    strongest_tech: Optional[TechPremium] = None
    missing_tech: Optional[MissingTech] = None
    jobs: tuple[ReportJob, ...] = ()
    owner: Optional[ReportOwner] = None


def round_budget(value: float | int | None) -> Optional[int]:
    """Budżet projektu w mailu: w dół do pełnych 5 zł, żeby nie zdradzać stawek 1:1."""
    if value is None or value <= 0:
        return None
    return int(value) // 5 * 5
