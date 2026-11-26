"""Wzór dokumentu z poczty rozliczeń, który sam wskazuje klienta.

Czytnik skrzynki pyta o to tylko wtedy, gdy osoba pracuje naraz u dwóch klientów
(``identity.resolve_by_template``). Inny plik nie mówi, czyj jest.

* Karta ewidencji świadczenia usług (KCP) Banku Pocztowego. Sam tytuł noszą też
  karty innych klientów (archiwum III–XI 2026: Alior i PKO BP), a wydruk karty
  Aliora z NEXUS-a ma również „Suma dni przepracowanych”. Wzór banku poznajemy
  więc po wypełnionym wierszu „Liczba godzin czas podstawowy”.
* Time Sheet VeloBanku (``timesheet.parse_velobank``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.services.client_settlements import kcp, timesheet


@dataclass(frozen=True)
class Template:
    #: Klucz klienta z ``order_policies/known_clients``.
    client_key: str
    #: Osoba wpisana w pliku; ``None``, gdy pole jest puste.
    person: Optional[str]
    #: ``(rok, miesiąc)`` z pliku.
    month: Optional[tuple[int, int]]


def _month(value: Optional[str]) -> Optional[tuple[int, int]]:
    if value is None:
        return None
    year, month = value.split("-")
    return int(year), int(month)


def recognize(content: bytes, file_name: str) -> Optional[Template]:
    """Wzór klienta w pliku PDF albo XLSX; ``None`` = plik nie wskazuje klienta."""

    if content[:5] == b"%PDF-":
        mime = kcp.PDF
    elif content[:2] == b"PK" and file_name.lower().endswith((".xlsx", ".xlsm")):
        mime = kcp.XLSX
    else:
        return None
    card = kcp.parse(content, mime)
    if card is not None and card.declared_hours is not None:
        return Template("bank_pocztowy", card.person, _month(card.month))
    if mime == kcp.XLSX:
        sheet = timesheet.parse_velobank(content)
        if sheet is not None:
            return Template("velobank", sheet.consultant, _month(sheet.month))
    return None
