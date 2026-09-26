"""Treść zgody z formularza kariery jest JEDNA — front i backend (R8-N4-3).

Kandydat widzi ``CONSENT_TEXT`` z ``frontend/src/lib/career/apply.ts``, a
``candidate_consents`` zapisuje wersję i skrót ``career_consent.CONSENT_TEXT``.
Do rundy 8 (26.09.2026) front nie miał adresu siedziby, więc zapisany skrót
opisywał tekst, którego kandydat nie zobaczył.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.services.career_consent import CONSENT_TEXT

_FRONT = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "lib"
    / "career"
    / "apply.ts"
)
_CONST = re.compile(r'export const CONSENT_TEXT\s*=\s*("(?:[^"\\\n]|\\.)*")\s*;')


def test_frontend_consent_text_is_the_backend_text_word_for_word():
    match = _CONST.search(_FRONT.read_text(encoding="utf-8"))
    assert match, "Nie znaleziono stałej CONSENT_TEXT w apply.ts"
    assert json.loads(match.group(1)) == CONSENT_TEXT
