"""Rozliczenia: raporty i faktury z portalu i ze skrzynki ``rozliczenia@``.

Oba kanały kończą w ``store``, więc dają tę samą kartę w kolumnie ``invoice``: karta
to (kontrakt, okres, rodzaj), a nie plik (``sources.document_cards``). Ten sam plik
z drugiego kanału to ten sam wiersz, także gdy czytnik źle zgadł okres. Inny plik za
ten sam okres dokłada się do tej samej karty.

Typ pliku rozpoznaje ``documents_store.check`` po treści; nazwa od człowieka nie trafia
na dysk. Plik czyta zespół Finansów, a konsultant tylko ten, który wysłał sam
(``sent_by_consultant``): plik od klienta bywa zbiorczy.
Raport przyjęty przez Finanse daje konsultantowi sygnał „wystaw fakturę”.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.core.upload_filename import fit_filename_column
from app.models.consultant_portal import CpDocument
from app.models.contract import Contract
from app.models.consultant_panel import ClientSettlementRule
from app.services import storage_service
from app.services.consultant_portal import identity, portal_mail
from app.services.consultant_portal.auth import PortalContext, PortalError
from app.services.consultant_portal_schema import (
    COMMENT_MAX,
    DOCUMENT_KINDS,
    FILE_NAME_MAX,
)
from app.services.client_settlements import kesu, timesheet_plus
from app.services.hr import documents_store

logger = logging.getLogger(__name__)

SUBDIR = "consultant_portal"
MONTHS_BACK = 24
#: Starsze miesiące pokazujemy tylko wtedy, gdy mają dokument: rozliczenia sprzed portalu
#: szły mailem i nie mogą wyglądać jak zaległości.
OVERVIEW_MONTHS = 3
MAX_FILE_BYTES = documents_store.MAX_FILE_BYTES
NOT_FOUND = "Nie ma takiego dokumentu."
BAD_PERIOD = "Wybierz miesiąc z ostatnich dwóch lat, najpóźniej bieżący."
BAD_KIND = "Wybierz raport albo fakturę."
ALREADY_DECIDED = "Ten dokument ma już decyzję."


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
#: KEŚU z Jiry klienta (E6.3): rozszerzenie .xls, w środku XML Spreadsheet 2003.
KESU_MIME = kesu.KESU_MIME
#: Arkusz z makrami: tylko szablon klienta (PKO, roadmapa E6.1). Makr nie
#: uruchamiamy nigdzie w NEXUS-ie, a plik pobiera się jako załącznik.
XLSM_MIME = "application/vnd.ms-excel.sheet.macroEnabled.12"
MSG_MIME = "application/vnd.ms-outlook"
EML_MIME = "message/rfc822"
#: Rozliczenia (roadmapa E2.0): RCP w Excelu i mail z akceptacją z Outlooka
#: albo jako .eml. Tylko w portalu konsultanta; reszta ``documents_store`` bez zmian.
SETTLEMENT_EXTENSIONS: dict[str, str] = {
    XLSX_MIME: "xlsx",
    KESU_MIME: "xls",
    XLSM_MIME: "xlsm",
    MSG_MIME: "msg",
    EML_MIME: "eml",
}
_OLE_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_EML_HEADERS = (b"from:", b"subject:", b"mime-version:", b"message-id:", b"date:")
_EML_HEAD_LIMIT = 64 * 1024


def _spreadsheet(content: bytes) -> Optional[str]:
    """XLSX albo XLSM (z makrami) po zawartości archiwum; inny ZIP = ``None``."""

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = {entry.filename for entry in archive.infolist()}
    except (zipfile.BadZipFile, OSError):
        return None
    if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
        return None
    if any(name.lower().endswith("vbaproject.bin") for name in names):
        return XLSM_MIME
    return XLSX_MIME


def _is_msg(content: bytes) -> bool:
    # Kontener OLE z polami wiadomości Outlooka; stary .doc/.xls ich nie ma.
    return (
        content.startswith(_OLE_HEADER)
        and "__substg1.0_".encode("utf-16-le") in content
    )


def _is_eml(content: bytes) -> bool:
    # Cały blok nagłówków (do pierwszej pustej linii), nie pierwsze 4 KB: w poczcie
    # z M365 i home.pl Received/ARC/DKIM zajmują 8–10 KB, a Date, Message-ID
    # i MIME-Version stoją dalej (próba IX–XI 2026: 31% maili odpadało).
    head = content[:_EML_HEAD_LIMIT]
    end = min(
        (i for i in (head.find(b"\r\n\r\n"), head.find(b"\n\n")) if i >= 0),
        default=len(head),
    )
    head = head[:end].lower()
    lines = {
        line.split(b":", 1)[0] + b":" for line in head.splitlines() if b":" in line
    }
    return sum(header in lines for header in _EML_HEADERS) >= 3


def check_settlement_file(content: bytes) -> tuple[str, str]:
    """Typ i SHA-256 pliku rozliczenia: typy ``documents_store`` plus XLSX, MSG i EML."""

    if content and len(content) <= MAX_FILE_BYTES:
        spreadsheet = (
            _spreadsheet(content) if content.startswith(b"PK\x03\x04") else None
        )
        if spreadsheet is not None:
            return spreadsheet, hashlib.sha256(content).hexdigest()
        if _is_msg(content):
            return MSG_MIME, hashlib.sha256(content).hexdigest()
        if kesu.is_kesu_file(content) or timesheet_plus.is_polkomtel_report(content):
            # Raport Polkomtelu z Jiry to tabela HTML z rozszerzeniem .xls; trzymamy
            # go jak arkusz .xls (pobranie zawsze jako załącznik, nigdy jako strona).
            return KESU_MIME, hashlib.sha256(content).hexdigest()
        if documents_store.sniff_mime(content) is None and _is_eml(content):
            return EML_MIME, hashlib.sha256(content).hexdigest()
    try:
        return documents_store.check(content)
    except documents_store.FileRejected as exc:
        if "Wgraj PDF" in str(exc):
            raise documents_store.FileRejected(
                "Wgraj PDF, arkusz Excel (XLSX, XLSM), mail z Outlooka (MSG, EML), plik Word (DOCX) "
                "albo zdjęcie (JPG, PNG)."
            ) from None
        raise


def relative_path(owner: str, digest: str, mime: str) -> str:
    extension = SETTLEMENT_EXTENSIONS.get(mime) or documents_store.EXTENSIONS[mime]
    return f"{SUBDIR}/{owner}/{digest}.{extension}"


def _save(owner: str, content: bytes, *, mime: str, digest: str) -> str:
    relative = relative_path(owner, digest, mime)
    target = Path(storage_service.STORAGE_ROOT) / relative
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f"{target.name}.part")
        temporary.write_bytes(content)
        os.replace(temporary, target)
    return relative


def path_for(relative: str) -> Path:
    """Ścieżka pliku pod katalogiem portalu, bez wyjścia poza niego."""

    root = Path(storage_service.STORAGE_ROOT).resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root / SUBDIR)
    except ValueError:
        raise FileNotFoundError("poza katalogiem portalu") from None
    if not path.is_file():
        raise FileNotFoundError("brak pliku")
    return path


def valid_period(year: int, month: int, *, today: date) -> bool:
    if not 1 <= month <= 12:
        return False
    index = year * 12 + month
    current = today.year * 12 + today.month
    return current - MONTHS_BACK <= index <= current


@dataclass(frozen=True)
class Stored:
    document: CpDocument
    duplicate: bool


async def _same_file(
    db: AsyncSession,
    *,
    contract_id: Optional[int],
    kind: str,
    digest: str,
    graph_message_id: Optional[str],
) -> Optional[CpDocument]:
    if contract_id is not None:
        return await db.scalar(
            select(CpDocument)
            .where(
                CpDocument.contract_id == contract_id,
                CpDocument.kind == kind,
                CpDocument.sha256 == digest,
            )
            .order_by(CpDocument.id)
            .limit(1)
        )
    if graph_message_id:
        return await db.scalar(
            select(CpDocument).where(
                CpDocument.graph_message_id == graph_message_id,
                CpDocument.sha256 == digest,
            )
        )
    return None


async def stored_from_mail(
    db: AsyncSession, graph_message_id: str, content: bytes
) -> bool:
    """Ten plik z tego maila już leży w dokumentach. Czytnik wraca do świeżych maili,
    a identyfikator maila razem z plikiem może nosić tylko jeden dokument."""

    existing = await _same_file(
        db,
        contract_id=None,
        kind="report",
        digest=hashlib.sha256(content).hexdigest(),
        graph_message_id=graph_message_id,
    )
    return existing is not None


async def store(
    db: AsyncSession,
    *,
    contract_id: Optional[int],
    kind: str,
    year: int,
    month: int,
    content: bytes,
    file_name: Optional[str],
    channel: str,
    now: datetime,
    period_guessed: bool = False,
    graph_message_id: Optional[str] = None,
    sender_email: Optional[str] = None,
) -> Stored:
    """Jedno wejście obu kanałów. Odrzuca plik zły, a ten sam plik zwraca bez zapisu."""

    if kind not in DOCUMENT_KINDS:
        raise PortalError(BAD_KIND)
    try:
        mime, digest = check_settlement_file(content)
    except documents_store.FileRejected as exc:
        raise PortalError(str(exc), code="bad_file") from None
    existing = await _same_file(
        db,
        contract_id=contract_id,
        kind=kind,
        digest=digest,
        graph_message_id=graph_message_id,
    )
    if existing is not None:
        return Stored(existing, True)
    relative = _save(
        str(contract_id) if contract_id else "unmatched",
        content,
        mime=mime,
        digest=digest,
    )
    document = CpDocument(
        contract_id=contract_id,
        kind=kind,
        period_year=year,
        period_month=month,
        period_guessed=period_guessed,
        channel=channel,
        status="received",
        file_path=relative,
        file_name=fit_filename_column(file_name, FILE_NAME_MAX) if file_name else None,
        mime=mime,
        size_bytes=len(content),
        sha256=digest,
        graph_message_id=graph_message_id,
        sender_email=sender_email,
        created_at=now,
        updated_at=now,
    )
    try:
        async with db.begin_nested():
            db.add(document)
            await db.flush()
    except IntegrityError:
        # Dwa kanały naraz: wygrywa pierwszy zapis, drugi dostaje ten sam wiersz.
        existing = await _same_file(
            db,
            contract_id=contract_id,
            kind=kind,
            digest=digest,
            graph_message_id=graph_message_id,
        )
        if existing is None:
            raise
        return Stored(existing, True)
    await _refresh_settlement(db, document)
    return Stored(document, False)


async def _refresh_settlement(db: AsyncSession, document: CpDocument) -> None:
    """Rozliczenia klientów (E2.4): nowe RCP przelicza rozliczenie miesiąca.

    W SAVEPOINT i bez wyjątku na zewnątrz: odczyt pliku jest dodatkiem, przyjęcie
    dokumentu działa także wtedy, gdy parser albo moduł rozliczeń zawiodą.
    """

    from app.services.client_settlements import service as settlements

    try:
        async with db.begin_nested():
            await settlements.refresh_for_document(db, document)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "rozliczenia: przeliczenie po dokumencie %s nie wyszło (%s)",
            document.id,
            type(exc).__name__,
        )


# ── Konsultant ───────────────────────────────────────────────────────────────


def _doc_row(document: CpDocument) -> dict[str, Any]:
    return {
        "id": document.id,
        "kind": document.kind,
        "status": document.status,
        "file_name": document.file_name,
        "channel": document.channel,
        "created_at": document.created_at.isoformat(),
        "reject_reason": document.reject_reason
        if document.status == "rejected"
        else None,
    }


def sent_by_consultant(document: CpDocument, email: str) -> bool:
    """Plik, który konsultant wysłał sam: z portalu albo mailem ze swojego adresu.

    Tylko taki plik konsultant pobiera i widzi z nazwą (decyzja Artura z 24.11.2026).
    Czytniki rozliczenia@ zapisują ten sam plik zbiorczy klienta (arkusz CA, protokół
    CeZ albo PFRON, .eml koordynatora, tabela zamówień) przy kontrakcie każdej osoby
    z dokumentu, a w nim są godziny i nazwiska pozostałych. Lista dozwolona, a nie
    flaga „zbiorczy”: obejmuje pliki już zapisane i każdy przyszły czytnik."""

    if document.channel == "portal":
        return True
    address = identity.normalize_email(email)
    return bool(address) and identity.normalize_email(document.sender_email) == address


def _portal_doc(document: CpDocument, email: str) -> dict[str, Any]:
    own = sent_by_consultant(document, email)
    return {
        **_doc_row(document),
        "file_name": document.file_name if own else None,
        "downloadable": own,
    }


def _best(documents: list[CpDocument], kind: str) -> Optional[CpDocument]:
    """Najważniejszy stan okresu: decyzja pozytywna, potem czekający, potem odrzucony."""

    rank = {"paid": 0, "accepted": 1, "received": 2, "rejected": 3}
    rows = [row for row in documents if row.kind == kind]
    return min(rows, key=lambda row: (rank[row.status], -row.id)) if rows else None


REPORT_LABELS = {
    "received": "Raport: czeka na akceptację",
    "accepted": "Raport: zaakceptowany",
    "paid": "Raport: zaakceptowany",
    "rejected": "Raport: do poprawy",
}
INVOICE_LABELS = {
    "received": "Faktura: przyjęta do sprawdzenia",
    "accepted": "Faktura: przyjęta",
    "paid": "Faktura: opłacona",
    "rejected": "Faktura: do poprawy",
}


def _client_report_row(
    year: int, month: int, documents: list[CpDocument], *, email: str
) -> dict[str, Any]:
    """Raport przysyła klient, więc konsultant ma tylko krok z fakturą."""

    invoice = _best(documents, "invoice")
    action = "send_invoice" if invoice is None or invoice.status == "rejected" else None
    return {
        "year": year,
        "month": month,
        "report_label": "Raport: przysyła klient",
        "invoice_label": INVOICE_LABELS[invoice.status]
        if invoice
        else "Faktura: czekamy",
        "issue_invoice": action == "send_invoice",
        "action": action,
        "documents": [_portal_doc(row, email) for row in documents],
    }


def month_row(
    year: int,
    month: int,
    documents: list[CpDocument],
    *,
    mode: Optional[str] = None,
    email: str = "",
) -> dict[str, Any]:
    """Stan miesiąca i następny krok konsultanta (czysta funkcja).

    ``mode`` to szablon rozliczenia klienta; bez szablonu raport wysyła konsultant.
    ``email`` to adres konsultanta: plik z innego adresu jest bez nazwy i linku.
    """

    if mode == "client_report":
        return _client_report_row(year, month, documents, email=email)

    report = _best(documents, "report")
    invoice = _best(documents, "invoice")
    if report is None or report.status == "rejected":
        action: Optional[str] = "send_report"
    elif report.status == "received":
        action = None
    elif invoice is None or invoice.status == "rejected":
        # Raport przyjęty: to jest sygnał „wystaw fakturę”.
        action = "send_invoice"
    else:
        action = None
    return {
        "year": year,
        "month": month,
        "report_label": REPORT_LABELS[report.status]
        if report
        else "Raport: do wysłania",
        "invoice_label": INVOICE_LABELS[invoice.status]
        if invoice
        else (
            "Faktura: wystaw i wyślij"
            if action == "send_invoice"
            else "Faktura: po akceptacji raportu"
        ),
        "issue_invoice": action == "send_invoice",
        "action": action,
        "documents": [_portal_doc(row, email) for row in documents],
    }


def _months_back(today: date, count: int) -> list[tuple[int, int]]:
    total = today.year * 12 + today.month - 1
    return [
        ((total - offset) // 12, (total - offset) % 12 + 1) for offset in range(count)
    ]


async def overview(
    db: AsyncSession, context: PortalContext, *, today: date
) -> list[dict[str, Any]]:
    rows = (
        await db.scalars(
            select(CpDocument)
            .where(CpDocument.contract_id.in_(context.consultant.contract_ids))
            .order_by(CpDocument.period_year.desc(), CpDocument.period_month.desc())
        )
    ).all()
    contract = await db.get(Contract, context.consultant.contract_id)
    start = contract.start_date if contract else None
    by_month: dict[tuple[int, int], list[CpDocument]] = {
        key: []
        for key in _months_back(today, OVERVIEW_MONTHS)
        if start is None or key >= (start.year, start.month)
    }
    for row in rows:
        by_month.setdefault((row.period_year, row.period_month), []).append(row)
    rule = (
        await db.get(ClientSettlementRule, contract.client_id)
        if contract and contract.client_id
        else None
    )
    rows = [
        month_row(
            year,
            month,
            by_month[(year, month)],
            mode=rule.mode if rule else None,
            email=context.consultant.email,
        )
        for year, month in sorted(by_month, reverse=True)
    ]
    # Rozliczenia klientów (E3): stan RCP, wynik sprawdzenia i dane do faktury.
    from app.services.client_settlements import consultant as settlement_view

    for row in rows:
        # Trwa miesiąc z estymacją: plik to plan, przycisk „Wyślij plan” (E5.4).
        row["plan"] = await settlement_view.plan_month(
            db,
            contract.client_id if contract else None,
            row["year"],
            row["month"],
            today,
        )
        settlement = (
            await settlement_view.view(
                db,
                context.consultant.contract_id,
                contract.client_id if contract else None,
                row["year"],
                row["month"],
            )
            if contract
            else None
        )
        apply_settlement(row, settlement)
        if row["plan"] and row["action"] == "send_invoice":
            # Decyzja Artura z 10.11: miesiąc z planem konsultant fakturuje
            # dopiero po RCP za cały miesiąc, nie po przyjęciu planu.
            row["action"] = None
            row["issue_invoice"] = False
            row["invoice_label"] = "Faktura: po RCP za cały miesiąc"
        # Dodatki do faktury (polecenie, delegacja): stan zgłoszeń osoby.
        row["extras"] = (
            await settlement_view.own_extras(
                db, context.consultant.contract_id, row["year"], row["month"]
            )
            if contract
            else None
        )
    return rows


def apply_settlement(row: dict[str, Any], settlement: Optional[dict[str, Any]]) -> None:
    """Dołącza rozliczenie do wiersza miesiąca. Przyjęte rozliczenie zamyka krok
    raportu także wtedy, gdy Finanse przyjęły MD wpisane bez pliku: następny krok
    to faktura, nie „Wyślij raport”."""

    row["settlement"] = settlement
    if not settlement or settlement.get("status") != "accepted":
        return
    if settlement.get("kind") == "estimate":
        # Przyjęty plan nie zamyka miesiąca: RCP faktyczne przychodzi po jego końcu.
        return
    if row["action"] == "send_report":
        row["action"] = "send_invoice"
        row["issue_invoice"] = True
        row["report_label"] = REPORT_LABELS["accepted"]
        row["invoice_label"] = "Faktura: wystaw i wyślij"
    ksef = (settlement.get("invoice") or {}).get("ksef")
    if ksef:
        # Faktura jest już w KSeF (E4): nic do wysłania; korekta idzie zadaniem.
        row["action"] = None
        row["issue_invoice"] = False
        row["invoice_label"] = ksef["label"]


async def upload_from_portal(
    db: AsyncSession,
    context: PortalContext,
    *,
    kind: str,
    year: int,
    month: int,
    content: bytes,
    file_name: Optional[str],
    today: date,
    now: datetime,
) -> Stored:
    if not valid_period(year, month, today=today):
        raise PortalError(BAD_PERIOD)
    return await store(
        db,
        contract_id=context.consultant.contract_id,
        kind=kind,
        year=year,
        month=month,
        content=content,
        file_name=file_name,
        channel="portal",
        now=now,
        sender_email=context.consultant.email,
    )


async def own_document(
    db: AsyncSession, context: PortalContext, document_id: int
) -> CpDocument:
    document = await db.get(CpDocument, document_id)
    if (
        document is None
        or document.contract_id is None
        or document.contract_id not in context.consultant.contract_ids
        # Plik od klienta albo koordynatora bywa zbiorczy: ten sam ma każda osoba.
        or not sent_by_consultant(document, context.consultant.email)
    ):
        raise PortalError(NOT_FOUND, status=404, code="not_found")
    return document


# ── Finanse ──────────────────────────────────────────────────────────────────


def staff_row(document: CpDocument) -> dict[str, Any]:
    return {
        **_doc_row(document),
        "contract_id": document.contract_id,
        "period_year": document.period_year,
        "period_month": document.period_month,
        "period_guessed": document.period_guessed,
        "sender_email": document.sender_email,
        "invoice_signal_at": document.invoice_signal_at.isoformat()
        if document.invoice_signal_at
        else None,
    }


async def sender_contracts(
    db: AsyncSession, document: CpDocument, *, today: date
) -> Optional[dict[str, Any]]:
    """Podpowiedź przy „Przypisz”: osoba nadawcy pliku bez kontraktu i jej
    działające kontrakty (klient, numer, okres, bez kwot).

    Faktura osoby u dwóch klientów czeka na Finanse bez kontraktu (od 26.11.2026,
    ``identity.invoice_waits``), a numer kontraktu trzeba było znaleźć gdzie indziej.
    Osoba z adresu nadawcy jak w czytniku poczty; nieznany adres albo dwie osoby pod
    nim = ``None`` (bez podpowiedzi, jak dotąd).
    """

    from app.models.candidate import Candidate
    from app.models.client import Client

    if document.contract_id is not None or not document.sender_email:
        return None
    ids = await identity.sender_contract_ids(db, document.sender_email, today=today)
    if not ids:
        return None
    people = set(
        (
            await db.scalars(select(Contract.candidate_id).where(Contract.id.in_(ids)))
        ).all()
    )
    if len(people) != 1 or None in people:
        return None
    person_id = next(iter(people))
    rows = (
        await db.execute(
            select(Contract, Client.display_name, Client.name)
            .outerjoin(Client, Client.id == Contract.client_id)
            .where(Contract.candidate_id == person_id)
            .order_by(Contract.start_date.desc().nulls_last(), Contract.id.desc())
        )
    ).all()
    contracts = [
        {
            "id": contract.id,
            "client": (shown or name or "").strip() or None,
            "start_date": contract.start_date.isoformat()
            if contract.start_date
            else None,
            "end_date": contract.end_date.isoformat() if contract.end_date else None,
        }
        for contract, shown, name in rows
        if identity.eligible(contract, today)
    ]
    if not contracts:
        return None
    person = await db.get(Candidate, person_id)
    full_name = " ".join(
        part.strip()
        for part in ((person.name, person.lastname) if person else ())
        if part and part.strip()
    )
    return {"name": full_name or None, "contracts": contracts}


async def _notify(
    db: AsyncSession, document: CpDocument, *, subject: str, text: str
) -> None:
    """Mail do konsultanta. Awaria nie cofa decyzji: stan i tak widać w portalu."""

    if document.contract_id is None:
        return
    contract = await db.get(Contract, document.contract_id)
    email = identity.normalize_email(contract.candidate_email if contract else None)
    if not email:
        return
    try:
        await portal_mail.send(
            db, contract_id=document.contract_id, to=email, subject=subject, text=text
        )
    except Exception as exc:  # noqa: BLE001 — mail to dodatek do decyzji
        logger.warning("consultant_portal_documents: mail (%s)", type(exc).__name__)


async def _for_decision(db: AsyncSession, document_id: int) -> CpDocument:
    document = await db.get(CpDocument, document_id)
    if document is None:
        raise PortalError(NOT_FOUND, status=404, code="not_found")
    return document


async def accept(
    db: AsyncSession, document_id: int, *, actor_id: int, now: datetime
) -> CpDocument:
    document = await _for_decision(db, document_id)
    if document.contract_id is None:
        raise PortalError(
            "Najpierw wskaż kontrakt nadawcy.", status=409, code="unmatched"
        )
    if document.status != "received":
        raise PortalError(ALREADY_DECIDED, status=409, code="decided")
    document.status = "accepted"
    document.decided_by = actor_id
    document.decided_at = now
    document.updated_at = now
    if document.kind == "report":
        document.invoice_signal_at = now
        await _notify(
            db,
            document,
            subject="Raport zaakceptowany: możesz wystawić fakturę",
            text=(
                f"Raport za {document.period_month:02d}.{document.period_year} jest "
                "zaakceptowany. Możesz wystawić fakturę i wysłać ją w strefie konsultanta "
                f"albo na adres rozliczeń:\n{portal_mail.portal_url()}"
            ),
        )
    return document


async def reject(
    db: AsyncSession, document_id: int, *, actor_id: int, reason: str, now: datetime
) -> CpDocument:
    document = await _for_decision(db, document_id)
    if document.status != "received":
        raise PortalError(ALREADY_DECIDED, status=409, code="decided")
    clean = reason.replace("\x00", "").strip()[:COMMENT_MAX]
    if not clean:
        raise PortalError("Napisz, co trzeba poprawić.")
    document.status = "rejected"
    document.reject_reason = clean
    document.decided_by = actor_id
    document.decided_at = now
    document.updated_at = now
    await _notify(
        db,
        document,
        subject="Dokument do poprawy",
        text=(
            f"Dokument za {document.period_month:02d}.{document.period_year} wymaga poprawy. "
            f"Szczegóły znajdziesz w strefie konsultanta:\n{portal_mail.portal_url()}"
        ),
    )
    return document


async def mark_paid(
    db: AsyncSession, document_id: int, *, actor_id: int, now: datetime
) -> CpDocument:
    document = await _for_decision(db, document_id)
    if document.kind != "invoice" or document.status != "accepted":
        raise PortalError(
            "Opłacona może być tylko przyjęta faktura.", status=409, code="not_accepted"
        )
    document.status = "paid"
    document.decided_by = actor_id
    document.updated_at = now
    return document


async def assign_contract(
    db: AsyncSession,
    document_id: int,
    *,
    contract_id: int,
    now: datetime,
    period: Optional[tuple[int, int]] = None,
) -> CpDocument:
    """Plik bez kontraktu trafia do kontraktu ręką Finansów.

    ``period`` (rok, miesiąc) poprawia miesiąc dokumentu (decyzje Artura
    z 26.11.2026): numer faktury niesie miesiąc wystawienia, a raport bez okresu
    w nazwie dostaje miesiąc zgadnięty z daty maila. Miesiąc taki jak dotąd niczego
    nie zmienia, także flagi „zgadnięty”."""

    document = await _for_decision(db, document_id)
    if document.contract_id is not None:
        raise PortalError("Dokument ma już kontrakt.", status=409, code="matched")
    if period == (document.period_year, document.period_month):
        period = None
    if period is not None and not valid_period(*period, today=business_today()):
        raise PortalError(BAD_PERIOD)
    if await db.get(Contract, contract_id) is None:
        raise PortalError("Nie ma takiego kontraktu.", status=404, code="no_contract")
    duplicate = await _same_file(
        db,
        contract_id=contract_id,
        kind=document.kind,
        digest=document.sha256,
        graph_message_id=None,
    )
    if duplicate is not None:
        raise PortalError(
            "Ten plik jest już w dokumentach kontraktu.", status=409, code="duplicate"
        )
    document.contract_id = contract_id
    if period is not None:
        document.period_year, document.period_month = period
        # Raport: wybrany ręcznie miesiąc nie udaje miesiąca z nazwy pliku, który
        # kontrole rozliczenia biorą za dowód (``settlements._named_month``, „RCP
        # za inny miesiąc”), więc liczy się jak okres nie z nazwy.
        document.period_guessed = document.kind == "report"
    document.updated_at = now
    # KEŚU albo RCP przypisane ręcznie liczy się tak samo jak przypisane przez czytnik.
    await _refresh_settlement(db, document)
    return document
