"""QA-01: bramka „pokrycie bez spadku" (``.github/scripts/coverage_gate.py``).

Skrypt ładowany po ścieżce (wzorzec ``test_deploy_version_summary_script.py``).
Sprawdza granice progu, ratchet, format pliku baseline w repo i to, że spadek
kończy się kodem 1 z adnotacją ``::error::`` — bez tego bramka byłaby
kolejnym raportem, który nic nie blokuje.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "coverage_gate", _REPO / ".github/scripts/coverage_gate.py"
)
gate = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = gate
_SPEC.loader.exec_module(gate)


@pytest.mark.parametrize(
    ("actual", "passed", "hint"),
    [
        (73.00, True, False),  # równo baseline
        (72.50, True, False),  # dokładnie na minimum (baseline − tolerancja)
        (72.49, False, False),  # o 0,01 pp za nisko
        (73.50, True, False),  # wzrost w granicach tolerancji — bez podpowiedzi
        (73.51, True, True),  # wyraźny wzrost → prośba o podbicie baseline'u
    ],
)
def test_evaluate_boundaries(actual: float, passed: bool, hint: bool) -> None:
    result = gate.evaluate(actual, baseline=73.0, tolerance=0.5)
    assert result.passed is passed
    assert result.ratchet_hint is hint


def test_negative_tolerance_is_rejected() -> None:
    with pytest.raises(ValueError):
        gate.evaluate(70.0, baseline=70.0, tolerance=-1)


def test_main_fails_with_error_annotation_and_writes_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"backend": 60.0, "tolerance_pp": 0.5}))
    summary = tmp_path / "summary.md"

    code = gate.main(
        ["--baseline", str(baseline), "--key", "backend", "--actual", "59.2",
         "--summary", str(summary)]
    )

    assert code == 1
    assert "::error::" in capsys.readouterr().out
    assert "SPADEK" in summary.read_text(encoding="utf-8")


def test_main_passes_and_hints_ratchet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"backend": 60.0, "tolerance_pp": 0.5}))

    code = gate.main(["--baseline", str(baseline), "--key", "backend", "--actual", "62"])

    assert code == 0
    assert "::notice::" in capsys.readouterr().out


def test_missing_key_is_an_error(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"tolerance_pp": 0.5}))
    with pytest.raises(KeyError):
        gate.main(["--baseline", str(baseline), "--key", "backend", "--actual", "1"])


def test_repo_baseline_file_is_well_formed() -> None:
    data = json.loads((_REPO / ".github/coverage-baseline.json").read_text(encoding="utf-8"))
    value = data["backend_line_branch_percent"]
    assert isinstance(value, (int, float)) and 0 < value <= 100
    assert 0 <= data["tolerance_pp"] <= 2, "szeroka tolerancja zamienia bramkę w raport"
