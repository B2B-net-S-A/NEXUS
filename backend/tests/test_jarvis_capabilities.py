"""Pusty panel Jarvisa: lista możliwości z narzędzi danej roli (27.10.2026)."""

from __future__ import annotations

from app.services.jarvis.capabilities import NEVER, NOW, READ, WRITE, capabilities_for
from app.services.jarvis.tools import TOOLS_BY_NAME, tools_for_user
from app.services.section_permissions import ProductSection


def _names(sections: dict[ProductSection, int]) -> list[str]:
    return [t.name for t in tools_for_user(sections, permissions=(), hr_modules=())]


def test_every_listed_tool_exists() -> None:
    """Literówka w nazwie narzędzia po cichu chowałaby pozycję każdej roli."""
    for _label, tools in (*READ, *NOW, *WRITE):
        for name in tools:
            assert name in TOOLS_BY_NAME, name


def test_recruiter_sees_board_moves_but_not_clients() -> None:
    caps = capabilities_for(
        _names(
            {
                ProductSection.sourcing: 2,
                ProductSection.pipeline: 2,
                ProductSection.insights: 1,
            }
        )
    )
    assert "przesunięcie na tablicy" in caps["write"]
    assert "klienci, kontrakty i zamówienia" not in caps["read"]
    assert caps["never"] == list(NEVER)


def test_read_only_section_offers_nothing_to_prepare() -> None:
    caps = capabilities_for(_names({ProductSection.pipeline: 1}))
    assert "tablice rekrutacji" in caps["read"]
    assert "przesunięcie na tablicy" not in caps["write"]


def test_no_sections_still_says_what_jarvis_never_does() -> None:
    caps = capabilities_for([])
    assert caps == {"read": [], "now": [], "write": [], "never": list(NEVER)}


def test_now_lists_exactly_the_tools_with_undo() -> None:
    """Panel nie może obiecać „zrobię od razu” dla zapisu, który czeka na klik."""
    listed = {name for _label, tools in NOW for name in tools}
    assert listed == {t.name for t in TOOLS_BY_NAME.values() if t.undo is not None}
    assert not listed.intersection(name for _label, tools in WRITE for name in tools)
