"""Klauzula zgody RODO na końcu CV firmowego — jedno rozpoznanie dla QC i DOCX.

Generator pisze ją jako ``<p class="rodo">`` bez znacznika sekcji, edytor
dokłada ``data-cv-section="rodo"`` dopiero po zapisie, a starsze zatwierdzone
CV zgubiły oba znaczniki — zostają pierwsze słowa klauzuli z szablonu.
"""

from __future__ import annotations

from functools import lru_cache

OPENING_WORDS = 5
# Klauzula zaczyna się od stałych słów; dalsza część akapitu nie jest potrzebna.
_PROBE_CHARS = 200


def _norm(text: str) -> str:
    return " ".join((text or "").split()).casefold()


@lru_cache(maxsize=1)
def rodo_openings() -> tuple[str, ...]:
    # Leniwie: `docx_renderer` ciągnie python-docx, a szablon jest stały.
    from app.services.cv_generator_b2b.docx_renderer import TRANSLATIONS

    return tuple(
        _norm(" ".join(t["rodo"].split()[:OPENING_WORDS]))
        for t in TRANSLATIONS.values()
    )


def is_rodo_text(text: str) -> bool:
    """Czy akapit zaczyna się jak klauzula zgody z szablonu (PL albo EN)."""
    return _norm((text or "")[:_PROBE_CHARS]).startswith(rodo_openings())
