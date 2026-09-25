"""Nordea: gotowa pozycja faktury cyklicznej z zamówienia (ticket 8, 25.09.2026).

Do faktury cyklicznej Nordei Finanse wpisują w pozycji::

    NIDS: 2022-001168, IT Retail Banking, Nordea Contact: Poul Marcussen, Contractor: Edyta Karpowicz ID:

Źródła w Call Off Agreement:

* ``NIDS`` — wartość po „NIIDS number:” w sekcji „Invoice reference”;
* ``Nordea Contact`` — „Contact person:” w TEJ SAMEJ sekcji. Nie „Nordea
  contact person” z górnej tabeli i nie „Contact person” Suppliera — te dwie
  etykiety stoją bez dwukropka, więc dwukropek w obrębie sekcji jest kotwicą;
* ``IT Retail Banking`` — stały tekst, taki sam dla każdego zamówienia;
* ``Contractor`` — osoba z tabeli „Consultant(s)” (``nordea.extract_rows``,
  ta sama reguła co odczyt zamówienia z maila);
* ``ID:`` — puste; tej informacji w zamówieniu nie ma.

W układzie pdfplumbera sekcja „Invoice reference” jest prawą kolumną
PRZEPLECIONĄ z adresem do faktury („Satamaradankatu 5, … Contact person:
Poul Marcussen”), więc wartość stoi na końcu linii.

Formuła jest ZAPISANA przy zamówieniu (``client_orders.invoice_lines``):
powstaje przy wgraniu PDF-a (``_attach_po_bytes`` — formularz i poczta
zamówień), a zamówienia sprzed wdrożenia uzupełnia pętla ``order_gaps``.
Ręczna poprawka zapisuje się na tej samej linii i przeżywa „Zrobione” —
formuła należy do zamówienia, nie do pozycji audytu.

Nieodczytane pole = ``[brak]`` w formule; ekran pokazuje wtedy ostrzeżenie
i pozwala poprawić tekst przed skopiowaniem.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.client_order import ClientOrder, ClientOrderStatus

logger = logging.getLogger(__name__)

MISSING = "[brak]"
#: Stały tekst pozycji — taki sam dla wszystkich zamówień Nordei (ticket 8).
BUSINESS_UNIT = "IT Retail Banking"
PAYLOAD_VERSION = 1
MAX_TEXT_CHARS = 500
#: Odczyt PDF-a przy wyświetlaniu (zamówienie jeszcze bez zapisanej formuły)
#: jest ograniczony — resztę dosypie pętla, a ekran nie może czekać minuty.
READ_TIME_PARSE_LIMIT = 10

_INVOICE_SECTION_RE = re.compile(
    r"Invoice\s+reference(?P<body>.*?)(?:^\s*Supplier\s*$|\Z)",
    re.I | re.S | re.M,
)
_NIIDS_RE = re.compile(
    r"\bN\s*I?\s*IDS\s*(?:number|no\.?|nr\.?)?\s*:[ \t]*(?P<v>[^\s,;]*)", re.I
)
_CONTACT_RE = re.compile(r"\bContact\s+person\s*:[ \t]*(?P<v>[^\n]*)", re.I)
_CONTACT_STOP_RE = re.compile(
    r"\s+(?:E-?mail|NIIDS|NIDS|Cost\s+center|REF)\s*:.*$", re.I
)


@dataclass(frozen=True)
class InvoiceFields:
    niids: Optional[str] = None
    contact: Optional[str] = None
    consultants: tuple[str, ...] = field(default_factory=tuple)


def is_nordea(client_id: Optional[int]) -> bool:
    """Klient Nordea = ta sama bramka co reguła odczytu zamówień Nordei."""
    from app.services.order_policies.registry import is_client_in_policy

    return is_client_in_policy("nordea", client_id)


def _clean(value: Optional[str]) -> Optional[str]:
    cleaned = re.sub(r"\s+", " ", value or "").strip(" \t,;:-–—")
    return cleaned or None


def parse_invoice_fields(text: str) -> InvoiceFields:
    """NIIDS, osoba kontaktowa z „Invoice reference” i osoby z „Consultant(s)”."""
    from app.services.order_policies import nordea

    body = nordea.order_text_only(text or "")
    section = _INVOICE_SECTION_RE.search(body)
    niids = contact = None
    if section:
        scope = section.group("body")
        if match := _NIIDS_RE.search(scope):
            niids = _clean(match.group("v"))
        if match := _CONTACT_RE.search(scope):
            contact = _clean(_CONTACT_STOP_RE.sub("", match.group("v")))
    consultants = tuple(
        name
        for name in dict.fromkeys(
            _clean(row.consultant_name) for row in nordea.extract_rows(body)
        )
        if name
    )
    return InvoiceFields(niids=niids, contact=contact, consultants=consultants)


def formula(
    niids: Optional[str], contact: Optional[str], consultant: Optional[str]
) -> str:
    return (
        f"NIDS: {niids or MISSING}, {BUSINESS_UNIT}, "
        f"Nordea Contact: {contact or MISSING}, "
        f"Contractor: {consultant or MISSING} ID:"
    )


def build_payload(
    fields: InvoiceFields,
    *,
    source: str,
    fallback_consultant: Optional[str] = None,
) -> dict:
    """Zapis przy zamówieniu: pola dokumentu + gotowa linia na każdą osobę.

    Bez żadnej osoby w tabeli jest JEDNA linia z ``[brak]`` w miejscu
    konsultanta — pusta lista wyglądałaby jak „nie dotyczy”.
    """
    people: Iterable[Optional[str]] = fields.consultants or (
        (_clean(fallback_consultant),) if source == "template" else (None,)
    )
    return {
        "version": PAYLOAD_VERSION,
        "source": source,
        "niids": fields.niids,
        "contact": fields.contact,
        "read_at": datetime.now(timezone.utc).isoformat(),
        "lines": [
            {
                "consultant": person,
                "text": formula(fields.niids, fields.contact, person),
                "edited_by": None,
                "edited_by_name": None,
                "edited_at": None,
            }
            for person in people
        ],
    }


def template_payload(consultant: Optional[str]) -> dict:
    """Zamówienie bez PDF-a: szablon z ``[brak]`` do uzupełnienia ręcznie."""
    return build_payload(
        InvoiceFields(), source="template", fallback_consultant=consultant
    )


def read_pdf_payload(path: Path | str, filename: Optional[str]) -> Optional[dict]:
    """Odczyt PDF-a zamówienia. Błąd odczytu = ``None`` (nigdy wyjątek).

    Formuła jest dodatkiem do zapisu zamówienia — nieczytelny plik nie może
    zatrzymać uploadu ani biegu poczty zamówień.
    """
    from app.services.order_document_text import extract_order_text

    try:
        text = extract_order_text(str(path), filename or Path(str(path)).name).text
    except Exception as exc:  # noqa: BLE001 — dodatek, nie bramka
        logger.warning(
            "[nordea_invoice_lines] PDF read failed (%s)", type(exc).__name__
        )
        return None
    return build_payload(parse_invoice_fields(text), source="pdf")


def refresh_on_upload(order: ClientOrder, abs_path: Path | str) -> None:
    """Wołane przy przypięciu PDF-a: nowy dokument = nowa formuła.

    Podmiana PDF-a nadpisuje także ręczną poprawkę — dane pochodzą z NOWEGO
    dokumentu, a poprawka dotyczyła poprzedniego.
    """
    if not is_nordea(order.client_id):
        return
    # Nieczytelny nowy plik = brak formuły (dosypie ją pętla), a nie formuła
    # POPRZEDNIEGO dokumentu przy nowym PDF-ie.
    order.invoice_lines = read_pdf_payload(abs_path, order.filename)


def clear_on_file_delete(order: ClientOrder) -> None:
    """Usunięcie PDF-a zdejmuje formułę odczytaną z niego (nie ręczną)."""
    payload = order.invoice_lines
    if not payload or payload.get("source") != "pdf":
        return
    if any(line.get("edited_at") for line in payload.get("lines") or []):
        return
    order.invoice_lines = None


def lines_for_consultant(payload: dict, consultant: Optional[str]) -> list[dict]:
    """Linie do pokazania na karcie jednej osoby — z indeksem zapisu.

    Karta w „Wejściach” opisuje JEDNO zamówienie jednej osoby. Gdy ta osoba
    stoi w tabeli dokumentu, pokazujemy wyłącznie jej linię (zamówienie
    wieloosobowe dałoby inaczej te same formuły na kilku kartach); gdy nie
    stoi (inna pisownia, osoba spoza tabeli) — wszystkie linie dokumentu.
    """
    from app.services.order_pdf_parser import _names_exactly_equivalent

    lines = [
        {**line, "index": index}
        for index, line in enumerate(payload.get("lines") or [])
        if isinstance(line, dict) and isinstance(line.get("text"), str)
    ]
    if consultant:
        mine = [
            line
            for line in lines
            if line.get("consultant")
            and _names_exactly_equivalent(line["consultant"], consultant)
        ]
        if mine:
            return mine
    return lines


def _abs_path(order: ClientOrder) -> Optional[Path]:
    from app.services import storage_service

    if not order.file_path:
        return None
    try:
        path = storage_service.get_client_order_po_path(order.file_path)
    except Exception:  # noqa: BLE001 — ścieżka spoza magazynu = brak pliku
        return None
    return path if path.exists() else None


async def entry_lines(
    db: AsyncSession, orders: list[tuple[int, int, str]]
) -> dict[int, list[dict]]:
    """Linie dla kart „Wejść”: ``(order_id, client_id, consultant)`` → linie.

    Tylko klient Nordea. Odczyt NIE zapisuje: zamówienie bez zapisanej
    formuły czyta PDF (najwyżej ``READ_TIME_PARSE_LIMIT``), a bez PDF-a
    dostaje szablon z ``[brak]``; zapis robi upload, pętla i ręczna poprawka.
    """
    nordea = [(oid, name) for oid, cid, name in orders if is_nordea(cid)]
    if not nordea:
        return {}
    rows = (
        (
            await db.execute(
                select(ClientOrder).where(
                    ClientOrder.id.in_([oid for oid, _ in nordea])
                )
            )
        )
        .scalars()
        .all()
    )
    by_id = {order.id: order for order in rows}
    result: dict[int, list[dict]] = {}
    parsed = 0
    for order_id, consultant in nordea:
        order = by_id.get(order_id)
        if order is None:
            continue
        payload = order.invoice_lines
        if not payload:
            path = _abs_path(order)
            if path is not None:
                if parsed >= READ_TIME_PARSE_LIMIT:
                    # Dane są w PDF-ie — szablon z [brak] kłamałby, że ich
                    # nie ma. Formułę dosypie pętla.
                    continue
                parsed += 1
                payload = await asyncio.to_thread(
                    read_pdf_payload, path, order.filename
                )
            if not payload:
                payload = template_payload(consultant)
        result[order_id] = lines_for_consultant(payload, consultant)
    return result


class InvoiceLineError(ValueError):
    pass


async def save_line(
    db: AsyncSession,
    order_id: int,
    *,
    index: int,
    text: str,
    user_id: int,
    user_name: Optional[str],
) -> list[dict]:
    """Ręczna poprawka jednej linii; zwraca wszystkie linie zamówienia."""
    cleaned = re.sub(r"[\r\n\t]+", " ", text or "").strip()
    if not cleaned:
        raise InvoiceLineError("Pozycja faktury nie może być pusta.")
    if len(cleaned) > MAX_TEXT_CHARS:
        raise InvoiceLineError(
            f"Pozycja faktury może mieć najwyżej {MAX_TEXT_CHARS} znaków."
        )
    order = await db.scalar(select(ClientOrder).where(ClientOrder.id == order_id))
    if order is None:
        raise LookupError("Nie znaleziono zamówienia.")
    if not is_nordea(order.client_id):
        raise InvoiceLineError("Pozycja faktury dotyczy wyłącznie zamówień Nordei.")
    # OCR PRZED blokadą wiersza — odczyt PDF-a trwa sekundy i nie może trzymać
    # FOR UPDATE (wstrzymałby upload PDF-a i pętlę ``fill_missing``).
    read_payload: Optional[dict] = None
    read_file = (order.file_path, order.file_uploaded_at)
    if not order.invoice_lines:
        path = _abs_path(order)
        if path is not None:
            read_payload = await asyncio.to_thread(
                read_pdf_payload, path, order.filename
            )
    order = await db.scalar(
        select(ClientOrder)
        .where(ClientOrder.id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if order is None:
        raise LookupError("Nie znaleziono zamówienia.")
    payload = order.invoice_lines
    if not payload:
        # Odczyt sprzed blokady tylko dla tego samego pliku.
        if read_payload and read_file == (order.file_path, order.file_uploaded_at):
            payload = read_payload
        if not payload:
            payload = template_payload(await _consultant_name(db, order))
    lines = list(payload.get("lines") or [])
    if not 0 <= index < len(lines):
        raise InvoiceLineError("Nie ma takiej pozycji faktury — odśwież widok.")
    line = dict(lines[index])
    line.update(
        text=cleaned,
        edited_by=user_id,
        edited_by_name=user_name,
        edited_at=datetime.now(timezone.utc).isoformat(),
    )
    lines[index] = line
    order.invoice_lines = {**payload, "lines": lines}
    flag_modified(order, "invoice_lines")
    return [{**item, "index": i} for i, item in enumerate(lines)]


async def _consultant_name(db: AsyncSession, order: ClientOrder) -> Optional[str]:
    from app.models.candidate import Candidate
    from app.models.contract import Contract

    row = (
        await db.execute(
            select(Candidate.name, Candidate.lastname)
            .join(Contract, Contract.candidate_id == Candidate.id)
            .where(Contract.id == order.contract_id)
        )
    ).first()
    if row is None:
        return None
    return _clean(f"{row[0] or ''} {row[1] or ''}")


async def fill_missing(db: AsyncSession, *, limit: int = 200) -> int:
    """Zapisz formułę zamówieniom Nordei z PDF-em, które jej jeszcze nie mają.

    Zamówienia sprzed wdrożenia i te, których PDF przyszedł ścieżką bez
    ``_attach_po_bytes``. PDF nieczytelny zapisuje szablon z ``[brak]``
    (konsultant z zamówienia) — inaczej ten sam plik byłby czytany w każdym
    biegu.

    Funkcja SAMA commituje: kończy transakcję odczytu przed OCR i zapisuje
    każde zamówienie osobno, warunkowo (formuła wciąż pusta, ten sam plik).
    Zwraca liczbę faktycznie zapisanych formuł.
    """
    from app.services.order_policies.registry import (
        client_ids_from_env,
        policy_by_key,
    )

    policy = policy_by_key("nordea")
    client_ids = policy.canonical_client_ids | client_ids_from_env(policy.env_var)
    if not client_ids:
        return 0
    orders = (
        (
            await db.execute(
                select(ClientOrder)
                .where(
                    ClientOrder.client_id.in_(client_ids),
                    ClientOrder.file_path.is_not(None),
                    ClientOrder.invoice_lines.is_(None),
                    ClientOrder.status != ClientOrderStatus.cancelled,
                )
                .order_by(ClientOrder.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    # Migawka (id, plik, stempel wgrania) i koniec transakcji odczytu PRZED OCR:
    # odczyt PDF-a trwa sekundy–minuty i nie może trzymać otwartej
    # transakcji ani blokady wiersza.
    pending: list[tuple[int, str, Optional[datetime], Path, Optional[str]]] = []
    for order in orders:
        path = _abs_path(order)
        if path is not None:
            pending.append(
                (
                    order.id,
                    order.file_path,
                    order.file_uploaded_at,
                    path,
                    order.filename,
                )
            )
    await db.commit()

    filled = 0
    for order_id, file_path, uploaded_at, path, filename in pending:
        payload = await asyncio.to_thread(read_pdf_payload, path, filename)
        if not payload:
            order = await db.get(ClientOrder, order_id)
            payload = template_payload(
                await _consultant_name(db, order) if order is not None else None
            )
        # Zapis warunkowy: w trakcie OCR ktoś mógł ręcznie poprawić formułę
        # (``save_line``) albo podmienić PDF (``_attach_po_bytes`` zapisuje
        # formułę nowego pliku) — wtedy wynik tego biegu jest nieaktualny
        # i przepada.
        result = await db.execute(
            update(ClientOrder)
            .where(
                ClientOrder.id == order_id,
                ClientOrder.invoice_lines.is_(None),
                ClientOrder.file_path == file_path,
                # Podmiana pliku pod tą samą ścieżką zmienia stempel wgrania.
                ClientOrder.file_uploaded_at.is_not_distinct_from(uploaded_at),
            )
            .values(invoice_lines=payload)
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        filled += result.rowcount or 0
    return filled
