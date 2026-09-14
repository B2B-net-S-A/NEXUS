"""DEP-01 (audyt Codexa, 14.09.2026): podsumowanie deployu mówi, CO naprawdę
stoi na produkcji.

Skrypt ``.github/scripts/deploy_version_summary.py`` renderuje tabelę do
``$GITHUB_STEP_SUMMARY`` i linię ``::notice::`` z TARGET_SHA obok SHA
serwowanego po deployu. Koalescencja burstów (produkcja serwuje POTOMKA
targetu) ma być nazwana wprost, a prawdziwy rozjazd — odróżniony od niej.
Skrypt ładowany po ścieżce (wzorzec ``test_sentry_daily_digest_script.py``);
bez sieci, bez sekretów, zawsze kod wyjścia 0.
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
# `@dataclass` pod `from __future__ import annotations` rozwiązuje typy przez
# `sys.modules[cls.__module__]` — moduł ładowany po ścieżce musi tam być
# ZANIM wykona się jego ciało, inaczej AttributeError przy kolekcji testów.
sys.modules[_SPEC.name] = summary
_SPEC.loader.exec_module(summary)

TARGET = "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
CHILD = "2222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


@pytest.mark.parametrize(
    ("live", "relation", "kind"),
    [
        (TARGET, "", "match"),
        (TARGET[:7], "", "match"),  # /api/health bywa skrócone do 7 znaków
        (CHILD, "identical", "match"),
        (CHILD, "ahead", "descendant"),
        (CHILD, "behind", "mismatch"),
        (CHILD, "diverged", "mismatch"),
        (CHILD, "unknown", "mismatch"),
        (CHILD, "", "mismatch"),
        ("", "", "missing"),
        ("missing", "", "missing"),
        ("unknown", "ahead", "missing"),  # build bez GIT_SHA nie jest „potomkiem”
        ("abc", "ahead", "missing"),
    ],
)
def test_classify(live: str, relation: str, kind: str) -> None:
    assert summary.classify(TARGET, live, relation).kind == kind


def test_descendant_is_named_burst_coalescing_not_error() -> None:
    rows = {"backend (/api/health)": summary.classify(TARGET, CHILD, "ahead")}
    text = summary.render_summary(TARGET, rows, rebuild_skipped=True)
    assert "koalescencja burstów" in text
    assert "ROZJAZD" not in text
    assert "`2222222`" in text and "`1111111`" in text
    assert "pominięty" in text


def test_mismatch_is_flagged_and_not_called_coalescing() -> None:
    rows = {"backend (/api/health)": summary.classify(TARGET, CHILD, "behind")}
    text = summary.render_summary(TARGET, rows, rebuild_skipped=False)
    assert "ROZJAZD" in text
    assert "pokrewieństwo=behind" in text
    assert "koalescencja burstów — produkcja serwuje potomka" not in text
    assert "Rebuild w Coolify wykonany" in text


def test_notice_is_a_single_workflow_command_line() -> None:
    rows = {
        "backend (/api/health)": summary.classify(TARGET, CHILD, "ahead"),
        "frontend (version.json)": summary.classify(TARGET, "", ""),
    }
    notice = summary.render_notice(TARGET, rows, rebuild_skipped=True)
    assert notice.startswith("::notice title=Wersje po deployu::")
    assert "\n" not in notice
    assert "backend=2222222" in notice
    assert "frontend=—" in notice
    assert "koalescencja burstów" in notice


def test_cli_writes_both_files_and_exits_zero(tmp_path: Path) -> None:
    summary_out = tmp_path / "summary.md"
    notice_out = tmp_path / "notice.txt"
    code = summary.main(
        [
            "--target",
            TARGET,
            "--backend-live",
            CHILD,
            "--backend-relation",
            "ahead",
            "--frontend-live",
            TARGET,
            "--frontend-relation",
            "identical",
            "--rebuild-skipped",
            "true",
            "--summary-out",
            str(summary_out),
            "--notice-out",
            str(notice_out),
        ]
    )
    assert code == 0
    md = summary_out.read_text(encoding="utf-8")
    assert "| backend (/api/health) |" in md and "| frontend (version.json) |" in md
    assert "koalescencja burstów" in md
    assert notice_out.read_text(encoding="utf-8").count("\n") == 1


def test_cli_without_frontend_reading_renders_backend_only(tmp_path: Path) -> None:
    summary_out = tmp_path / "summary.md"
    notice_out = tmp_path / "notice.txt"
    assert (
        summary.main(
            [
                "--target",
                TARGET,
                "--backend-live",
                "",
                "--backend-relation",
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
