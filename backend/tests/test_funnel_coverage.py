"""Które etapy lejka mają pokrycie w imporcie — i czy nikt tej wiedzy nie zdublował.

Kafle dashboardu podawały `akceptacja → placement = 3257,1%` przy
`data_quality.status = "complete"`, bo etap `acceptance` nie ma mapowania
z Traffita (7 wystąpień rocznie wobec 228 placementów, pomiar 2026-09-02).

Te testy pilnują trzech rzeczy: że zbiór etapów bez pokrycia jest WYPROWADZONY
z tabeli mapera (a nie przepisany, więc po domknięciu mapowania skurczy się
sam), że każda konwersja deklaruje swoje operandy, i że te operandy są realnymi
etapami, a nie literówkami.
"""

from __future__ import annotations

import dataclasses

from app.models.recruitment_pipeline import PipelineStage
from app.services.funnel_coverage import (
    CONVERSION_OPERAND_STAGES,
    COVERAGE_STARTED_AT,
    STAGES_WITHOUT_TRAFFIT_COVERAGE,
    coverage_note,
    uncovered_conversions,
    uncovered_stages_for_window,
)
from app.services.recruitment_trend import FunnelConversions
from app.services.traffit.mappers import (
    _DEFAULT_STATE_MAPPING,
    _TRAFFIT_STATE_NAME_MAP,
    _TRAFFIT_STATE_TYPE_MAP,
    TRAFFIT_MAPPED_LEGACY_STAGES,
)


def test_uncovered_stages_are_derived_from_the_mapper_not_copied():
    """Literał OBOK derywacji — derywacja porównana sama ze sobą nie dowodzi niczego.

    Sam test „wyprowadzone == wyprowadzone" przechodzi niezależnie od tego, czy
    wynik jest prawdziwy. Literał przypina, CO dziś z tego wychodzi; derywacja
    przypina, że nikt nie utrzymuje drugiej kopii listy.
    """
    # Po domknięciu mapowania po NAZWIE stanu („Zaakceptowany",
    # „Interview u klienta") zbiór skurczył się SAM — to jest dowód, że
    # derywacja działa, a nie że ktoś utrzymuje drugą kopię listy.
    assert STAGES_WITHOUT_TRAFFIT_COVERAGE == {
        "negotiation",
        "onboarding",
        "prep_call",
    }
    # …ale etapy ze ŚWIEŻYM mapowaniem nadal nie mają danych historycznych,
    # więc bez podanego okna traktujemy je jak niepokryte.
    assert set(COVERAGE_STARTED_AT) == {"acceptance", "client_interview"}
    assert TRAFFIT_MAPPED_LEGACY_STAGES == (
        {mapping["legacy"] for mapping in _TRAFFIT_STATE_TYPE_MAP.values()}
        | {mapping["legacy"] for mapping in _TRAFFIT_STATE_NAME_MAP.values()}
        | {_DEFAULT_STATE_MAPPING["legacy"]}
    )


def test_every_conversion_field_declares_its_operand_stages():
    """Siódma konwersja bez wpisu w mapie operandów ma WYSYPAĆ test…

    …a nie po cichu ominąć strażnik pokrycia i wrócić na kafel jako pewna.
    """
    fields = {
        f.name
        for f in dataclasses.fields(FunnelConversions)
        if f.name.endswith("_pct")
    }
    assert set(CONVERSION_OPERAND_STAGES) == fields


def test_operand_stages_are_real_pipeline_stages():
    """Literówka w nazwie etapu nie może udawać „etapu bez pokrycia"."""
    for field, operands in CONVERSION_OPERAND_STAGES.items():
        for stage in operands:
            PipelineStage(stage)  # ValueError = literówka


def test_predicate_covers_any_operand_not_only_the_denominator():
    """Ta sama siódemka psuje dwie liczby — raz jako mianownik, raz jako licznik."""
    suppressed = set(uncovered_conversions(uncovered_stages_for_window(None)))
    # mianownik `acceptance`
    assert "acceptance_to_placement_pct" in suppressed
    # licznik `acceptance`, mianownik `interview` (zdrowy!)
    assert "interview_to_acceptance_pct" in suppressed
    # cztery zdrowe zostają nietknięte
    assert suppressed == {
        "acceptance_to_placement_pct",
        "interview_to_acceptance_pct",
    }


def test_note_names_actual_stages_so_it_cannot_go_stale():
    note = coverage_note(uncovered_stages_for_window(None))
    assert note is not None
    assert "Akceptacja" in note
    # Etapy, których żadna konwersja nie dotyka, nie zaśmiecają komunikatu.
    assert "Onboarding" not in note
    assert coverage_note(frozenset()) is None


def test_window_before_a_stage_gained_coverage_stays_suppressed(monkeypatch):
    """Domknięcie mapowania nie może odsłonić 3257% dla okien historycznych.

    Mapper działa na PRZYSZŁE importy — 194 891 historycznych wierszy nie jest
    przepisywanych — więc sam skurczony zbiór odsłoniłby metrykę dla stycznia,
    w którym danych i tak nie ma.
    """
    from datetime import date

    import app.services.funnel_coverage as fc

    monkeypatch.setattr(fc, "STAGES_WITHOUT_TRAFFIT_COVERAGE", frozenset())
    monkeypatch.setattr(fc, "COVERAGE_STARTED_AT", {"acceptance": date(2034, 6, 1)})

    assert "acceptance" in fc.uncovered_stages_for_window(date(2034, 1, 1))
    assert "acceptance" not in fc.uncovered_stages_for_window(date(2034, 7, 1))


def test_a_window_after_the_mapping_landed_sees_the_stage_as_covered():
    """Okno po wdrożeniu mapowania odsłania metrykę — wygaszenie nie jest wieczne."""
    from datetime import date

    assert "acceptance" not in uncovered_stages_for_window(date(2026, 12, 1))
    assert "acceptance" in uncovered_stages_for_window(date(2026, 1, 1))


def test_missing_window_suppresses_the_widest_set_not_the_narrowest():
    """Brak okna = „nie wiem", a nie „wszystko pokryte"."""
    assert uncovered_stages_for_window(None) == (
        STAGES_WITHOUT_TRAFFIT_COVERAGE | set(COVERAGE_STARTED_AT)
    )
