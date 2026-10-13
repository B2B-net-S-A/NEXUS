"""Neutralizacja znaczników w danych wklejanych do promptu (audyt 22.09 r2, AI-03).

Prompty generatora CV opakowują dane w znaczniki (`<cv>`, `<screening_notes>`,
`<champion_profile>`) i mówią modelowi, że to, co w środku, jest DANYMI.
Tekst CV wgranego przez kandydata mógł jednak zawierać własne `</cv>
<screening_notes>…` — model widział wtedy „notatkę rekrutera” dopisaną przez
kandydata i traktował ją jak dowód do CV.

`neutralize_tags` zamienia `<` na `‹` (U+2039) WYŁĄCZNIE w dopasowaniach
znaczników, którymi posługują się nasze prompty (i typowych nazw ról), więc
zwykły tekst (`a < b`, `C<T>`, HTML w CV) zostaje nietknięty. Walidatory
(cytaty, dowody) dalej pracują na ORYGINALNYM tekście — neutralizacja dotyczy
wyłącznie tego, co trafia do modelu.
"""

from __future__ import annotations

import json
import re
from typing import Any

_TAG_RE = re.compile(
    r"<(?=\s*/?\s*(?:cv|screening_notes|champion_profile|source_facts|"
    r"previous_screening|candidate_[a-z_]+|new_questions|interview_note|"
    r"card_fields|screening_questions|keywords|question_text|"
    r"cv_[a-z_]+|original_[a-z_]+|recruiter_hint|recruiter_command|previous_proposals|"
    r"client_[a-z_]+|system|assistant|user|developer|instructions?)\b)",
    re.IGNORECASE,
)

_LOOKALIKE = "\u2039"


def neutralize_tags(text: str | None) -> str:
    """Zamienia `<` otwierające znacznik promptu na `‹`."""
    if not text:
        return ""
    return _TAG_RE.sub(_LOOKALIKE, text)


# Odwrotność `neutralize_tags`: podmieniony znak tylko tam, gdzie stoi przed
# nazwą znacznika (wzorzec budowany z `_TAG_RE`, żeby lista nazw była jedna).
_NEUTRALIZED_RE = re.compile(_LOOKALIKE + _TAG_RE.pattern[1:], re.IGNORECASE)


def restore_tags(text: str | None) -> str:
    """Tekst skopiowany przez model z ogrodzonych danych — w pierwotnej postaci.

    Ogrodzenie podmienia `<` także w zwykłej treści, która wygląda jak znacznik
    (`Flux<User>` w CV programisty). Model cytuje to, co widzi; kontrola „cytat
    stoi w źródle” porównuje z prawdziwym tekstem, więc cytat trzeba odwrócić.
    """
    if not text:
        return ""
    return _NEUTRALIZED_RE.sub("<", text)


def fence(tag: str, text: str | None) -> str:
    """Opakowuje dane w znacznik tak, żeby nie dało się go zamknąć od środka."""
    return f"<{tag}>\n{neutralize_tags(text).strip()}\n</{tag}>"


def json_for_prompt(value: Any) -> str:
    """JSON do promptu bez sekwencji `</` (zamienionej na poprawny JSON `<\\/`)."""
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")
