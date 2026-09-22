"""Treść zgody z formularza strony kariery — jedno źródło dla API i frontu.

Zmiana treści = nowa ``CONSENT_TEXT_VERSION``. Wiersze ``candidate_consents``
niosą wersję i skrót treści, więc stara zgoda nadal wskazuje dokładnie to, co
kandydat zobaczył. Klauzula informacyjna (``/rodo`` na stronie kariery) nosi
ten sam numer wersji.
"""

from __future__ import annotations

import hashlib

CONSENT_TEXT_VERSION = "2026-09-21"

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
