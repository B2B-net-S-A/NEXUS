"""DEP-01 (audyt 14.09.2026): podsumowanie deployu mówi, CO naprawdę stoi na
produkcji względem przypiętego wydania.

Skrypt ``.github/scripts/deploy_version_summary.py`` renderuje tabelę do
``$GITHUB_STEP_SUMMARY`` i linię ``::notice::``. Od przypięcia commitu w
Coolify (15.09.2026) jedynym sukcesem jest równość z RELEASE_SHA — potomek na
produkcji to rozjazd, nie koalescencja. Skrypt ładowany po ścieżce; bez sieci,
bez sekretów, zawsze kod wyjścia 0.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "deploy_version_summary",
    Path(__file__).parents[2] / ".github/scripts/deploy_version_summary.py",
)
summary = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = summary
_SPEC.loader.exec_module(summary)

TARGET = "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
RELEASE = "2222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
OTHER = "3333333ccccccccccccccccccccccccccccccccc"


@pytest.mark.parametrize(
    ("live", "kind"),
    [
        (RELEASE, "match"),
        (RELEASE[:7], "match"),
        (TARGET, "mismatch"),  # starszy commit niż przypięte wydanie
        (OTHER, "mismatch"),  # inny commit niż przyjęta wersja
        ("", "missing"),
        ("unknown", "missing"),
        ("abc", "missing"),
    ],
)
def test_classify(live: str, kind: str) -> None:
    assert summary.classify(RELEASE, live).kind == kind


def test_summary_names_release_newer_than_target_and_accepted_descendant() -> None:
    rows = {"backend (/api/health)": summary.classify(OTHER, OTHER)}
    text = summary.render_summary(
        TARGET, RELEASE, rows, rebuild_skipped=False, accepted=OTHER
    )
    assert "`2222222`" in text and "`1111111`" in text
    assert "HEAD maina z zieloną bramką" in text
    assert "`3333333`" in text and "potomka wydania" in text
    assert "ROZJAZD" not in text
    assert "wykonany" in text


def test_mismatch_is_flagged() -> None:
    rows = {"backend (/api/health)": summary.classify(RELEASE, OTHER)}
    text = summary.render_summary(RELEASE, RELEASE, rows, rebuild_skipped=True)
    assert "ROZJAZD" in text
    assert "pominięty" in text
    assert "HEAD maina" not in text


def test_notice_is_a_single_workflow_command_line() -> None:
    rows = {
        "backend (/api/health)": summary.classify(RELEASE, RELEASE),
        "frontend (version.json)": summary.classify(RELEASE, ""),
    }
    notice = summary.render_notice(RELEASE, rows, rebuild_skipped=True)
    assert notice.startswith("::notice title=Wersje po deployu::")
    assert "\n" not in notice
    assert "backend=2222222" in notice
    assert "frontend=—" in notice


def test_cli_writes_both_files_and_exits_zero(tmp_path: Path) -> None:
    summary_out = tmp_path / "summary.md"
    notice_out = tmp_path / "notice.txt"
    code = summary.main(
        [
            "--target",
            TARGET,
            "--release",
            RELEASE,
            "--backend-live",
            RELEASE,
            "--frontend-live",
            RELEASE,
            "--rebuild-skipped",
            "false",
            "--summary-out",
            str(summary_out),
            "--notice-out",
            str(notice_out),
        ]
    )
    assert code == 0
    md = summary_out.read_text(encoding="utf-8")
    assert "| backend (/api/health) |" in md and "| frontend (version.json) |" in md
    assert notice_out.read_text(encoding="utf-8").count("\n") == 1


def test_cli_without_release_falls_back_to_target(tmp_path: Path) -> None:
    summary_out = tmp_path / "summary.md"
    notice_out = tmp_path / "notice.txt"
    assert (
        summary.main(
            [
                "--target",
                TARGET,
                "--backend-live",
                "",
                "--summary-out",
                str(summary_out),
                "--notice-out",
                str(notice_out),
            ]
        )
        == 0
    )
    md = summary_out.read_text(encoding="utf-8")
    assert "frontend (version.json)" not in md
    assert "brak odczytu wersji" in md
    assert "`1111111`" in md
