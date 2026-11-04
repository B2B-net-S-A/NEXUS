"""Traffit jest wyłączony na stałe (decyzja Artura 14.10.2026).

„My już z Traffita nie korzystamy, żadne importy z Traffita ani sync nie
powinny już działać.” Do 14.10 import zatrzymywała tylko zmienna
`TRAFFIT_SYNC_ENABLED=false`, którą da się włączyć z powrotem, a część torów
(przeniesienie fal, scalenie bliźniaków, naprawy dat i notatek, poller
kontaktów, zapis kandydata z JJIT do Traffita) jej nie czytała.

Ten moduł jest jedynym strażnikiem. Każde wejście, które pobiera dane z API
Traffita albo pisze do Traffita, woła `refuse_traffit()` na początku: trasy
`/api/admin/traffit/*` odpowiadają 410, pętle w tle nie startują (jedna linia
logu), CLI `import_traffit` kończy się kodem ≠ 0. Flagi Traffita w ustawieniach
są wymuszone na `False` (`app/core/config.py`), żeby czytający je kod
(zamrożenie wyścigów, analityka, kolejka kontaktów) nie czekał na import,
którego nie będzie.

Bez zmiennej środowiskowej celowo: powrót do Traffita to zmiana kodu
z decyzją Artura, nie przełącznik w Coolify. Moduły importera zostają jako
historia, a dane z Traffita w bazie (archiwum, `external_source='traffit'`,
kolumny) są czytane jak dotąd.
"""

from __future__ import annotations

from datetime import date
from typing import NoReturn

TRAFFIT_RETIRED_ON = date(2026, 10, 14)
TRAFFIT_RETIRED_MESSAGE = (
    "Traffit jest wyłączony od 14.10.2026 — NEXUS nie importuje już danych z Traffita."
)
#: Wartość `checks.traffit` w `/api/health`. `disabled`, nie nowe słowo:
#: kafelek „Stan systemu” pokazuje je jako „Wyłączone” (jak dotychczasowe
#: `unconfigured`), a uptime-probe milczy (allowlista od 14.10.2026).
TRAFFIT_HEALTH_VALUE = "disabled"


class TraffitRetiredError(Exception):
    """Wejście do Traffita po jego wyłączeniu.

    Celowo nie `RuntimeError`: `TraffitConfig.from_env()` zgłasza brak
    sekretów jako `RuntimeError`, a wołający łapią go jako „pomiń bieg”.
    Wyłączenie nie może się pod to podszyć.
    """

    def __init__(self, entry: str) -> None:
        super().__init__(TRAFFIT_RETIRED_MESSAGE)
        self.entry = entry


def refuse_traffit(entry: str) -> NoReturn:
    """Odmawia każdego wejścia do Traffita; ``entry`` mówi, które to było."""
    raise TraffitRetiredError(entry)


__all__ = [
    "TRAFFIT_HEALTH_VALUE",
    "TRAFFIT_RETIRED_MESSAGE",
    "TRAFFIT_RETIRED_ON",
    "TraffitRetiredError",
    "refuse_traffit",
]
