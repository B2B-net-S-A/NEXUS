"""Stare nazwy nie wracają do menu, zakładek i pomocy (decyzja Artura 03.11.2026).

Słownik: ``docs/claude/ui/nazwy-wspolpracy-koordynacja-rozliczenia.md``. Test czyta
pliki, które widzi każdy, i pomija komentarze. Słowa UoP mieszkają w słowniku form,
którego ten test nie sprawdza.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

OLD_NAMES = (
    "Mój zespół",
    "Mój czas",
    "Moim czasie",
    "Kadry",
    "Płace",
    "Timesheet",
    "timesheetów",
    "Rytm dnia",
    "Na daily",
)

#: Nazwy spoza NEXUSA, które zostają (aplikacja w Entra ID).
ALLOWED = ("NEXUS Kadry",)

CHECKED = (
    "frontend/src/lib/nav-registry.ts",
    "frontend/src/components/v2/shell/BreadcrumbV2.tsx",
    "frontend/src/components/hr/people/PeopleSectionNav.tsx",
    "frontend/src/components/v2/dashboard/NewPersonSetupDialog.tsx",
    "frontend/src/components/v2/dashboard/NewPeopleSection.tsx",
    "backend/app/data/screen_guides/guides.json",
    "backend/app/data/novelties/start.json",
    "backend/app/services/hr/hr_mail.py",
    "backend/app/services/new_person_setup.py",
)

COMMENT = re.compile(r"^\s*(//|\*|/\*|\{/\*|#)")


def _visible_lines(relative: str) -> list[tuple[int, str]]:
    text = (ROOT / relative).read_text(encoding="utf-8")
    # Docstring na górze modułu i cudzysłowy potrójne to opis dla programisty.
    if relative.endswith(".py"):
        text = re.sub(r'"""[\s\S]*?"""', lambda m: "\n" * m.group(0).count("\n"), text)
    return [
        (number, line)
        for number, line in enumerate(text.splitlines(), start=1)
        if not COMMENT.match(line) and "frontend/src/" not in line
    ]


@pytest.mark.parametrize("relative", CHECKED)
def test_old_names_do_not_come_back(relative: str) -> None:
    found = []
    for number, line in _visible_lines(relative):
        cleaned = line
        for allowed in ALLOWED:
            cleaned = cleaned.replace(allowed, "")
        found.extend(
            f"{relative}:{number}: {name}" for name in OLD_NAMES if name in cleaned
        )
    assert found == [], (
        "Stare nazwy, słownik w docs/claude/ui/nazwy-wspolpracy-…:\n" + "\n".join(found)
    )


def test_new_person_window_says_coordinator() -> None:
    lines = "\n".join(line for _, line in _visible_lines(CHECKED[3]))
    assert "Koordynator" in lines
    assert "Przełożony" not in lines
