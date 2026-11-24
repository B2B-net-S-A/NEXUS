"""Wymagania klienta do faktury sprawdzane na miesiąc usługi (reguły ``cl.*``, 24.11.2026).

Przegląd skrzynek Finansów i kopii dokumentów klientów z 24.11.2026 pokazał dwa
ryzyka przy fakturach sprzedaży:

* ``cl.bzone_order`` — klient przyjmuje fakturę tylko z numerem zlecenia z modułu
  B-ZONE (``K/RRRR/<nr>/<inicjały>/<nr>/<kod projektu>``), które obejmuje okres
  faktury. Zlecenia są miesięczne albo kwartalne i przychodzą do KAM-a, a osoba
  potrafi zacząć pracę, zanim bank wystawi zlecenie. Każdy dzień roboczy pracy
  osoby w miesiącu (miesiąc ∩ okres kontraktu) musi leżeć w okresie zamówienia
  klienta w NEXUSIE z numerem w tym formacie; zamówień tej osoby może być kilka
  (zlecenie do 15., następne od 16.). Brak = faktura nie wychodzi (decyzja Artura).
* ``cl.client_protocol`` — klient przysyła podpisany protokół odbioru ok. miesiąc po
  okresie, a faktury wychodziły wcześniej z wewnętrznego zestawienia godzin; jedna
  wymagała korekty. Faktura bez protokołu od klienta za ten miesiąc dostaje
  ostrzeżenie, nie blokadę (decyzja Artura). Okres i numer umowy bierzemy z treści
  PDF (``protocol_collective``), nie z tematu maila: tematy bywają te same dla różnych
  miesięcy, a w wątku jednej umowy przyszedł protokół innej.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Mapping, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_executive_contract import ClientExecutiveContract
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import (
    GROUP_STATUS_CANCELLED,
    GROUP_STATUS_DRAFT,
    ClientOrderGroup,
)
from app.models.consultant_portal import CpDocument
from app.models.contract import Contract, ContractStatus
from app.services.client_settlements import protocol_collective
from app.services.hr.calendar import holiday_name, month_range

logger = logging.getLogger(__name__)

#: ``K/2026/123456/AB/1234/26KOD`` — numer zlecenia z modułu B-ZONE.
BZONE_NUMBER = re.compile(
    r"(?<![\w/])K/20\d{2}/\d+/[^\W\d_]{1,5}/\d+/[0-9A-Za-z]+(?![\w/])"
)
BZONE_MESSAGE = "Brak zlecenia B-ZONE na ten okres — poproś KAM o zlecenie"
_SETTLING = (ClientOrderStatus.active, ClientOrderStatus.completed)
_PROTOCOL_CACHE: dict[str, Optional[protocol_collective.Protocol]] = {}
_CACHE_MAX = 256


def bzone_number(text: Optional[str]) -> Optional[str]:
    """Numer zlecenia B-ZONE z numeru zamówienia; niepełny numer = ``None``."""

    found = BZONE_NUMBER.search(" ".join(str(text or "").split()))
    return found.group(0) if found else None


def _business(day: date) -> bool:
    return day.weekday() < 5 and holiday_name(day) is None


@dataclass(frozen=True)
class Span:
    start: Optional[date]
    end: Optional[date]

    def covers(self, day: date) -> bool:
        return (self.start is None or self.start <= day) and (
            self.end is None or day <= self.end
        )


def line_span(
    start: Optional[date],
    end: Optional[date],
    group_start: Optional[date],
    group_end: Optional[date],
) -> Span:
    """Okres zlecenia dla linii zamówienia MD: część wspólna linii i grupy.

    Numer zlecenia należy do grupy, więc linia z własną datą końca późniejszą niż
    koniec grupy (skrócenie grupy nie rusza takiej linii) nie przedłuża zlecenia."""

    starts = [d for d in (start, group_start) if d is not None]
    ends = [d for d in (end, group_end) if d is not None]
    return Span(max(starts) if starts else None, min(ends) if ends else None)


def work_span(
    period: str,
    *,
    start: Optional[date],
    end: Optional[date],
    terminated: Optional[date] = None,
) -> Optional[tuple[date, date]]:
    """Dni miesiąca ``RRRR-MM`` w okresie kontraktu; ``None`` = kontrakt poza miesiącem."""

    year, month = (int(part) for part in period.split("-"))
    first, last = month_range(year, month)
    stop = min(d for d in (end, terminated, last) if d is not None)
    begin = max(start, first) if start is not None else first
    return (begin, stop) if begin <= stop else None


def uncovered_days(
    orders: Iterable[tuple[Optional[str], Span]], *, need: tuple[date, date]
) -> list[date]:
    """Dni robocze ``need`` bez zamówienia z numerem B-ZONE, które je obejmuje."""

    spans = [span for number, span in orders if bzone_number(number)]
    day, out = need[0], []
    while day <= need[1]:
        if _business(day) and not any(span.covers(day) for span in spans):
            out.append(day)
        day += timedelta(days=1)
    return out


def day_ranges(days: Sequence[date]) -> str:
    """„03.11–14.11.2026, 30.11.2026” — kolejne dni robocze sklejone w zakresy."""

    groups: list[list[date]] = []
    for day in sorted(days):
        if groups:
            gap = groups[-1][-1] + timedelta(days=1)
            while gap < day and not _business(gap):
                gap += timedelta(days=1)
            if gap == day:
                groups[-1].append(day)
                continue
        groups.append([day])
    out = []
    for group in groups:
        head, tail = group[0], group[-1]
        if head == tail:
            out.append(tail.strftime("%d.%m.%Y"))
        else:
            out.append(f"{head.strftime('%d.%m')}–{tail.strftime('%d.%m.%Y')}")
    return ", ".join(out)


def bzone_message(gaps: Mapping[str, Sequence[date]]) -> Optional[str]:
    """Komunikat blokady ``cl.bzone_order``: osoba i dni bez zlecenia."""

    if not gaps:
        return None
    people = "; ".join(
        f"{person} ({day_ranges(days)})" if days else person
        for person, days in sorted(gaps.items())
    )
    return f"{BZONE_MESSAGE}: {people}."


async def bzone_gaps(
    db: AsyncSession, *, client_id: int, contract_ids: Iterable[int], period: str
) -> dict[int, list[date]]:
    """Kontrakty z dniami pracy w miesiącu bez zlecenia B-ZONE (``{kontrakt: dni}``).

    Zlecenia to zamówienia klienta tej osoby (aktywne i zakończone, bez szkiców
    i anulowanych): numer samodzielnego zamówienia to tytuł, linii zamówienia MD —
    numer grupy. Kontrakt bez dni pracy w miesiącu nie potrzebuje zlecenia."""

    ids = sorted({int(i) for i in contract_ids})
    if not ids:
        return {}
    contracts = {
        c.id: c for c in await db.scalars(select(Contract).where(Contract.id.in_(ids)))
    }
    rows = await db.execute(
        select(
            ClientOrder.contract_id,
            ClientOrder.title,
            ClientOrder.start_date,
            ClientOrder.end_date,
            ClientOrderGroup.order_number,
            ClientOrderGroup.status,
            ClientOrderGroup.start_date,
            ClientOrderGroup.end_date,
        )
        .outerjoin(ClientOrderGroup, ClientOrderGroup.id == ClientOrder.order_group_id)
        .where(
            ClientOrder.contract_id.in_(ids),
            ClientOrder.client_id == client_id,
            ClientOrder.status.in_(_SETTLING),
        )
    )
    orders: dict[int, list[tuple[Optional[str], Span]]] = {}
    for (
        contract_id,
        title,
        start,
        end,
        group_number,
        group_status,
        group_start,
        group_end,
    ) in rows.all():
        if group_status in (GROUP_STATUS_CANCELLED, GROUP_STATUS_DRAFT):
            continue
        if group_status is None:
            orders.setdefault(contract_id, []).append((title, Span(start, end)))
        else:
            orders.setdefault(contract_id, []).append(
                (group_number, line_span(start, end, group_start, group_end))
            )
    out: dict[int, list[date]] = {}
    for contract_id in ids:
        contract = contracts.get(contract_id)
        if contract is None or contract.status == ContractStatus.void:
            continue
        need = work_span(
            period,
            start=contract.start_date,
            end=contract.end_date,
            terminated=contract.terminated_at,
        )
        if need is None:
            continue
        days = uncovered_days(orders.get(contract_id, []), need=need)
        if days:
            out[contract_id] = days
    return out


# ── Protokół odbioru od klienta (``cl.client_protocol``) ────────────────────


@dataclass(frozen=True)
class ProtocolNeed:
    """Osoba faktury, dla której szukamy protokołu."""

    contract_id: int
    person: str
    #: Numer umowy wykonawczej osoby (zamówienie klienta); ``None`` = nie wiemy.
    contract_number: Optional[str] = None


def protocol_matches(
    protocol: Optional[protocol_collective.Protocol],
    need: ProtocolNeed,
    *,
    period: str,
    doc_month: Optional[str],
) -> bool:
    """Protokół za ``period`` z osobą i umową z treści PDF.

    Okres z treści (CeZ); protokół bez okresu w treści (PFRON) — okres dokumentu
    z nazwy pliku albo tematu, nie zgadnięty z daty maila. Umowa z treści musi być
    umową osoby, gdy NEXUS ją zna."""

    if protocol is None:
        return False
    month = protocol.month or doc_month
    if month != period or protocol_collective.person_in(protocol, need.person) is None:
        return False
    wanted = protocol_collective.contract_key(need.contract_number)
    if wanted is None:
        return True
    return protocol_collective.contract_key(protocol.contract) == wanted


def protocol_message(people: Iterable[str]) -> Optional[str]:
    """Ostrzeżenie ``cl.client_protocol`` (fakturę można wysłać mimo niego)."""

    names = sorted(set(people))
    if not names:
        return None
    return (
        "Brak protokołu odbioru od klienta za ten miesiąc — faktura może wymagać "
        f"korekty: {', '.join(names)}."
    )


async def _protocol(doc: CpDocument) -> Optional[protocol_collective.Protocol]:
    if doc.sha256 in _PROTOCOL_CACHE:
        return _PROTOCOL_CACHE[doc.sha256]
    from app.services.consultant_portal import documents as portal_documents

    try:
        content = portal_documents.path_for(doc.file_path).read_bytes()
    except (FileNotFoundError, OSError) as exc:
        logger.warning(
            "faktura: protokół %s nie do odczytu (%s)", doc.id, type(exc).__name__
        )
        return None
    found = await asyncio.to_thread(protocol_collective.parse, content, doc.mime)
    if len(_PROTOCOL_CACHE) >= _CACHE_MAX:
        _PROTOCOL_CACHE.clear()
    _PROTOCOL_CACHE[doc.sha256] = found
    return found


def _doc_month(doc: CpDocument) -> Optional[str]:
    if doc.period_guessed:
        return None
    return f"{doc.period_year:04d}-{doc.period_month:02d}"


async def without_protocol(
    db: AsyncSession, *, client_id: int, needs: Sequence[ProtocolNeed], period: str
) -> list[str]:
    """Osoby bez protokołu odbioru od klienta za miesiąc.

    Protokół to PDF z raportów miesiąca osoby (``cp_documents``), którego nadawca
    jest z domeny klienta. Protokół podpisany przez PM-a i odesłany do klienta
    z DW rozliczenia@ ma nadawcę klienta z wątku (``mailbox._thread_client_address``),
    a PDF z adresu firmy bez klienta w wątku się nie liczy."""

    if not needs:
        return []
    from app.services.consultant_portal import identity

    year, month = (int(part) for part in period.split("-"))
    docs = list(
        await db.scalars(
            select(CpDocument).where(
                CpDocument.contract_id.in_({n.contract_id for n in needs}),
                CpDocument.kind == "report",
                CpDocument.mime == protocol_collective.PDF,
                CpDocument.status != "rejected",
                CpDocument.period_year == year,
                CpDocument.period_month == month,
            )
        )
    )
    from_client: dict[str, bool] = {}
    by_contract: dict[int, list[CpDocument]] = {}
    for doc in docs:
        sender = doc.sender_email or ""
        if sender not in from_client:
            from_client[sender] = bool(sender) and client_id in (
                await identity.client_ids_for_sender(db, sender)
            )
        if from_client[sender]:
            by_contract.setdefault(int(doc.contract_id), []).append(doc)
    missing = []
    for need in needs:
        found = False
        for doc in by_contract.get(need.contract_id, []):
            if protocol_matches(
                await _protocol(doc), need, period=period, doc_month=_doc_month(doc)
            ):
                found = True
                break
        if not found:
            missing.append(need.person)
    return missing


async def executive_numbers(
    db: AsyncSession, order_ids: Iterable[int]
) -> dict[int, str]:
    """Numer umowy wykonawczej zamówienia osoby (``{order_id: numer}``)."""

    ids = sorted({int(i) for i in order_ids})
    if not ids:
        return {}
    rows = await db.execute(
        select(ClientOrder.id, ClientExecutiveContract.number)
        .join(
            ClientExecutiveContract,
            ClientExecutiveContract.id == ClientOrder.executive_contract_id,
        )
        .where(ClientOrder.id.in_(ids))
    )
    return {order_id: number for order_id, number in rows.all() if number}


__all__ = [
    "BZONE_MESSAGE",
    "ProtocolNeed",
    "Span",
    "bzone_gaps",
    "bzone_message",
    "bzone_number",
    "line_span",
    "day_ranges",
    "executive_numbers",
    "protocol_matches",
    "protocol_message",
    "uncovered_days",
    "without_protocol",
    "work_span",
]
