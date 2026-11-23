"""Jedna skrzynka wsparcie@ (E8): który czytnik bierze wiadomość.

Decyzja Artura z 18.11.2026: rozliczenia@ i administracja@ trafiają do jednej skrzynki
``wsparcie@`` w M365, a NEXUS sam rozdziela pocztę. Na jeden Inbox patrzą wtedy dwa czytniki,
rozliczeń (``consultant_portal/mailbox.py``) i spraw (``admin_cases/mail_ingest.py``), każdy
z własnym znacznikiem. Mail **z załącznikiem i z adresem rozliczeń w „Do” albo „DW”**
(``CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES``) bierze czytnik rozliczeń, każdy inny czytnik
spraw. Obie strony pytają tę samą funkcję, więc wiadomość trafia do dokładnie jednego
czytnika. Bez tego każdy raport stałby się i dokumentem, i sprawą.

Router działa tylko wtedy, gdy obie zmienne skrzynek wskazują tę samą skrzynkę, a czytnik spraw
pomija maile rozliczeń tylko przy działającym czytniku rozliczeń (portal ``internal``/``pilot``/
``all``). Osobne skrzynki bez adresów = każdy czytnik bierze swoją w całości, jak przed E8.
Dwa stany są błędem konfiguracji i zatrzymują czytnik rozliczeń bez ruszania znacznika
(``misconfiguration``): wspólna skrzynka bez adresów (``shared_without_route``) i adresy przy
osobnych skrzynkach (``route_not_shared``, np. wsparcie@ ustawiona przed skrzynką spraw).

Mail na rozliczenia@ bez załącznika (pytanie) jest sprawą. Mail wysłany w ukrytej kopii nie ma
adresu rozliczeń w nagłówkach, które czytamy, więc też jest sprawą.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from app.core.config import settings

#: Pola Graph potrzebne routerowi; czytniki dopisują je do swojego ``$select``
#: (``from`` i ``subject`` dla raportów godzin oba czytniki pobierają już same).
RECIPIENT_FIELDS = "toRecipients,ccRecipients"


def _norm(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def settlements_addresses() -> frozenset[str]:
    """Adresy rozliczeń z ``CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES`` (po przecinku)."""

    raw = settings.CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES or ""
    return frozenset(_norm(part) for part in raw.split(",") if _norm(part))


def shared_route(
    settlements_mailbox: Optional[str], cases_mailbox: Optional[str]
) -> Optional[frozenset[str]]:
    """Adresy rozliczeń, gdy oba czytniki czytają jedną skrzynkę; ``None`` = osobne skrzynki.

    Pusty zbiór znaczy „wspólna skrzynka bez adresów rozliczeń”: czytnik rozliczeń wtedy stoi.
    """

    left, right = _norm(settlements_mailbox), _norm(cases_mailbox)
    if not left or left != right:
        return None
    return settlements_addresses()


def recipients(message: dict[str, Any]) -> frozenset[str]:
    """Adresy z „Do” i „DW” wiadomości Graph, małymi literami."""

    found: set[str] = set()
    for key in ("toRecipients", "ccRecipients"):
        for item in message.get(key) or []:
            address = ((item or {}).get("emailAddress") or {}).get("address")
            if _norm(address):
                found.add(_norm(address))
    return frozenset(found)


def is_settlements_mail(message: dict[str, Any], addresses: frozenset[str]) -> bool:
    """Wiadomość dla czytnika rozliczeń: załącznik i adres rozliczeń w „Do”/„DW”,
    albo raport godzin klienta (``is_time_report_mail``) na dowolny adres skrzynki."""

    if not message.get("hasAttachments"):
        return False
    return bool(recipients(message) & addresses) or is_time_report_mail(message)


_TIME_REPORT_SUBJECT = re.compile(r"\bT4T\b|time\s*for\s*teams", re.IGNORECASE)


def time_report_senders() -> frozenset[str]:
    """Domeny albo adresy nadawców raportów godzin klienta
    (``CONSULTANT_PORTAL_TIME_REPORT_SENDERS``, po przecinku)."""

    raw = settings.CONSULTANT_PORTAL_TIME_REPORT_SENDERS or ""
    return frozenset(_norm(part).lstrip("@") for part in raw.split(",") if _norm(part))


def is_time_report_mail(message: dict[str, Any]) -> bool:
    """Raport Time for Teams od klienta albo przekazany przez Finanse (Nordea, 23.11.2026).

    Cost Control Nordei wysyła raport na skrzynkę koordynatorki i na wsparcie@ (bez adresu
    rozliczeń), a gdy zapomni, Finanse przekazują go dalej z „T4T” w temacie. Bez tej
    reguły router oddałby raport czytnikowi spraw. Czytnik rozliczeń bierze z takiego maila
    tylko arkusz raportu (``client_settlements/t4t_mail.py``).
    """

    if not message.get("hasAttachments"):
        return False
    sender = _norm(
        ((message.get("from") or {}).get("emailAddress") or {}).get("address")
    )
    senders = time_report_senders()
    if sender and (sender in senders or sender.rpartition("@")[2] in senders):
        return True
    return bool(_TIME_REPORT_SUBJECT.search(str(message.get("subject") or "")))


def misconfiguration(route: Optional[frozenset[str]]) -> Optional[str]:
    """Kod błędu, przy którym czytnik rozliczeń stoi; ``route`` z ``shared_route``."""

    if route is not None and not route:
        return "shared_without_route"
    if route is None and settlements_addresses():
        return "route_not_shared"
    return None
