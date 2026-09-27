"""Zmienne szablonów maili do kandydatów — JEDNA lista dla UI i wysyłki.

Runda 9 (R9-N10-5): ekran szablonów obiecywał zmienne (``{{company_name}}``,
``{{interview_date}}``, ``{{salary}}``, ``{{recruiter_email}}``,
``{{application_date}}``), których wysyłka maila odrzucenia
(``rejection_email_scheduler._render``) nigdy nie wypełniała — kandydat
dostawał dosłowne ``{{company_name}}``. Lista niżej to DOKŁADNIE to, co
wypełnia wysyłka. Lustro na froncie: ``AVAILABLE_PLACEHOLDERS`` w
``frontend/src/app/settings/templates/page.tsx`` (pilnuje
``tests/test_r9_mail_template_variables.py``).
"""

from __future__ import annotations

import re
from html import escape as html_escape

# (nazwa, opis po polsku) — kolejność = kolejność przycisków w edytorze.
TEMPLATE_VARIABLES: tuple[tuple[str, str], ...] = (
    ("candidate_name", "Imię kandydata"),
    ("candidate_lastname", "Nazwisko kandydata"),
    ("candidate_full_name", "Imię i nazwisko kandydata"),
    ("job_title", "Tytuł stanowiska"),
    ("recruiter_name", "Imię i nazwisko rekrutera"),
    ("other_processes_count", "Liczba innych procesów kandydata"),
    ("other_processes_list", "Lista innych procesów kandydata"),
)

SUPPORTED_VARIABLES: frozenset[str] = frozenset(name for name, _ in TEMPLATE_VARIABLES)

# Konstrukcje sterujące wysyłki odrzucenia — nie są zmiennymi.
_CONTROL_TOKENS = frozenset({"#if other_processes", "/if"})

# Bez zagnieżdżonych kwantyfikatorów — czas liniowy na tekście autora.
_TOKEN_RE = re.compile(r"\{\{([^{}]{0,80})\}\}")


def unsupported_variables(*texts: str | None) -> list[str]:
    """Zmienne ``{{…}}``, których wysyłka nie wypełni (posortowane, bez powtórzeń)."""
    found: set[str] = set()
    for text in texts:
        for raw in _TOKEN_RE.findall(text or ""):
            token = " ".join(raw.split())
            if token in _CONTROL_TOKENS or token in SUPPORTED_VARIABLES:
                continue
            found.add("{{" + token + "}}")
    return sorted(found)


_HTML_TAG_RE = re.compile(
    r"<\s*/?\s*(?:p|br|div|span|strong|b|i|em|u|ul|ol|li|a|table|tr|td|th|h[1-6])\b",
    re.IGNORECASE,
)
_PARAGRAPH_BREAK_RE = re.compile(r"\n[ \t]*\n")


def body_to_html(body: str | None) -> str:
    """Treść szablonu → HTML treści maila.

    Szablon napisany w polu tekstowym (bez znaczników HTML) szedł do Graph jako
    HTML, więc akapity i podpis sklejały się w jedną linię, a ``&`` / ``<`` z
    treści były interpretowane jako HTML. Tekst zwykły: escape, pusta linia =
    nowy akapit, pojedynczy enter = ``<br>``. Treść ze znacznikami HTML zostaje
    bez zmian (tak jest napisany szablon auto-odrzucenia).
    """
    text = body or ""
    if _HTML_TAG_RE.search(text):
        return text
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""
    paragraphs = [p.strip() for p in _PARAGRAPH_BREAK_RE.split(normalized) if p.strip()]
    return "\n".join(
        "<p>" + html_escape(p, quote=False).replace("\n", "<br>\n") + "</p>"
        for p in paragraphs
    )
