"""Formy gramatyczne zależne od płci Partnera (M/K) dla szablonu umowy B2B.

Oryginalny draft prawnika ma w komparycji i deklaracji formy „na żółto"
(``Panem/ią``, ``prowadzącym/cą``, ``zwany/ą``, ``zwanym``, ``zapoznałem``).
Generator podstawia właściwą formę na podstawie wybranej płci. Angielska wersja
jest neutralna płciowo poza ``Mr/Ms``.

Klucze trafiają do kontekstu renderu jako ``b2b.g_*`` (patrz ``render_context``
i ``_contract_vars``); szablon używa ``{{ b2b.g_pan }}`` itd.
"""

from __future__ import annotations

#: Domyślnie męska forma (gdy płeć nieokreślona) — bezpieczny fallback dla
#: starej ścieżki ``/generate`` bez pola płci.
_FORMS_M = {
    "g_pan": "Panem",
    "g_prowadzacy": "prowadzącym",
    "g_zwany": "zwany",
    "g_zwanym": "zwanym",
    "g_zapoznal": "zapoznałem",
    "g_mr": "Mr",
    # Formy dokumentów pochodnych (aneksy, rozwiązania, przedwstępna — 09.2026).
    "g_pan_nom": "Pan",
    "g_prowadzacy_nom": "prowadzący",
    "g_zamieszkaly": "zamieszkałym",
    "g_legitymujacy": "legitymującym się",
    "g_legitymujacy_nom": "legitymujący się",
    "g_przekazal": "przekazałem",
    "g_zlozyl": "złożyłem",
    "g_mr_long": "Mr",
}
_FORMS_F = {
    "g_pan": "Panią",
    "g_prowadzacy": "prowadzącą",
    "g_zwany": "zwana",
    "g_zwanym": "zwaną",
    "g_zapoznal": "zapoznałam",
    "g_mr": "Ms",
    "g_pan_nom": "Pani",
    "g_prowadzacy_nom": "prowadząca",
    "g_zamieszkaly": "zamieszkałą",
    "g_legitymujacy": "legitymującą się",
    "g_legitymujacy_nom": "legitymująca się",
    "g_przekazal": "przekazałam",
    "g_zlozyl": "złożyłam",
    "g_mr_long": "Ms",
}


def is_female(gender: str | None) -> bool:
    """``f``/``female``/``k``/``kobieta`` → kobieta; reszta → mężczyzna."""
    return (gender or "").strip().lower()[:1] in ("f", "k")


def gender_forms(gender: str | None) -> dict[str, str]:
    """Słownik form ``g_*`` dla wybranej płci (domyślnie męska)."""
    return dict(_FORMS_F if is_female(gender) else _FORMS_M)
