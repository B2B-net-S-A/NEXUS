"""Treść zgody z formularza strony kariery — jedno źródło dla API i frontu.

Zmiana treści = nowa ``CONSENT_TEXT_VERSION``. Wiersze ``candidate_consents``
niosą wersję i skrót treści, więc stara zgoda nadal wskazuje dokładnie to, co
kandydat zobaczył. Klauzula informacyjna (``/rodo`` na stronie kariery) nosi
ten sam numer wersji.
"""

from __future__ import annotations

import hashlib

# 2026-09-21: pierwsza wersja. 2026-09-26 (runda 8, R8-N4-3): front pokazywał
# tekst BEZ adresu siedziby, a zapisywaliśmy skrót tekstu z adresem — od tej
# wersji obie strony mają tekst z adresem (test lustra pilnuje zgodności).
# Wiersze z wersją 2026-09-21 zostają, jak były.
CONSENT_TEXT_VERSION = "2026-09-26"

CONSENT_TEXT = (
    "Wyrażam zgodę na przetwarzanie moich danych osobowych przez B2B.NET S.A. "
    "z siedzibą w Warszawie (Al. Jerozolimskie 180, 02-486 Warszawa) w celu "
    "prowadzenia obecnych i przyszłych procesów rekrutacyjnych."
)

CONSENT_TEXT_SHA256 = hashlib.sha256(CONSENT_TEXT.encode("utf-8")).hexdigest()

# Wartości pola formularza, które znaczą „zaznaczone" (checkbox HTML wysyła
# „on", nasz front „true").
_TRUTHY = frozenset({"true", "1", "on", "yes", "tak"})


def consent_given(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUTHY
