"""Treść zgód z formularza kariery jest JEDNA — front i backend (R8-N4-3).

Kandydat widzi ``CONSENT_CURRENT_TEXT`` i ``CONSENT_FUTURE_TEXT`` z
``frontend/src/lib/career/apply.ts``, a ``candidate_consents`` zapisuje wersję
i skrót tych samych stałych z ``career_consent``. Do rundy 8 (26.09.2026) front
nie miał adresu siedziby, więc zapisany skrót opisywał tekst, którego kandydat
nie zobaczył.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from app.services import career_consent

_FRONT = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "lib"
    / "career"
    / "apply.ts"
)


def _front_const(name: str) -> str:
    pattern = re.compile(rf'export const {name}\s*=\s*("(?:[^"\\\n]|\\.)*")\s*;')
    match = pattern.search(_FRONT.read_text(encoding="utf-8"))
    assert match, f"Nie znaleziono stałej {name} w apply.ts"
    return json.loads(match.group(1))


@pytest.mark.parametrize("name", ["CONSENT_CURRENT_TEXT", "CONSENT_FUTURE_TEXT"])
def test_frontend_consent_text_is_the_backend_text_word_for_word(name):
    assert _front_const(name) == getattr(career_consent, name)


def test_legacy_text_still_matches_the_rows_from_2026_09_26():
    """Wiersze z wersją 2026-09-26 mają skrót tej treści — archiwum nie może
    się zmienić ani o znak."""
    legacy = career_consent.LEGACY_CONSENT_TEXT_2026_09_26
    assert (
        hashlib.sha256(legacy.encode("utf-8")).hexdigest()
        == "110fca06cd3204e3a7a8ff0efcfe0bc8dbd60611415ccc27b6bbe06397aca5da"
    )
