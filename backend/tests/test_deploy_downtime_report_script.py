"""Raport przerwy przy deployu podaje frontend i API OSOBNO oraz restart Postgresa.

Do 15.09.2026 raport był wklejony w ``deploy.yml`` i w logu zostawiał tylko
maksimum z obu celów (63–93 s), więc nie dało się ustalić, czy przerwę robi
frontend, API, czy restart bazy. Skrypt ``.github/scripts/deploy_downtime_report.py``
ładowany po ścieżce (wzorzec ``test_deploy_version_summary_script.py``);
bez sieci, zawsze kod wyjścia 0.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "deploy_downtime_report",
    Path(__file__).parents[2] / ".github/scripts/deploy_downtime_report.py",
)
report = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = report
_SPEC.loader.exec_module(report)


def _write(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "samples.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_outages_measure_from_first_bad_to_first_good_sample() -> None:
    samples = [(0, "200"), (2, "503"), (4, "503"), (6, "200"), (8, "502"), (10, "200")]
    assert report.outages(samples) == [(2, 6), (8, 10)]


def test_outage_still_open_at_end_ends_on_last_sample() -> None:
    assert report.outages([(0, "200"), (2, "000"), (4, "000")]) == [(2, 4)]


def test_frontend_and_api_are_reported_separately(tmp_path: Path) -> None:
    samples = _write(
        tmp_path,
        [
            "100,frontend,200",
            "100,api,200",
            "102,frontend,200",
            "102,api,502",
            "104,frontend,503",
            "104,api,503",
            "106,frontend,200",
            "106,api,503",
            "130,frontend,200",
            "130,api,200",
        ],
    )
    summary = tmp_path / "summary.md"
    notices = tmp_path / "notices.txt"
    code = report.main(
        [
            "--samples", str(samples),
            "--target", "a" * 40,
            "--postgres-before", "2026-09-15T01:00:00+00:00",
            "--postgres-after", "2026-09-15T01:00:00+00:00",
            "--summary-out", str(summary),
            "--notice-out", str(notices),
        ]
    )
    assert code == 0
    lines = notices.read_text(encoding="utf-8").splitlines()
    # Dawny tekst zostaje: po nim da się porównać deploye sprzed zmiany.
    assert lines[0].startswith(
        "::notice::Najdłuższa przerwa widziana przez użytkowników w tym deployu: 28 s"
    )
    assert any(l.startswith("::notice title=Przerwa frontend::frontend: 2 s") for l in lines)
    assert any(l.startswith("::notice title=Przerwa api::api: 28 s") for l in lines)
    assert any("502, 503" in l for l in lines if "title=Przerwa api" in l)
    assert "Postgres restartował: nie" in lines[-1]
    assert "| api | 5 | 3 | 28 s |" in summary.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ("2026-09-15T01:00:00+00:00", "2026-09-15T01:00:00+00:00", "same"),
        ("2026-09-15T01:00:00+00:00", "2026-09-15T08:25:00+00:00", "restarted"),
        ("", "2026-09-15T08:25:00+00:00", "unknown"),  # prod bez pola przed wdrożeniem
        ("2026-09-15T01:00:00+00:00", "", "unknown"),
        ("null", "null", "unknown"),
    ],
)
def test_postgres_restart_verdict(before: str, after: str, expected: str) -> None:
    assert report.postgres_restart(before, after) == expected


def test_truncated_and_garbage_lines_are_skipped(tmp_path: Path) -> None:
    samples = _write(tmp_path, ["100,frontend,200", "10", "abc,api,200", "102,api,200"])
    rows = report.load_samples(samples)
    assert rows["frontend"] == [(100, "200")]
    assert rows["api"] == [(102, "200")]


def test_every_notice_is_single_line(tmp_path: Path) -> None:
    results = [report.summarize("frontend", []), report.summarize("api", [(1, "503")])]
    for line in report.render_notices(results, "unknown"):
        assert "\n" not in line and line.startswith("::notice")
