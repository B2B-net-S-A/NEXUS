"""Dwa PR-y ruszające RÓŻNE ekrany (albo różne pliki zamówień) nie zderzają się.

23–24.09.2026 kolejka merge'ów wyrzuciła 40 PR-ów, z tego 34 na teście
przewodników ekranów i 20 na teście instrukcji zamówień. Przyczyna nie była
w zapominaniu o stemplu, tylko w jego kształcie: jeden wspólny plik stempla na
cały mechanizm (plus wspólna data w treści instrukcji), więc KAŻDE dwa PR-y
ruszające dowolne ekrany przepisywały ten sam plik.

Test odtwarza to na prawdziwym gicie w katalogu tymczasowym: dwie gałęzie
z rozłącznymi zmianami, każda przestemplowana skryptem (różnego dnia), obie
łączone w obu kolejnościach. Warunek: zero konfliktów i zero rozjazdu
stempla po drugim merge'u — bez ponownego stemplowania.

Czysta biblioteka standardowa + git: bez aplikacji i bez bazy.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from app.data import review_stamps as rs
from app.data.procedures import ORDERS_LOGIC_SOURCES

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="brak gita w środowisku"
)

_GUIDES = [
    {"key": "alpha.list", "title": "Alfa", "sources": ["frontend/alpha.tsx"]},
    {"key": "beta.board", "title": "Beta", "sources": ["frontend/beta.tsx"]},
    {"key": "gamma.view", "title": "Gamma", "sources": ["frontend/alpha.tsx"]},
]
_ORDER_SOURCES = ("backend/orders_x.py", "backend/orders_y.py")
_PROCEDURE_TEXT = (
    "> **Zgodność z systemem sprawdzona:** 01.09.2026\n\nTreść instrukcji.\n"
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _stamp_everything(repo: Path, day: date) -> None:
    rs.stamp_guides(repo)
    rs.stamp_orders(repo, sources=_ORDER_SOURCES, today=day)


def _changed_files(repo: Path, branch: str) -> set:
    out = _git(repo, "diff", "--name-only", f"main...{branch}").stdout
    return set(out.split())


def _stamp_files(paths: set) -> set:
    return {
        p
        for p in paths
        if p.startswith((rs.GUIDE_STAMPS_REL + "/", rs.ORDERS_STAMPS_REL + "/"))
    }


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    assert _git(tmp_path, "init", "-q", "-b", "main").returncode == 0
    _write(tmp_path, rs.GUIDES_REL, json.dumps(_GUIDES, indent=2))
    for rel in ("frontend/alpha.tsx", "frontend/beta.tsx", *_ORDER_SOURCES):
        _write(tmp_path, rel, f"// {rel}\n")
    _write(tmp_path, rs.PROCEDURE_REL, _PROCEDURE_TEXT)
    _stamp_everything(tmp_path, date(2026, 9, 1))
    _git(tmp_path, "add", "-A")
    assert _git(tmp_path, "commit", "-qm", "start").returncode == 0
    return tmp_path


def _open_pr(repo: Path, branch: str, edits: dict, day: date) -> None:
    _git(repo, "checkout", "-q", "-b", branch, "main")
    for rel, text in edits.items():
        _write(repo, rel, text)
    _stamp_everything(repo, day)
    _git(repo, "add", "-A")
    assert _git(repo, "commit", "-qm", branch).returncode == 0
    _git(repo, "checkout", "-q", "main")


def _merge_in_order(repo: Path, first: str, second: str) -> None:
    target = f"queue-{first}-{second}"
    _git(repo, "checkout", "-q", "-b", target, "main")
    for branch in (first, second):
        result = _git(repo, "merge", "--no-edit", "-q", branch)
        assert result.returncode == 0, (
            f"Konflikt przy łączeniu {branch} po {first}:\n"
            f"{result.stdout}\n{result.stderr}"
        )
    assert rs.guide_drift(repo) == {}
    assert rs.orders_drift(repo, sources=_ORDER_SOURCES) == []
    _git(repo, "checkout", "-q", "main")


def test_disjoint_screen_and_order_prs_merge_cleanly_in_either_order(
    repo: Path,
) -> None:
    # PR A: ekran „beta” + plik zamówień X, stemplowany 23.09.
    _open_pr(
        repo,
        "pr-a",
        {"frontend/beta.tsx": "// beta v2\n", "backend/orders_x.py": "# x v2\n"},
        date(2026, 9, 23),
    )
    # PR B: ekran „alpha” (dwa przewodniki) + plik zamówień Y, dzień później.
    _open_pr(
        repo,
        "pr-b",
        {"frontend/alpha.tsx": "// alpha v2\n", "backend/orders_y.py": "# y v2\n"},
        date(2026, 9, 24),
    )

    stamps_a = _stamp_files(_changed_files(repo, "pr-a"))
    stamps_b = _stamp_files(_changed_files(repo, "pr-b"))
    assert stamps_a and stamps_b
    assert stamps_a.isdisjoint(stamps_b), stamps_a & stamps_b
    # Żaden PR nie dotknął wspólnego pliku: guides.json ani instrukcji.
    for branch in ("pr-a", "pr-b"):
        changed = _changed_files(repo, branch)
        assert rs.GUIDES_REL not in changed
        assert rs.PROCEDURE_REL not in changed

    _merge_in_order(repo, "pr-a", "pr-b")
    _merge_in_order(repo, "pr-b", "pr-a")


def test_same_screen_in_two_prs_touches_the_same_stamp(repo: Path) -> None:
    """Ten sam ekran w dwóch PR-ach MA się zderzyć — drugi autor przegląda
    przewodnik po zmianie pierwszego."""
    _open_pr(repo, "pr-c", {"frontend/beta.tsx": "// c\n"}, date(2026, 9, 23))
    _open_pr(repo, "pr-d", {"frontend/beta.tsx": "// d\n"}, date(2026, 9, 23))
    shared = _stamp_files(_changed_files(repo, "pr-c")) & _stamp_files(
        _changed_files(repo, "pr-d")
    )
    assert shared == {f"{rs.GUIDE_STAMPS_REL}/beta.board.json"}


def test_source_change_without_restamp_is_caught(repo: Path) -> None:
    _write(repo, "frontend/alpha.tsx", "// zmiana bez przeglądu\n")
    _write(repo, "backend/orders_y.py", "# zmiana bez przeglądu\n")
    drift = rs.guide_drift(repo)
    assert set(drift) == {"alpha.list", "gamma.view"}
    assert drift["alpha.list"] == ["frontend/alpha.tsx"]
    assert rs.orders_drift(repo, sources=_ORDER_SOURCES) == ["backend/orders_y.py"]


def test_procedure_date_moves_only_when_its_text_changes(repo: Path) -> None:
    _write(repo, "backend/orders_x.py", "# x v3\n")
    changed, bumped = rs.stamp_orders(
        repo, sources=_ORDER_SOURCES, today=date(2026, 9, 30)
    )
    assert changed == ["backend/orders_x.py"] and bumped is False
    assert "01.09.2026" in (repo / rs.PROCEDURE_REL).read_text(encoding="utf-8")

    _write(repo, rs.PROCEDURE_REL, _PROCEDURE_TEXT + "Nowy akapit.\n")
    changed, bumped = rs.stamp_orders(
        repo, sources=_ORDER_SOURCES, today=date(2026, 9, 30)
    )
    assert changed == [rs.PROCEDURE_REL] and bumped is True
    text = (repo / rs.PROCEDURE_REL).read_text(encoding="utf-8")
    assert "sprawdzona:** 30.09.2026" in text
    assert rs.orders_drift(repo, sources=_ORDER_SOURCES) == []


def test_real_layout_gives_every_unit_its_own_stamp_file() -> None:
    """Na prawdziwych danych: każdy ekran i każdy plik zamówień ma WŁASNY plik
    stempla (brak kolizji nazw po zamianie ``/`` na ``__``)."""
    guide_paths = {rs.guide_stamp_path(key) for key in rs.load_raw_guides()}
    assert len(guide_paths) == len(rs.load_raw_guides())
    watched = rs.orders_watched(ORDERS_LOGIC_SOURCES)
    order_paths = {rs.orders_stamp_path(rel) for rel in watched}
    assert len(order_paths) == len(set(watched))
