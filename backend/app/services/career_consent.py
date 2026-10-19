"""Treść zgód z formularza strony kariery — jedno źródło dla API i frontu.

Zmiana treści = nowa ``CONSENT_TEXT_VERSION``. Wiersze ``candidate_consents``
niosą wersję i skrót treści, więc stara zgoda nadal wskazuje dokładnie to, co
kandydat zobaczył. Klauzula informacyjna (``/rodo`` na stronie kariery) nosi
ten sam numer wersji.

Od 2026-10-19 (decyzja D Artura) formularz ma DWIE zgody:

* ``CONSENT_CURRENT_TEXT`` — obowiązkowa, na tę rekrutację
  (``kind = recruitment_current``);
* ``CONSENT_FUTURE_TEXT`` — dobrowolna, na przyszłe rekrutacje
  (``kind = recruitment_future``); wiersz powstaje tylko, gdy kandydat ją
  zaznaczył.

Wiersze sprzed tej zmiany mają ``kind = recruitment_current_future`` (jedna
zgoda na oba cele, treść ``LEGACY_CONSENT_TEXT_2026_09_26``) i zostają, jak
były — taka zgoda obejmuje także przyszłe rekrutacje.
"""

from __future__ import annotations

import hashlib

# 2026-09-21: pierwsza wersja. 2026-09-26 (runda 8, R8-N4-3): tekst z adresem
# siedziby. 2026-10-19: dwie zgody zamiast jednej (decyzja D).
CONSENT_TEXT_VERSION = "2026-10-19"

_CONTROLLER = (
    "przez B2B.NET S.A. z siedzibą w Warszawie (Al. Jerozolimskie 180, 02-486 Warszawa)"
)

CONSENT_CURRENT_TEXT = (
    f"Wyrażam zgodę na przetwarzanie moich danych osobowych {_CONTROLLER} "
    "w celu przeprowadzenia rekrutacji, na którą przesyłam zgłoszenie."
)

CONSENT_FUTURE_TEXT = (
    f"Wyrażam zgodę na przetwarzanie moich danych osobowych {_CONTROLLER} "
    "w celu prowadzenia przyszłych procesów rekrutacyjnych, w tym "
    "przedstawiania mi propozycji innych projektów IT."
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


CONSENT_CURRENT_TEXT_SHA256 = _sha256(CONSENT_CURRENT_TEXT)
CONSENT_FUTURE_TEXT_SHA256 = _sha256(CONSENT_FUTURE_TEXT)

# Archiwum: treść, na którą wskazują wiersze ``text_version = 2026-09-26``
# (``kind = recruitment_current_future``). Nie używać w nowych zgodach.
LEGACY_CONSENT_TEXT_2026_09_26 = (
    "Wyrażam zgodę na przetwarzanie moich danych osobowych przez B2B.NET S.A. "
    "z siedzibą w Warszawie (Al. Jerozolimskie 180, 02-486 Warszawa) w celu "
    "prowadzenia obecnych i przyszłych procesów rekrutacyjnych."
)

# Wartości pola formularza, które znaczą „zaznaczone" (checkbox HTML wysyła
# „on", nasz front „true").
_TRUTHY = frozenset({"true", "1", "on", "yes", "tak"})


def consent_given(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUTHY
