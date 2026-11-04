"""Ścieżki automatyczne zdejmują dopisek z imienia (D6, 13.10.2026) — bez bazy.

Reguła siedzi w `candidate_name_rules`; tu pilnujemy, że każda ścieżka, która
zakłada albo nadpisuje kandydata z danych z zewnątrz, naprawdę ją woła.
Usunięcie wywołania z którejkolwiek z nich zapala ten plik, a nie produkcję,
gdzie objawem jest „[ACTIVE] Jan” wracający po imporcie. Imiona są wymyślone
(repo jest publiczne).
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api.candidates import _cv_preview_response, _derive_names_from_preview
from app.models.candidate import Candidate
from app.services.candidate_name_rules import (
    MAX_SCANNED_NAME_LENGTH,
    has_blacklist_marker,
    strip_name_markers,
    without_name_markers,
)
from app.services.cv_enrichment import _apply_cv_contact_fields
from app.services.talent_radar_importer import TalentRadarImporter

BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "value",
    [
        "a" + " " * 20_000 + "b",
        "a" + "-" * 20_000 + "b",
        "(" + " " * 20_000 + "active",
        "a" + " /" * 10_000 + "b",
    ],
)
def test_long_value_is_not_scanned_and_returns_fast(value: str) -> None:
    """Przegląd 13.10.2026: 20 000 spacji blokowało pętlę zdarzeń ok. 30 s.

    Import zbiorczy i CSV wołają regułę przed walidacją długości, więc limit
    jest w samej regule. Wartość dłuższa od limitu wraca bez zmian i odpada
    dalej na limicie pola (100 znaków).
    """
    started = time.perf_counter()
    assert strip_name_markers(value) == (value, [])
    assert without_name_markers(value) == value
    assert has_blacklist_marker(value) is False
    assert time.perf_counter() - started < 0.5


def test_value_at_the_limit_is_still_scanned() -> None:
    value = "[ACTIVE] " + "J" + "a" * (MAX_SCANNED_NAME_LENGTH - 10)
    assert len(value) == MAX_SCANNED_NAME_LENGTH
    assert strip_name_markers(value)[1] == ["[ACTIVE]"]


def test_linkedin_preview_name_loses_marker() -> None:
    preview = SimpleNamespace(name="[ACTIVE] Jan", lastname="Testowy (zaakceptowany)")
    assert _derive_names_from_preview(
        preview, "https://www.linkedin.com/in/przyklad"
    ) == ("Jan", "Testowy")


def test_cv_preview_does_not_prefill_marker() -> None:
    preview = _cv_preview_response(
        "0" * 64, {"first_name": "(czarna lista) Jan", "last_name": "Testowy"}
    )
    assert (preview.name, preview.lastname) == ("Jan", "Testowy")


def test_cv_backfill_writes_name_without_marker() -> None:
    candidate = Candidate(name="?", lastname="")
    _apply_cv_contact_fields(
        candidate, {"first_name": "[ACTIVE] Jan", "last_name": "Testowy (CIPP/E)"}, {}
    )
    assert (candidate.name, candidate.lastname) == ("Jan", "Testowy")


def test_talent_radar_reimport_does_not_restore_marker() -> None:
    importer = TalentRadarImporter.__new__(TalentRadarImporter)
    row = {
        "id": 1,
        "traffit_id": 2,
        "email": None,
        "name": "[ACTIVE] Jan",
        "lastname": "Testowy",
        "raw_cv_text": None,
        "cv_content": None,
        "cv_filename": None,
        "extracted_data": None,
        "skills": None,
        "experience_years": None,
        "seniority": None,
        "languages": None,
        "location": None,
        "availability": None,
        "cv_language": None,
        "cv_date": None,
    }
    payload = importer._to_payload(row)
    assert (payload["name"], payload["lastname"]) == ("Jan", "Testowy")


# Ścieżki, które zakładają kandydata w środku dłuższej transakcji z bazą —
# tu wystarcza dowód, że moduł woła regułę przy imieniu.
DB_BOUND_PATHS = [
    "app/services/public_apply.py",
    "app/api/application_submissions.py",
    "app/api/import_export.py",
    "app/services/order_mail_apply.py",
    "app/services/m365/attachment_handler.py",
    "app/services/candidate_merge.py",
]


@pytest.mark.parametrize("path", DB_BOUND_PATHS)
def test_db_bound_path_calls_the_name_rule(path: str) -> None:
    source = (BACKEND / path).read_text(encoding="utf-8")
    assert "without_name_markers(" in source or "strip_name_markers(" in source, (
        f"{path} zakłada kandydata z danych z zewnątrz — imię musi przejść przez "
        "candidate_name_rules (D6)"
    )
