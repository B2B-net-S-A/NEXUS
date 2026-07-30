from __future__ import annotations

import csv
import io
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import app.models  # noqa: F401
import pytest

from app.api.import_export import _build_candidates_csv, _parse_profile_rate
from app.models.candidate import Candidate, CandidateStatus
from scripts import report_candidate_profile_rate_conflicts as conflict_report


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity", "1.234"])
def test_profile_rate_parser_rejects_non_finite_and_overprecision(raw: str):
    with pytest.raises(ValueError, match="invalid_profile_rate"):
        _parse_profile_rate(raw)


def test_csv_export_suppresses_explicit_foreign_candidate_profile_rate():
    candidate = Candidate(
        id=7,
        name="Anna",
        lastname="Nowak",
        status=CandidateStatus.active,
        expected_rate_hourly=Decimal("120.50"),
        expected_rate_currency="EUR",
    )

    payload = _build_candidates_csv([candidate]).decode("utf-8-sig")
    row = next(csv.DictReader(io.StringIO(payload)))

    assert row["expected_rate_hourly"] == ""


def test_csv_export_keeps_zero_pln_rate():
    candidate = Candidate(
        id=8,
        name="Jan",
        lastname="Nowak",
        status=CandidateStatus.active,
        expected_rate_hourly=Decimal("0.00"),
        expected_rate_currency="PLN",
    )

    payload = _build_candidates_csv([candidate]).decode("utf-8-sig")
    row = next(csv.DictReader(io.StringIO(payload)))

    assert row["expected_rate_hourly"] == "0.00"


def test_foreign_rate_conflict_report_cannot_write_anywhere_in_repository():
    repo_local = conflict_report._REPO_ROOT / "docs" / "candidate-rate-conflicts.bin"

    with pytest.raises(
        conflict_report.ConflictReportSafetyError,
        match="outside the repository",
    ):
        conflict_report._validated_output_path(str(repo_local))


def test_foreign_rate_conflict_report_help_bootstraps_without_pythonpath():
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "report_candidate_profile_rate_conflicts.py"
    )
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=script.parents[2],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
