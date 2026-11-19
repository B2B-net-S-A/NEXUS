"""Powód odrzucenia z treści maila CPro (19.11.2026, sprawa B7, decyzja Artura).

Od #3040 człowiek przy „Odrzuca klient” wybiera „Inne” w 5% odrzuceń, a automat
poczty CPro w 100%: każdy mail „rejected” lądował jako „Inne (rejected)”
z tekstem klienta w notatce. Ten słownik przypisuje tekst do powodu z szablonu.
Sprawdzony na 108 tekstach z produkcji (02–19.11): 104 trafiają w powód,
4 zostają przy „Inne”.

Kolejność reguł ma znaczenie, pierwsze trafienie wygrywa:

- inny dostawca przed „wybrał kogoś innego”, bo „other vendor with better price”
  to duplikat zgłoszenia, a nie wybór innej osoby;
- „wybrał kogoś innego” i „bez powodu” przed oceną osoby, bo grzecznościowe
  „candidates whose qualifications more closely align” nie mówi nic o tej osobie;
- rozmowa przed brakiem doświadczenia i wymaganiami, bo ocena po rozmowie to
  inna informacja niż ocena CV.

Tekst bez trafienia zostaje przy „Inne”, a notatka „Z CPro: …” zostaje zawsze,
więc pomyłka słownika nie gubi tego, co napisał klient.
"""

from __future__ import annotations

import re
from typing import Optional

from app.services.cpro_mail_parse import is_withdrawal
from app.services.rejection_reason_labels import (
    OTHER_LABEL,
    CLIENT_CHOSE_OTHER,
    CLIENT_INTERVIEW_WEAK,
    CLIENT_NO_REASON,
    CLIENT_OTHER_VENDOR,
    WORK_MODE_MISMATCH,
    rejection_reason_label,
)

# Nazwy z szablonu domyślnego (0006), nie kody: tak stoją w `rejection_reasons.name`.
NO_EXPERIENCE = "Brak doświadczenia"
TECH_REQUIREMENTS = "Nie spełnia wymagań technicznych"
CULTURE_FIT = "Nie pasuje kulturowo"

NOTE_PREFIX = "Z CPro:"

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in (
        (CLIENT_OTHER_VENDOR, r"other (vendor|provider)|multiple vendors|duplicat"),
        (
            CLIENT_CHOSE_OTHER,
            r"(another|other) (candidate|consultant|applicant|person)s?\b.{0,40}"
            r"(chosen|selected|stronger)"
            r"|went with another|(choose|hire) another"
            r"|proceed(ed|ing)? with (an)?other|move(d)? forward with (an)?other"
            r"|found (a suitable|another) candidate|already selected"
            r"|have now contracted|closed with other"
            r"|other profiles even more precise",
        ),
        (
            CLIENT_NO_REASON,
            r"decided to decline|not (selected|shortlisted) for interview"
            r"|will not call in|position is closed",
        ),
        (WORK_MODE_MISMATCH, r"location|to the office|dojazd"),
        (CULTURE_FIT, r"match (with|for) the team"),
        (
            CLIENT_INTERVIEW_WEAK,
            r"interview|conversation|introduce himself|reading answers|communicat"
            r"|rozmow|poradził",
        ),
        (
            NO_EXPERIENCE,
            r"(insufficient|\bno\b|lack of|not enough|not enought|not sufficient"
            r"|not strong enough|not convincing).{0,40}(experien|\bexp\b|\bPM\b)"
            r"|level of experience|experiance|experience is not matching"
            r"|PM profile not strong",
        ),
        (
            TECH_REQUIREMENTS,
            r"skill ?set|tech stack|competen|kompeten|not (the )?exact|not matching"
            r"|not a (match|fit)|(don'?t|do not|does not)( seem to| fully)? match"
            r"|feels like a match|too (technical|tech|IT)|IT (heavy|focused)"
            r"|hands on|more specific|execution|knowledge|background"
            r"|domain knowledge|testing skills|overqualified|lower side"
            r"|technical review|test automation",
        ),
    )
)


def client_text(note_or_reason: Optional[str]) -> str:
    """Tekst klienta bez przedrostka notatki „Z CPro:”."""
    text = (note_or_reason or "").strip()
    if text.startswith(NOTE_PREFIX):
        text = text[len(NOTE_PREFIX) :]
    elif text == NOTE_PREFIX.rstrip(":"):
        text = ""
    return " ".join(text.split())


def reason_name_for(cpro_reason: Optional[str]) -> Optional[str]:
    """Nazwa powodu z szablonu dla tekstu klienta; ``None`` = zostaje „Inne”.

    Mail bez tekstu to „Klient nie podał powodu”: klient odrzucił i nic nie dopisał.
    """

    text = client_text(cpro_reason)
    if not text:
        return CLIENT_NO_REASON
    for name, pattern in _RULES:
        if pattern.search(text):
            return name
    return None


def reason_label_for(cpro_reason: Optional[str]) -> str:
    """Etykieta powodu, który NEXUS wpisał dla tego maila (baner CPro w rekrutacji)."""

    if is_withdrawal(cpro_reason):
        return "Kandydat się wycofał"
    return rejection_reason_label(reason_name_for(cpro_reason)) or OTHER_LABEL
