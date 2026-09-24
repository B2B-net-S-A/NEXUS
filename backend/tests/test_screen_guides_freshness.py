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

from app.data.review_stamps import GUIDE_STAMPS_REL, guide_drift, orphan_guide_stamps
from app.data.review_stamps import GUIDES_HINT as _HINT
from app.data.screen_guides import REPO_ROOT, SCREEN_KEYS, load_guides

EXPECTED_KEYS = set(SCREEN_KEYS)


def _frontend_available() -> bool:
    return (REPO_ROOT / "frontend").is_dir()


def _checkable_source(relative: str) -> bool:
    return _frontend_available() or not relative.startswith("frontend/")


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
    """Każdy ekran ma własny stempel (``stamps/<klucz>.json``) — PR ruszający
    inny ekran nie przepisuje Twojego, więc kolejka merge'ów ich nie zderza."""
    drift = guide_drift(checkable=_checkable_source)
    drifted = sorted(f"{key} ({', '.join(reasons)})" for key, reasons in drift.items())
    assert not drifted, (
        "Zmienił się ekran (albo przewodnik), a przewodnik Jarvisa nie został "
        "przejrzany:\n  · " + "\n  · ".join(drifted) + _HINT
    )


def test_stamp_covers_exactly_the_guides() -> None:
    guides = set(load_guides())
    stamped = {p.stem for p in (REPO_ROOT / GUIDE_STAMPS_REL).glob("*.json")}
    assert stamped == guides and not orphan_guide_stamps(), (
        "Stempel rozjechał się z listą przewodników.\n"
        f"Tylko w stemplach: {sorted(stamped - guides) or '—'}\n"
        f"Bez stempla: {sorted(guides - stamped) or '—'}" + _HINT
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
