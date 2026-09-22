"""Definicja własnej metryki pulpitu — deklaratywna, bez SQL od użytkownika.

Kreator na froncie składa ten obiekt z pięciu kroków (źródło → co liczymy →
filtry → podział i okres → wygląd). Serwer przyjmuje WYŁĄCZNIE wartości ze
słowników poniżej: każde źródło ma zamkniętą listę miar i podziałów, a filtry
to listy identyfikatorów. Nie ma tu miejsca na kolumnę ani wyrażenie podane
z zewnątrz — tak kreator nie staje się drugim, niechronionym API do bazy.

Ta sama klasa waliduje kafelki metryk zapisane w układzie pulpitu
(``app/services/dashboard_tiles.py``), więc zapisany kafelek nie może nieść
definicji, której silnik by nie policzył.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

MetricSource = Literal[
    "pipeline_moves", "candidates", "jobs", "contracts", "orders", "finance"
]
MetricGroupBy = Literal[
    "none", "week", "month", "client", "recruiter", "stage", "competence_category"
]
MetricAuthor = Literal["me", "team", "all"]
MetricPeriod = Literal[
    "last_7_days",
    "last_30_days",
    "last_8_weeks",
    "last_12_weeks",
    "last_90_days",
    "this_month",
    "last_month",
    "this_quarter",
    "this_year",
    "last_12_months",
]

# Etapy liczone z widoku `analytics_first_milestones` — PIERWSZE wejście pary
# (kandydat, rekrutacja) na etap (reguła D2, ta sama co Insights). Inne etapy
# świadomie poza kreatorem: surowe `candidate_stages` dubluje powroty na etap.
# Przypisanie do LUDZI (autor „moje"/„mój zespół", podział po rekruterze) idzie
# kredytem jak w „Moje KPI" (`VERIFIER_ANCHORED_CTE` — pierwszy zaakceptowany
# weryfikator pary), nie osobą, która kliknęła etap (decyzja 22.09.2026).
# Wykluczone placementy (0343) nie liczą się w żadnym wariancie.
MILESTONE_STAGES: tuple[str, ...] = (
    "verified",
    "cv_sent",
    "interview",
    "client_interview",
    "acceptance",
    "hired",
)
STAGE_LABELS_PL: dict[str, str] = {
    "verified": "Zweryfikowani",
    "cv_sent": "CV wysłane",
    "interview": "Rozmowa",
    "client_interview": "Rozmowa z klientem",
    "acceptance": "Akceptacja",
    "hired": "Zatrudnieni",
}


class SourceSpec(BaseModel):
    """Co wolno zrobić z jednym źródłem. Czytają to walidator i katalog."""

    label: str
    measures: dict[str, str]
    # Miary „stan na dziś" nie mają okresu ani porównania z poprzednim.
    snapshot_measures: frozenset[str] = frozenset()
    group_by: tuple[str, ...]
    supports_author: bool
    filters: tuple[str, ...]


SOURCES: dict[str, SourceSpec] = {
    "pipeline_moves": SourceSpec(
        label="Ruchy w pipeline",
        measures={"first_reach": "Liczba pierwszych wejść na etap"},
        group_by=(
            "none",
            "week",
            "month",
            "client",
            "recruiter",
            "stage",
            "competence_category",
        ),
        supports_author=True,
        filters=("client_ids", "competence_category_ids", "job_ids"),
    ),
    "candidates": SourceSpec(
        label="Kandydaci",
        measures={"new": "Nowi kandydaci w bazie"},
        group_by=("none", "week", "month", "recruiter", "competence_category"),
        supports_author=True,
        filters=("competence_category_ids",),
    ),
    "jobs": SourceSpec(
        label="Rekrutacje",
        measures={
            "opened": "Otwarte rekrutacje (w okresie)",
            "closed": "Zamknięte rekrutacje (w okresie)",
            "open_now": "Rekrutacje otwarte teraz",
        },
        snapshot_measures=frozenset({"open_now"}),
        group_by=(
            "none",
            "week",
            "month",
            "client",
            "recruiter",
            "competence_category",
        ),
        supports_author=True,
        filters=("client_ids", "competence_category_ids"),
    ),
    "contracts": SourceSpec(
        label="Kontrakty",
        measures={
            "active_now": "Aktywne kontrakty teraz",
            "started": "Rozpoczęte kontrakty",
            "ended": "Zakończone kontrakty",
        },
        snapshot_measures=frozenset({"active_now"}),
        group_by=("none", "week", "month", "client"),
        supports_author=False,
        filters=("client_ids",),
    ),
    "orders": SourceSpec(
        label="Zamówienia",
        measures={
            "ending_30_days": "Kończące się w ciągu 30 dni",
            "started": "Rozpoczęte zamówienia",
        },
        snapshot_measures=frozenset({"ending_30_days"}),
        group_by=("none", "week", "month", "client"),
        supports_author=False,
        filters=("client_ids",),
    ),
    "finance": SourceSpec(
        label="Finanse",
        measures={
            "revenue": "Przychód miesięczny (PLN)",
            "margin": "Marża miesięczna (PLN)",
            "cost": "Koszt konsultantów miesięczny (PLN)",
        },
        group_by=("none", "month", "client"),
        supports_author=False,
        filters=("client_ids",),
    ),
}

MAX_FILTER_IDS = 20


class MetricFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_ids: list[int] = Field(default_factory=list, max_length=MAX_FILTER_IDS)
    competence_category_ids: list[int] = Field(
        default_factory=list, max_length=MAX_FILTER_IDS
    )
    job_ids: list[int] = Field(default_factory=list, max_length=MAX_FILTER_IDS)
    author: MetricAuthor = "me"


class MetricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: MetricSource
    measure: str = Field(max_length=40)
    stage: Optional[str] = Field(default=None, max_length=40)
    filters: MetricFilters = Field(default_factory=MetricFilters)
    group_by: MetricGroupBy = "none"
    period: MetricPeriod = "last_30_days"
    compare_previous: bool = False

    @model_validator(mode="after")
    def _check_against_source(self) -> "MetricDefinition":
        spec = SOURCES[self.source]
        if self.measure not in spec.measures:
            raise ValueError(f"Źródło „{spec.label}” nie liczy miary „{self.measure}”.")
        if self.group_by not in spec.group_by:
            raise ValueError(
                f"Źródła „{spec.label}” nie da się podzielić po „{self.group_by}”."
            )
        for key in ("client_ids", "competence_category_ids", "job_ids"):
            if getattr(self.filters, key) and key not in spec.filters:
                raise ValueError(f"Źródło „{spec.label}” nie ma filtra „{key}”.")
        if self.source == "pipeline_moves":
            if self.stage is None and self.group_by != "stage":
                raise ValueError("Wybierz etap albo podział po etapach.")
            if self.stage is not None and self.stage not in MILESTONE_STAGES:
                raise ValueError(f"Nieznany etap „{self.stage}”.")
            if self.stage is not None and self.group_by == "stage":
                raise ValueError("Podział po etapach liczy wszystkie etapy naraz.")
        elif self.stage is not None:
            raise ValueError("Etap dotyczy tylko ruchów w pipeline.")
        if self.measure in spec.snapshot_measures and self.group_by in (
            "week",
            "month",
        ):
            raise ValueError("Stanu „teraz” nie da się rozłożyć na oś czasu.")
        return self
