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

Mail na rozliczenia@ bez załącznika (pytanie) jest sprawą, chyba że pisze klient z regułą
akceptacji mailowej (``acceptance_clients``): wtedy to akceptacja godzin w treści i bierze go
czytnik rozliczeń. Jeśli przyszedł z adresu firmy z tematem rozliczenia, czytnik rozliczeń
dodatkowo zapisuje jego treść jako dokument jednej osoby (``mailbox.is_body_only_settlement``,
23.11.2026); router tego nie zmienia, więc sprawa też powstaje. Mail wysłany w ukrytej kopii
nie ma adresu rozliczeń w nagłówkach, które czytamy, więc też jest sprawą.
"""

from __future__ import annotations

import re
from collections.abc import Set
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Optional

from app.core.config import settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

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


def is_settlements_mail(
    message: dict[str, Any],
    addresses: frozenset[str],
    acceptance_domains: Set[str] = frozenset(),
) -> bool:
    """Wiadomość dla czytnika rozliczeń: załącznik i adres rozliczeń w „Do”/„DW”,
    albo raport godzin klienta (``is_time_report_mail``) na dowolny adres skrzynki,
    albo akceptacja klienta w samej treści (``is_client_acceptance_mail``)."""

    if not message.get("hasAttachments"):
        return is_client_acceptance_mail(message, addresses, acceptance_domains)
    return bool(recipients(message) & addresses) or is_time_report_mail(message)


def sender_domain(message: dict[str, Any]) -> str:
    sender = _norm(
        ((message.get("from") or {}).get("emailAddress") or {}).get("address")
    )
    return sender.rpartition("@")[2] if "@" in sender else ""


def is_client_acceptance_mail(
    message: dict[str, Any], addresses: frozenset[str], domains: Set[str]
) -> bool:
    """Akceptacja godzin w treści maila, bez załącznika (próba rozliczeń IX–X 2026).

    PKO i BIK odpisują w wątku z TS na adres rozliczeń, np. „łączna liczba godzin: 112,
    październik 2026”. Bez tej reguły router oddawał to czytnikowi spraw, a kontrola
    ``proof.accept_has_hours`` nie miała czego sprawdzić. Wymagamy adresu rozliczeń w „Do”/„DW”
    i nadawcy dokładnie z domeny klienta z regułą akceptacji mailowej; resztę bierze sprawa.
    """

    domain = sender_domain(message)
    return bool(domain) and domain in domains and bool(recipients(message) & addresses)


async def acceptance_clients(db: "AsyncSession") -> dict[str, frozenset[int]]:
    """Domena nadawcy → klienci, od których akceptacja mailowa idzie do rozliczeń.

    * ``proof.excel_with_mail`` włączona z domeną: ta domena (BIK, BNP, VIP Solution);
    * ``proof.accept_has_hours`` włączona: domena z ``proof.excel_with_mail``, a bez niej
      domeny adresów kontaktów klienta (PKO ma tę regułę bez domeny);
    * ``cl.client_acceptance`` włączona: domena jej adresu (odpowiedź Banku Pocztowego
      na paczkę KCP, którą czyta ``consultant_portal.mailbox._store_client_reply``).

    Zestawy reguł są od miesiąca, a akceptacja za miesiąc przychodzi na jego końcu albo na
    początku następnego, dlatego bierzemy reguły bieżącego i poprzedniego miesiąca.
    """

    from sqlalchemy import select

    from app.core.scheduling import business_today
    from app.models.client_settlement import ClientSettlementRuleSet
    from app.services.client_settlements import acceptance_mail, service

    today = business_today()
    previous = today.replace(day=1) - timedelta(days=1)
    months = {f"{d.year}-{d.month:02d}" for d in (today, previous)}
    client_ids = (
        await db.scalars(select(ClientSettlementRuleSet.client_id).distinct())
    ).all()
    found: dict[str, set[int]] = {}
    for client_id in client_ids:
        for month in months:
            rules = await service.rules_for(db, client_id, month)
            on = {key for key, rule in rules.items() if rule["level"] != "off"}
            excel = list(
                acceptance_mail.domains(
                    str(rules["proof.excel_with_mail"]["params"].get("domain") or "")
                )
            )
            domains = (
                excel
                if on & {"proof.excel_with_mail", "proof.accept_has_hours"}
                else []
            )
            if "proof.accept_has_hours" in on and not excel:
                domains = await _contact_domains(db, client_id)
            email = _norm(
                str(rules["cl.client_acceptance"]["params"].get("email") or "")
            )
            if "cl.client_acceptance" in on and "@" in email:
                domains = [*domains, email.rpartition("@")[2]]
            for domain in domains:
                found.setdefault(domain, set()).add(client_id)
    return {domain: frozenset(ids) for domain, ids in found.items()}


async def _contact_domains(db: "AsyncSession", client_id: int) -> list[str]:
    from sqlalchemy import func, select

    from app.models.contact import Contact

    rows = await db.scalars(
        select(func.lower(Contact.email)).where(
            Contact.client_id == client_id, Contact.email.like("%@%")
        )
    )
    return sorted({_norm(email).rpartition("@")[2] for email in rows if email})


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
