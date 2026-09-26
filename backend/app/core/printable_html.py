"""Wspólna otoczka dokumentów „do druku” (CV etapu, szkic i snapshot umowy).

Front otwiera te dokumenty przez ``openAuthenticatedFile(..., "text/html")``:
bajty lecą przez ``fetch`` z nagłówkiem Bearer, a nowa karta dostaje
``blob:`` URL. Blob ma ORIGIN APLIKACJI (ten sam ``localStorage`` z tokenem)
i NIE niesie nagłówków odpowiedzi — CSP ustawiona nagłówkiem HTTP w trasie
(``_CONTRACT_PREVIEW_CSP``) w tej karcie nie obowiązuje. Dlatego polityka
jedzie W DOKUMENCIE, jako pierwszy element ``<head>``: przeglądarka stosuje
``<meta http-equiv="Content-Security-Policy">`` także do dokumentów z bloba,
a wszystko, co parser zobaczy po niej (np. wstrzyknięte ``</title><img
onerror>`` z imienia kandydata), już jej podlega.

Jedyny dozwolony skrypt to nasz auto-print, wpuszczony po skrócie SHA-256.
Tytuł jest zawsze escapowany — imię i nazwisko przychodzą z publicznego
formularza kariery (audyt bezpieczeństwa 24.09.2026).
"""

from __future__ import annotations

import base64
import hashlib
from html import escape

AUTOPRINT_JS = "window.addEventListener('load',()=>setTimeout(()=>window.print(),300));"
AUTOPRINT_HASH = "sha256-" + base64.b64encode(
    hashlib.sha256(AUTOPRINT_JS.encode("utf-8")).digest()
).decode("ascii")

# Deny-by-default. Style inline (formatowanie dokumentów prawnych i CV),
# obrazy i fonty wyłącznie z data: — dokument do druku niczego nie pobiera
# z sieci, więc wstrzyknięta treść nie ma też kanału wysyłki danych.
PRINTABLE_CSP = (
    "default-src 'none'; "
    f"script-src '{AUTOPRINT_HASH}'; "
    "style-src 'unsafe-inline'; img-src data:; font-src data:; "
    "base-uri 'none'; form-action 'none'"
)

# Ta sama polityka bez żadnego skryptu — dokument bez auto-printu (np. szablon
# umowy otwierany przez ``document.write`` w nowym oknie pod originem aplikacji).
PRINTABLE_CSP_NO_SCRIPT = (
    "default-src 'none'; "
    "style-src 'unsafe-inline'; img-src data:; font-src data:; "
    "base-uri 'none'; form-action 'none'"
)


def printable_document(
    body_html: str, title: str, *, head_extra: str = "", autoprint: bool = True
) -> str:
    """Pełny dokument HTML z CSP w ``<meta>`` jako PIERWSZYM elementem głowy.

    ``title`` to zwykły tekst (escapowany tutaj); ``body_html`` i
    ``head_extra`` muszą pochodzić z zaufanego kodu albo z sanitizera —
    CSP z ``<meta>`` jest drugą linią obrony, nie pierwszą. ``autoprint=False``
    = bez skryptu i z polityką, która nie wpuszcza żadnego.
    """
    csp = PRINTABLE_CSP if autoprint else PRINTABLE_CSP_NO_SCRIPT
    script = f"<script>{AUTOPRINT_JS}</script>" if autoprint else ""
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{csp}">'
        f"<title>{escape(title, quote=False)}</title>"
        f"{head_extra}"
        f"{script}"
        "</head><body>"
        f"{body_html}"
        "</body></html>"
    )
