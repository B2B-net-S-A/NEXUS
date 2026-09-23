"""Przewodniki ekranów Jarvisa nie mogą rozjechać się z ekranami, które opisują.

Treść idzie do użytkowników bez przeglądu człowieka (decyzja 23.09.2026), więc
jedyną ochroną przed przewodnikiem, który mówi o nieistniejącym przycisku,
jest przypomnienie w CI: zmiana pliku z ``sources`` przewodnika (albo samego
wpisu) wymaga świadomego przestemplowania — tak jak instrukcja zamówień.
Stary przewodnik powitalny zgnił dokładnie w ten sposób („Ogłoszenia”).

Test NIE twierdzi, że treść jest błędna. Twierdzi, że nikt jej nie przejrzał
po zmianie ekranu.
"""

from __future__ import annotations

import pytest

from app.data.screen_guides import (
    REPO_ROOT,
    SCREEN_KEYS,
    current_digests,
    load_guides,
    load_stamp,
)

_HINT = (
    "\n\nCo zrobić:\n"
    "  1. Przeczytaj przewodnik w backend/app/data/screen_guides/guides.json\n"
    "     i sprawdź, czy nazwy przycisków i kroki nadal są prawdą.\n"
    "  2. Popraw wpis (albo nie popraw nic, jeśli zmiana go nie dotyczy).\n"
    "  3. cd backend && python scripts/stamp_screen_guides.py\n"
    "  4. Zacommituj przewodnik razem ze stemplem."
)

EXPECTED_KEYS = set(SCREEN_KEYS)


def _frontend_available() -> bool:
    return (REPO_ROOT / "frontend").is_dir()


def _checkable(sources: list[str]) -> bool:
    return _frontend_available() or not any(s.startswith("frontend/") for s in sources)


def test_guides_cover_exactly_the_agreed_screens() -> None:
    assert set(load_guides()) == EXPECTED_KEYS


def test_guide_sources_exist() -> None:
    missing = [
        f"{key}: {rel}"
        for key, guide in load_guides().items()
        for rel in guide.sources
        if (_frontend_available() or not rel.startswith("frontend/"))
        and not (REPO_ROOT / rel).is_file()
    ]
    assert not missing, "Nie ma plików źródłowych przewodników:\n  · " + "\n  · ".join(
        missing
    )


def test_task_anchors_point_to_declared_anchors() -> None:
    broken = [
        f"{key}: {task.anchor}"
        for key, guide in load_guides().items()
        for task in guide.tasks
        if task.anchor and task.anchor not in {a.id for a in guide.anchors}
    ]
    assert not broken, (
        "Zadanie wskazuje kotwicę spoza listy anchors:\n  · " + "\n  · ".join(broken)
    )


def test_anchor_ids_are_unique_and_prefixed_with_the_screen_key() -> None:
    seen: dict[str, str] = {}
    for key, guide in load_guides().items():
        for anchor in guide.anchors:
            assert anchor.id.startswith(f"{key}."), (
                f"{anchor.id} nie zaczyna się od {key}."
            )
            assert anchor.id not in seen, (
                f"{anchor.id} powtórzone w {seen.get(anchor.id)} i {key}"
            )
            seen[anchor.id] = key


def test_guides_reviewed_after_screen_change() -> None:
    stamped = load_stamp()["guides"]
    current = current_digests()
    guides = load_guides()
    drifted = sorted(
        key
        for key, digest in current.items()
        if _checkable(guides[key].sources) and stamped.get(key) != digest
    )
    assert not drifted, (
        "Zmienił się ekran (albo przewodnik), a przewodnik Jarvisa nie został "
        "przejrzany:\n  · " + "\n  · ".join(drifted) + _HINT
    )


def test_stamp_covers_exactly_the_guides() -> None:
    assert set(load_stamp()["guides"]) == set(load_guides()), (
        "Stempel rozjechał się z listą przewodników." + _HINT
    )


@pytest.mark.parametrize("key", sorted(EXPECTED_KEYS))
def test_guide_text_has_no_developer_jargon(key: str) -> None:
    """Przewodnik czyta rekruter — bez ścieżek, tras API i nazw tabel."""
    guide = load_guides()[key]
    texts = [
        guide.what,
        *guide.pitfalls,
        *(t.q for t in guide.tasks),
        *(t.a for t in guide.tasks),
    ]
    for text in texts:
        for needle in ("/api/", ".py", ".tsx", "_id", "SELECT", "endpoint"):
            assert needle not in text, (
                f"{key}: „{needle}” w tekście dla użytkownika: {text}"
            )
