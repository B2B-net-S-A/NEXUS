"""Jedna reguła „dopisek w imieniu” (D6, 13.10.2026) — testy bez bazy.

Przypadki z produkcji z 13.10.2026 są tu jawnie (z wymyślonymi imionami —
repo jest publiczne): dziewięć dopisków, które reguła MUSI złapać, i 21 drugich
nazwisk w nawiasie, które MUSI przepuścić. Zawężenie albo poszerzenie reguły
zapala się tutaj, a nie na produkcji, gdzie objawem jest odmowa zapisu
prawdziwego nazwiska albo osoba z czarnej listy proponowana klientowi.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.candidate_name_marker_repair import (
    DETAILS_KEY,
    EMPTY_NAME_PLACEHOLDER,
    REPAIR_MARKER,
    NameMarkerRow,
    build_receipt,
    plan_fix,
    summarize_for_log,
)
from app.services.candidate_name_rules import (
    NAME_MARKER_ERROR_TYPE,
    find_name_markers,
    has_active_marker,
    has_blacklist_marker,
    name_marker_message,
    strip_name_markers,
    without_name_markers,
)
from app.services.traffit.mappers import traffit_employee_to_candidate

BACKEND = Path(__file__).resolve().parents[1]

# (surowe pole, oczekiwane po zdjęciu) — dziewięć dopisków z produkcji.
PRODUCTION_MARKERS = [
    ("[ACTIVE] Zbigniew", "Zbigniew"),
    ("Kowalski (zaakceptowany)", "Kowalski"),
    ("(zaakceptowany) Marek", "Marek"),
    ("Nowak (ekspracownik)", "Nowak"),
    ("Wiśniewski (eks-pracownik)", "Wiśniewski"),
    ("Anna (czarna lista)", "Anna"),
    ("Lewandowski (na projekt dodatkowy)", "Lewandowski"),
    ("Zielińska (poprawiony nr telefonu)", "Zielińska"),
    ("Kamińska (CIPP/E)", "Kamińska"),
]

# Drugie nazwisko w nawiasie — 21 form, które zostają nietknięte.
LEGIT_SECOND_SURNAMES = [
    "Anna (Kowalska)",
    "Maria (Nowak)",
    "Ewa (Wiśniewska)",
    "Katarzyna (Wójcik)",
    "Joanna (Kowalczyk-Lis)",
    "Agnieszka (Kamińska)",
    "Barbara (Lewandowska)",
    "Magdalena (Zielińska)",
    "Monika (Szymańska)",
    "Aleksandra (Woźniak)",
    "Natalia (Dąbrowska)",
    "Karolina (Kozłowska)",
    "Paulina (Jankowska)",
    "Małgorzata (Mazur)",
    "Justyna (Kwiatkowska)",
    "Dorota (Krawczyk)",
    "Izabela (Piotrowska-Grabowska)",
    "Beata (Ślęzak)",
    "Zofia (Żak)",
    "Kowalska (Nowak)",
    "Łucja (Ćwik)",
]


@pytest.mark.parametrize("raw,expected", PRODUCTION_MARKERS)
def test_production_markers_are_caught_and_stripped(raw: str, expected: str):
    assert find_name_markers(raw), raw
    assert strip_name_markers(raw)[0] == expected


def test_production_lists_have_the_measured_sizes():
    assert len(PRODUCTION_MARKERS) == 9
    assert len(LEGIT_SECOND_SURNAMES) == 21


@pytest.mark.parametrize("value", LEGIT_SECOND_SURNAMES)
def test_second_surname_in_brackets_is_not_a_marker(value: str):
    assert find_name_markers(value) == []
    assert strip_name_markers(value) == (value, [])


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Jan (Active)", "Jan"),
        ("Jan (Zatrudniony)", "Jan"),
        ("Jan (Blacklist)", "Jan"),
        ("Jan (Black-List)", "Jan"),
        ("Jan (Akcept)", "Jan"),
        ("Jan (Aktywny)", "Jan"),
        ("Jan (Eks-Pracownik)", "Jan"),
        ("Jan (Były pracownik)", "Jan"),
        ("Jan (byly pracownik)", "Jan"),
        ("[Czarna Lista] Jan", "Jan"),
        ("(zaakceptowany przez klienta) Jan", "Jan"),
    ],
)
def test_status_word_is_a_marker_even_when_capitalised(raw: str, expected: str):
    assert strip_name_markers(raw)[0] == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ACTIVE Jan", "Jan"),
        ("Jan passive", "Jan"),
        ("AKTYWNY Łukasz", "Łukasz"),
        ("/ ACTIVE] Bartłomiej", "Bartłomiej"),
        ("[active / Bartosz", "Bartosz"),
        ("Kowalski - zatrudniony", "Kowalski"),
    ],
)
def test_bare_and_unbalanced_markers_from_traffit(raw: str, expected: str):
    assert strip_name_markers(raw)[0] == expected


@pytest.mark.parametrize(
    "value",
    ["Active", "Activision", "Inactivewicz", "Jan ACTIVE Kowalski", "Łukasz", "Żaneta"],
)
def test_plain_names_stay_untouched(value: str):
    assert strip_name_markers(value) == (value, [])


def test_no_marker_keeps_the_value_byte_for_byte():
    """Bez dopisku nic się nie normalizuje — korekta nie dotyka takich wierszy."""
    assert strip_name_markers("Jan  Kowalski ") == ("Jan  Kowalski ", [])


def test_marker_only_field_becomes_empty_and_automated_paths_keep_it():
    assert strip_name_markers("[ACTIVE]") == ("", ["[ACTIVE]"])
    assert without_name_markers("[ACTIVE]") == "[ACTIVE]"
    assert without_name_markers("[ACTIVE] Jan") == "Jan"
    assert without_name_markers(None) is None


def test_blacklist_detection_knows_czarna_lista_but_needs_a_delimiter():
    assert has_blacklist_marker("Anna (czarna lista)") is True
    assert has_blacklist_marker("[Czarna Lista] Jan") is True
    assert has_blacklist_marker("Blacklista") is False
    assert has_blacklist_marker("Anna (zaakceptowany)") is False


def test_active_detection_skips_inactive_forms():
    assert has_active_marker(["[ACTIVE]"]) is True
    assert has_active_marker(["(aktywny)"]) is True
    assert has_active_marker(["[INACTIVE]", "(nieaktywny)"]) is False


def test_user_message_and_error_type():
    message = name_marker_message()
    assert message.startswith("Imię i nazwisko bez dopisków w nawiasie.")
    # Nazwy pól z okien „Dodaj kandydata” / „Edytuj dane” (audyt 13.10.2026);
    # czarna lista od 17.10.2026 w menu profilu.
    assert "Dyspozycyjność" in message and "„Czarna lista…”" in message
    assert NAME_MARKER_ERROR_TYPE == "candidate_name_marker"


# ── Mapper Traffita = ta sama reguła co korekta 0436 ────────────────────────


def _row(**kw) -> NameMarkerRow:
    return NameMarkerRow(id=1, **{"name": "Jan", "lastname": "Testowy", **kw})


@pytest.mark.parametrize("raw,expected", PRODUCTION_MARKERS)
def test_traffit_payload_maps_to_the_same_name_as_the_repair(raw, expected):
    """Import nie może przywrócić tego, co zdjęła migracja — i odwrotnie."""
    for field in ("name", "lastname"):
        payload = {"id": 7, "name": "Jan", "lastname": "Testowy", "status": "active"}
        payload[field] = raw
        mapped = traffit_employee_to_candidate(payload)
        fix = plan_fix(_row(**{field: raw}))
        assert fix is not None
        assert mapped[field] == getattr(fix, field) == expected
        assert (mapped["status"] == "blacklisted") == (fix.status == "blacklisted")
        assert mapped["cv_extracted_data"]["traffit_name_marker"] == fix.provenance


# ── Plan korekty: najpierw pole, potem tekst ────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [raw for raw, _ in PRODUCTION_MARKERS]
    + [
        "ACTIVE Jan",
        "Jan passive",
        "Kowalski zatrudniony",
        "/ ACTIVE] Jan",
        "Jan (Były pracownik)",
    ],
)
def test_sql_prefilter_is_a_superset_of_the_rule(raw: str):
    """Wiersz, którego filtr SQL nie wybierze, nigdy nie zostanie poprawiony."""
    import re

    from app.services.candidate_name_marker_repair import PREFILTER_PATTERN

    assert find_name_markers(raw)
    assert re.search(PREFILTER_PATTERN, raw, re.IGNORECASE)


def test_plan_ignores_rows_without_markers():
    assert plan_fix(_row(name="Anna (Kowalska)")) is None


def test_plan_blacklists_unless_a_human_set_the_status():
    fix = plan_fix(_row(lastname="Nowak (czarna lista)"))
    assert fix.lastname == "Nowak"
    assert fix.status == "blacklisted"

    kept = plan_fix(_row(lastname="Nowak (czarna lista)", status_manual=True))
    assert kept.status == "active"
    assert kept.blacklist_kept_manual_status is True


def test_plan_sets_actively_looking_only_from_unknown():
    assert plan_fix(_row(name="[ACTIVE] Jan")).availability_status == (
        "actively_looking"
    )
    kept = plan_fix(_row(name="[ACTIVE] Jan", availability_status="open_to_offers"))
    assert kept.availability_status == "open_to_offers"
    other = plan_fix(_row(name="Jan (zaakceptowany)"))
    assert (other.status, other.availability_status) == ("active", "unknown")


def test_plan_restores_traffit_value_and_clears_the_manual_lock():
    fix = plan_fix(
        _row(name="[ACTIVE] Zbyszek", name_manual=True, traffit_name="Zbigniew")
    )
    assert fix.name == "Zbigniew"
    assert fix.cleared_locks == ("name",)


def test_plan_keeps_the_lock_when_traffit_value_is_missing_or_marked():
    for source in (None, "", "[ACTIVE] Zbigniew"):
        fix = plan_fix(
            _row(name="[ACTIVE] Zbigniew", name_manual=True, traffit_name=source)
        )
        assert fix.name == "Zbigniew"
        assert fix.cleared_locks == ()
    unlocked = plan_fix(_row(name="[ACTIVE] Zbigniew", traffit_name="Inny"))
    assert (unlocked.name, unlocked.cleared_locks) == ("Zbigniew", ())


def test_plan_writes_provenance_only_into_an_object_and_without_repeats():
    fix = plan_fix(_row(name="[ACTIVE] Jan", name_marker="[ACTIVE]"))
    assert fix.provenance == "[ACTIVE]"
    appended = plan_fix(_row(lastname="Nowak (zaakceptowany)", name_marker="[akcept]"))
    assert appended.provenance == "[akcept] (zaakceptowany)"
    assert plan_fix(_row(name="[ACTIVE] Jan", cv_is_object=False)).provenance is None


def test_plan_uses_placeholder_for_a_field_that_was_only_a_marker():
    fix = plan_fix(_row(name="[BLACKLIST]"))
    assert fix.name == EMPTY_NAME_PLACEHOLDER
    assert fix.placeholder_fields == ("name",)


def test_receipt_has_ids_and_counts_but_no_names():
    from scripts.show_migration_receipts import is_receipt_key

    rows = [
        _row(name="[ACTIVE] Zbigniew"),
        NameMarkerRow(id=2, name="Anna", lastname="Nowak (czarna lista)"),
    ]
    fixes = [plan_fix(row) for row in rows]
    receipt = build_receipt(rows, fixes)
    assert receipt["changed_candidate_ids"] == [1, 2]
    assert receipt["blacklisted_candidate_ids"] == [2]
    assert receipt["actively_looking_candidate_ids"] == [1]
    assert receipt["reindex_recorded"] is False
    dumped = json.dumps(receipt, ensure_ascii=False)
    for text_value in ("Zbigniew", "Nowak", "czarna", "ACTIVE"):
        assert text_value not in dumped
    assert is_receipt_key(REPAIR_MARKER)
    assert not is_receipt_key(DETAILS_KEY)
    assert summarize_for_log(None) == "already applied"
    assert "changed=2" in summarize_for_log(receipt)


# ── Migracja i faza startu wołają ten sam runner ────────────────────────────


def test_migration_0436_runs_the_shared_repair():
    source = (BACKEND / "alembic/versions/0436_candidate_name_markers.py").read_text(
        encoding="utf-8"
    )
    assert 'revision = "0436_candidate_name_markers"' in source
    assert 'down_revision = "0435_candidate_document_removed"' in source
    assert "apply_name_marker_repair(op.get_bind())" in source


def test_entrypoint_runs_the_repair_and_logs_only_the_summary():
    source = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert 'startup_phase "repair-candidate-name-markers"' in source
    block = source.split("run_candidate_name_marker_repair", 1)[1].split("\nPY\n", 1)[0]
    assert "summarize_for_log(summary)" in block
    assert "await db.commit()" in block
    assert "await db.rollback()" in block
    assert source.index('startup_phase "repair-candidate-name-markers"') < (
        source.index("exec uvicorn app.main:app")
    )
