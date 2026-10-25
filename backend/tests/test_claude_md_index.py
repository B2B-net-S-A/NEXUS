"""``CLAUDE.md`` zostaje krótki, a jego indeks zgadza się z ``docs/claude/``.

``CLAUDE.md`` jest wklejany w całości do kontekstu każdej sesji Claude'a.
10.10.2026 miał 926 KB (ok. 530 tys. tokenów z okna 1 mln): każda sesja
startowała w połowie zapełniona, a po zmianie pliku aplikacja wklejała go
drugi raz — siedem sesji z 09.10 skończyło się błędem „Prompt is too long”,
którego kompaktowanie nie naprawiało. Plik urósł, bo każdy PR dopisywał do
niego sekcję (27 KB 01.08 → 926 KB 10.10).

Reguły modułów leżą teraz w ``docs/claude/<obszar>/``. Ten test pilnuje, żeby
nikt nie wrócił do dopisywania ich do ``CLAUDE.md``.
"""

from __future__ import annotations

import json
import subprocess
import sys

from scripts import build_claude_index as index

_FIX = "Uruchom: cd backend && python3 scripts/build_claude_index.py"


def test_claude_md_stays_small() -> None:
    size = index.CLAUDE_MD.stat().st_size
    assert size <= index.MAX_CLAUDE_MD_BYTES, (
        f"CLAUDE.md ma {size} B (limit {index.MAX_CLAUDE_MD_BYTES} B). Ten plik trafia w całości "
        "do kontekstu każdej sesji — nową regułę zapisz w docs/claude/<obszar>/<plik>.md "
        "i odśwież indeks. " + _FIX
    )


def test_area_list_matches_rule_directories() -> None:
    assert index.current() == index.render(), (
        "Lista obszarów w CLAUDE.md nie zgadza się z katalogami docs/claude/ "
        "(nowy katalog, zmieniony opis w GROUPS albo ręczna edycja). " + _FIX
    )


def test_claude_md_does_not_list_rule_files() -> None:
    """25.10.2026: dwa PR-y z regułą w tym samym obszarze dopisywały linię
    w tym samym miejscu listy plików w CLAUDE.md i #2648 miał konflikt z #2653
    w kolejce merge'ów. Pliki wypisuje hook SessionStart, CLAUDE.md ich nie zna."""
    text = index.CLAUDE_MD.read_text(encoding="utf-8")
    listed = [p.name for p in index.RULES_DIR.rglob("*.md") if f"`{p.name}`" in index.current(text)]
    assert not listed, "Pliki reguł w liście obszarów CLAUDE.md: " + ", ".join(listed)


def test_every_rule_file_reaches_the_session_once() -> None:
    files = sorted(index.RULES_DIR.rglob("*.md"))
    assert files, "docs/claude/ jest puste — reguły modułów zniknęły."
    printed = [index.render_files(part) for part in range(1, index.HOOK_PARTS + 1)]
    stems = [
        stem
        for text in printed
        for line in text.splitlines()[1:]
        for stem in line.split("/: ", 1)[1].split(", ")
    ]
    assert sorted(stems) == sorted(p.stem for p in files)
    untitled = [
        str(p.relative_to(index.REPO_ROOT)) for p in files if not p.read_text(encoding="utf-8").startswith("# ")
    ]
    assert not untitled, "Pierwsza linia pliku reguły ma być tytułem „# …”: " + ", ".join(untitled)


def test_each_hook_part_fits_the_session_start_limit() -> None:
    """Claude Code obcina wyjście hooka ponad 10 000 znaków do ścieżki pliku
    i 2 000 znaków podglądu, a sesji nie każe go czytać."""
    for part in range(1, index.HOOK_PARTS + 1):
        size = len(index.render_files(part))
        assert size <= index.HOOK_MAX_CHARS, (
            f"Część {part}/{index.HOOK_PARTS} wypisu reguł ma {size} znaków (limit "
            f"{index.HOOK_MAX_CHARS}). Podnieś HOOK_PARTS w build_claude_index.py "
            "i dopisz hook z --part w .claude/settings.json."
        )


def test_settings_run_one_hook_per_part() -> None:
    settings = json.loads((index.REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [hook["command"] for entry in settings["hooks"]["SessionStart"] for hook in entry["hooks"]]
    assert commands == [
        f'python3 "$CLAUDE_PROJECT_DIR/backend/scripts/build_claude_index.py" --print --part {part}'
        for part in range(1, index.HOOK_PARTS + 1)
    ]


def test_hook_runs_on_the_system_python_without_dependencies() -> None:
    """Hook odpala systemowy ``python3`` (na Macu Artura 3.9) przed każdą sesją."""
    out = subprocess.run(
        [sys.executable, str(index.REPO_ROOT / "backend" / "scripts" / "build_claude_index.py"), "--print", "--part", "1"],
        capture_output=True,
        text=True,
        check=True,
        cwd="/",
    ).stdout
    assert out.startswith("Pliki reguł NEXUSA, część 1/")


def test_core_points_at_the_rules_directory() -> None:
    text = index.CLAUDE_MD.read_text(encoding="utf-8")
    assert "docs/claude/" in text
    assert "build_claude_index.py" in text, "CLAUDE.md ma mówić, jak dodać obszar bez powiększania go."
