"""Które etapy lejka mają pokrycie w danych, a które nie.

Powstało, bo kafle dashboardu podawały `akceptacja → placement = 3257,1%`
przy `data_quality.status = "complete"` (pomiar produkcyjny 2026-09-02:
7 akceptacji rocznie wobec 228 placementów). Etap `acceptance` nie ma
mapowania z Traffita, więc te siedem wystąpień to ręczne ruchy — mianownik,
który nie opisuje rzeczywistości. Metryka bez pokrycia ma mówić „nie wiem",
a nie podawać liczbę jako pewną.

**Predykat obejmuje KAŻDY operand, nie tylko mianownik.** Ta sama siódemka
psuje dwie liczby na raz: `acceptance_to_placement_pct` przez mianownik
(228/7 = 3257,1%) i `interview_to_acceptance_pct` przez licznik
(7/3500 = 0,2%). Reguła „tylko mianownik" zostawiłaby 0,2% na kaflu jako
pewne.

Zbiór etapów bez pokrycia jest **wyprowadzony** z tabeli mapera Traffita, nie
przepisany — po domknięciu mapowania skurczy się sam i metryki odżyją bez
commita w tej warstwie. `COVERAGE_STARTED_AT` pilnuje, żeby nie odżyły dla
okien historycznych, w których danych i tak nie ma.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Optional

from app.models.recruitment_pipeline import PipelineStage
from app.schemas.pipeline import STAGE_LABELS
from app.services.traffit.mappers import TRAFFIT_MAPPED_LEGACY_STAGES

# Etapy, których import z Traffita nigdy nie zapełnia. Dziś:
# {acceptance, client_interview, negotiation, onboarding, prep_call}.
STAGES_WITHOUT_TRAFFIT_COVERAGE: frozenset[str] = frozenset(
    {stage.value for stage in PipelineStage} - set(TRAFFIT_MAPPED_LEGACY_STAGES)
)

# Etap uznajemy za pokryty dopiero dla okien ZACZYNAJĄCYCH SIĘ po dacie, od
# której mapowanie realnie zapełnia dane.
#
# Bez tego domknięcie mapowania odsłoniłoby 3257,1% z powrotem dla stycznia,
# lutego i każdego innego okna sprzed zmiany — zbiór by się skurczył, a dane
# historyczne zostałyby takie, jakie są (mapper działa na PRZYSZŁE importy;
# 194 891 historycznych wierszy świadomie nie jest przepisywanych).
#
# Wpis dodaj W TYM SAMYM commicie co zmiana `_TRAFFIT_STATE_TYPE_MAP`.
COVERAGE_STARTED_AT: dict[str, date] = {}

# Mapa: pole konwersji → (etap licznika, etap mianownika).
#
# JEDYNE miejsce, w którym ta wiedza jest zapisana. Etapy są nazwane wartościami
# `PipelineStage` (angielskie), a nie polskimi nazwami argumentów
# `funnel_conversions` — inaczej powstałaby czwarta kopia nazewnictwa obok
# `_STAGE_FIELDS` w `recruitment_trend`.
CONVERSION_OPERAND_STAGES: dict[str, tuple[str, str]] = {
    "verified_to_recommendation_pct": ("cv_sent", "verified"),
    "recommendation_to_interview_pct": ("interview", "cv_sent"),
    "interview_to_acceptance_pct": ("acceptance", "interview"),
    "acceptance_to_placement_pct": ("hired", "acceptance"),
    "interview_to_placement_pct": ("hired", "interview"),
    "overall_pct": ("hired", "verified"),
}


def uncovered_stages_for_window(
    window_start: Optional[datetime | date] = None,
) -> frozenset[str]:
    """Etapy bez pokrycia dla okna zaczynającego się `window_start`.

    Etap, którego mapowanie domknięto, wraca do puli pokrytych dopiero dla
    okien zaczynających się od tej daty — wcześniejsze okna nadal go nie mają.
    """

    if window_start is None or not COVERAGE_STARTED_AT:
        return STAGES_WITHOUT_TRAFFIT_COVERAGE

    start = window_start.date() if isinstance(window_start, datetime) else window_start
    covered_late = {
        stage for stage, since in COVERAGE_STARTED_AT.items() if start < since
    }
    return frozenset(STAGES_WITHOUT_TRAFFIT_COVERAGE | covered_late)


def uncovered_conversions(uncovered_stages: Iterable[str]) -> tuple[str, ...]:
    """Pola konwersji, których KTÓRYKOLWIEK operand nie ma pokrycia."""

    without = set(uncovered_stages)
    return tuple(
        field
        for field, operands in CONVERSION_OPERAND_STAGES.items()
        if without.intersection(operands)
    )


def stage_label(stage: str) -> str:
    try:
        return STAGE_LABELS[PipelineStage(stage)]
    except (KeyError, ValueError):  # pragma: no cover - etap spoza enuma
        return stage


def coverage_note(uncovered_stages: Iterable[str]) -> Optional[str]:
    """Zdanie dla użytkownika — budowane z FAKTYCZNYCH nazw etapów.

    Nazwy nie są zaszyte w tekście, więc po zmianie mapowania komunikat zmieni
    się razem ze zbiorem zamiast kłamać o „Akceptacji".
    """

    relevant = {
        stage
        for stage in uncovered_stages
        if any(
            stage in operands
            for field, operands in CONVERSION_OPERAND_STAGES.items()
            if field in uncovered_conversions(uncovered_stages)
        )
    }
    if not relevant:
        return None
    names = ", ".join(sorted(stage_label(stage) for stage in relevant))
    return (
        f"Konwersje przez etapy bez pokrycia w imporcie ({names}) są wygaszone "
        "— tych etapów nie zapełnia synchronizacja z Traffita, więc iloraz "
        "przez nie nie opisywałby rzeczywistości."
    )


__all__ = [
    "CONVERSION_OPERAND_STAGES",
    "COVERAGE_STARTED_AT",
    "STAGES_WITHOUT_TRAFFIT_COVERAGE",
    "coverage_note",
    "stage_label",
    "uncovered_conversions",
    "uncovered_stages_for_window",
]
