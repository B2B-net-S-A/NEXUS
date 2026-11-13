"""Podpisane dokumenty od klienta: arkusz zbiorczy i protokół odbioru (roadmapa E6).

Arkusze Velo przekazują koordynatorzy po naszej stronie, a jeden przysyła sam
bank, więc nadawca maila nic nie mówi (odpowiedź rozliczeń z 12.11.2026:
„niezależnie, kto wrzuci na rozliczenia@, rozpoznaj i przypisz”). Rozpoznajemy
dokument po treści:

* arkusz zbiorczy — nagłówki „Nazwisko i imię … Zlecenie od … Liczba MD” (nasz
  wzór) albo „Nazwisko Imię … Okres od … MD.” (wzór banku); wiersz osoby to
  linia z datą i liczbą MD na końcu;
* protokół odbioru — „Protokół odbioru” i „Okres rozliczeniowy: od … do …”.

Osoby dopasowujemy po imieniu i nazwisku z kontraktów klientów, którzy mają
regułę ``cl.client_document`` na ten rodzaj dokumentu. Liczy się tylko PDF
z ważnym podpisem elektronicznym: arkusz podpisuje klient, protokół najpierw
my, potem klient (dwa podpisy). Wydruk bez podpisu nic nie zmienia.

Wynik zapisujemy przy rozliczeniu osoby w ``checks`` jako wpis ``signed``
(dokument, rodzaj, podpisujący, data, MD z arkusza); przeliczenie rozliczenia
go zachowuje. Rozpoznany plik odpina się od kontraktu i dostaje stan
„przyjęty”, żeby nie wisiał jako karta „do przypisania” ani nie udawał RCP.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_settlement import ClientSettlementRuleSet
from app.models.consultant_portal import CpDocument
from app.services.client_settlements import mail_text
from app.services.client_settlements.rcp_bnp import signatures
from app.services.client_settlements.rcp_checks import name_tokens

logger = logging.getLogger(__name__)

PDF = "application/pdf"
SHEET, PROTOCOL = "sheet", "protocol"
SIGNED_KEY = "signed"
#: ``per`` w regule ``cl.client_document``: na kogo jest dokument.
PER_SIGNER = {"podpisujący", "podpisujacy", "podpisującego", "signer", "arkusz"}
PER_MONTH = {
    "cały miesiąc",
    "caly miesiac",
    "miesiąc",
    "miesiac",
    "month",
    "wszystkie osoby",
}
MAX_PAGES = 6

_DATE = re.compile(
    r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](20\d{2})(?!\d)|(?<!\d)(20\d{2})-(\d{2})-(\d{2})(?!\d)"
)
_MD_TAIL = re.compile(r"(\d{1,2}(?:[.,]\d{1,3})?)\s*$")
_PERIOD = re.compile(
    r"okres\s+rozliczeniowy\s*:?\s*od\s+(\d{1,2})[./-](\d{1,2})[./-](20\d{2})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SheetRow:
    tokens: frozenset[str]
    md: Optional[Decimal]


@dataclass(frozen=True)
class Recognized:
    kind: str
    month: Optional[str]
    rows: tuple[SheetRow, ...]
    signers: tuple[str, ...]
    signed_at: Optional[datetime]
    #: Arkusz: podpis klienta. Protokół: podpis spółki i klienta.
    complete: bool


def _dates(line: str) -> list[date]:
    out = []
    for m in _DATE.finditer(line):
        try:
            if m.group(1):
                out.append(date(int(m.group(3)), int(m.group(2)), int(m.group(1))))
            else:
                out.append(date(int(m.group(4)), int(m.group(5)), int(m.group(6))))
        except ValueError:
            continue
    return out


def _folded(text: str) -> str:
    """Małe litery bez polskich znaków: PDF bywa zapisany bez nich („imie”)."""

    raw = text.lower().replace("ł", "l")
    raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    return " ".join(raw.split())


def kind_of(text: str) -> Optional[str]:
    lowered = _folded(text)
    if "protokol odbioru" in lowered and "okres rozliczeniowy" in lowered:
        return PROTOCOL
    sheet_header = ("nazwisko i imie" in lowered or "nazwisko imie" in lowered) and (
        "zlecenie od" in lowered or "okres od" in lowered
    )
    if sheet_header and ("liczba md" in lowered or "md." in lowered):
        return SHEET
    return None


def read_text(text: str) -> Optional[tuple[str, Optional[str], tuple[SheetRow, ...]]]:
    """Tekst PDF → (rodzaj, miesiąc, wiersze osób). Wydzielone dla testów."""

    kind = kind_of(text)
    if kind is None:
        return None
    rows: list[SheetRow] = []
    months: list[str] = []
    if kind == PROTOCOL:
        period = _PERIOD.search(text)
        if period:
            months.append(f"{period.group(3)}-{int(period.group(2)):02d}")
    for line in text.splitlines():
        found = _dates(line)
        if kind == SHEET:
            if not found or _folded(line).startswith("suma"):
                continue
            months.extend(f"{d.year}-{d.month:02d}" for d in found)
            tail = _MD_TAIL.search(line)
            md = None
            if tail:
                try:
                    md = Decimal(tail.group(1).replace(",", "."))
                except InvalidOperation:
                    md = None
            head = _DATE.split(line)[0]
            rows.append(SheetRow(frozenset(name_tokens(head)), md))
        elif re.search(r"\d+/20\d{2}", line):
            # Wiersz protokołu: numer zamówienia „NNNN/RRRR” i kwoty.
            rows.append(SheetRow(frozenset(name_tokens(line)), None))
    month = max(set(months), key=months.count) if months else None
    return kind, month, tuple(rows)


def _pdf_text(content: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages[:MAX_PAGES])


def recognize_pdf(content: bytes) -> Optional[Recognized]:
    try:
        text = _pdf_text(content)
    except Exception as exc:  # noqa: BLE001 — uszkodzony PDF nie blokuje przyjęcia
        logger.info("signoffs: PDF nieczytelny (%s)", type(exc).__name__)
        return None
    found = read_text(text)
    if found is None:
        return None
    kind, month, rows = found
    signed = [s for s in signatures(content) if s.intact]
    signed_at = max((s.signed_at for s in signed if s.signed_at), default=None)
    return Recognized(
        kind=kind,
        month=month,
        rows=rows,
        signers=tuple(s.signer or "" for s in signed),
        signed_at=signed_at,
        complete=len(signed) >= (2 if kind == PROTOCOL else 1),
    )


def recognize(content: bytes, mime: str) -> Optional[Recognized]:
    """PDF albo mail z PDF-em w załączniku (przekazany mail od klienta)."""

    if mime == PDF:
        return recognize_pdf(content)
    if mime in mail_text.MAIL_MIMES:
        mail = mail_text.read(content, mime)
        for _name, data in mail.attachments if mail else []:
            if data.startswith(b"%PDF"):
                found = recognize_pdf(data)
                if found is not None:
                    return found
    return None


def marker(checks: Optional[list[Any]]) -> Optional[dict[str, Any]]:
    for item in checks or []:
        if isinstance(item, dict) and isinstance(item.get(SIGNED_KEY), dict):
            return item[SIGNED_KEY]
    return None


def with_marker(checks: list[Any], value: Optional[dict[str, Any]]) -> list[Any]:
    kept = [c for c in checks if not (isinstance(c, dict) and SIGNED_KEY in c)]
    return [*kept, {SIGNED_KEY: value}] if value else kept


def document_rule(rules: dict[str, dict[str, Any]], month: str) -> Optional[str]:
    """Rodzaj dokumentu klienta z reguły ``cl.client_document`` na ten miesiąc."""

    rule = rules["cl.client_document"]
    if rule["level"] == "off":
        return None
    per = str(rule["params"].get("per") or "").strip().lower()
    start = str(rule["params"].get("from") or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}", start) and month < start:
        return None
    if per in PER_SIGNER:
        return SHEET
    if per in PER_MONTH:
        return PROTOCOL
    return None


async def _clients_with(db: AsyncSession, kind: str, month: str) -> list[int]:
    from sqlalchemy import select

    from app.services.client_settlements import service

    ids = (await db.scalars(select(ClientSettlementRuleSet.client_id).distinct())).all()
    out = []
    for client_id in ids:
        rules = await service.rules_for(db, client_id, month)
        if document_rule(rules, month) == kind:
            out.append(client_id)
    return out


async def apply(
    db: AsyncSession, document: CpDocument, *, now: datetime
) -> Optional[int]:
    """Rozpoznaje podpisany dokument i przypisuje go osobom; liczba osób albo ``None``."""

    from app.services.client_settlements import service
    from app.services.consultant_portal import documents as portal_documents

    if document.mime != PDF and document.mime not in mail_text.MAIL_MIMES:
        return None
    try:
        content = portal_documents.path_for(document.file_path).read_bytes()
    except OSError:
        return None
    found = await asyncio.to_thread(recognize, content, document.mime)
    if found is None or not found.signers:
        return None
    month = found.month or f"{document.period_year}-{document.period_month:02d}"
    matched: list[tuple[int, Optional[Decimal]]] = []
    for client_id in await _clients_with(db, found.kind, month):
        people = await service._people(db, client_id, month)
        hits = []
        for person in people:
            tokens = name_tokens(person.name)
            row = next((r for r in found.rows if tokens and tokens <= r.tokens), None)
            if row is not None:
                hits.append((person.contract.id, row.md))
        if hits and found.kind == PROTOCOL:
            # Jeden protokół na wszystkie osoby miesiąca; nazwiska w PDF łamią się
            # na dwie linie, więc wystarczy, że rozpoznamy kogokolwiek z klienta.
            with_settlement = await service.contracts_with_settlement(
                db, client_id, month
            )
            hits = [
                (p.contract.id, None)
                for p in people
                if p.contract.id in with_settlement
            ]
        matched.extend(hits)
    if not matched:
        return None
    signer = ", ".join(s for s in found.signers if s) or None
    value = {
        "kind": found.kind,
        "document_id": document.id,
        "signer": signer,
        "signed_at": found.signed_at.isoformat() if found.signed_at else None,
        "complete": found.complete,
    }
    for contract_id, md in matched:
        s = await service._get_or_create(db, contract_id, month, None)
        s.checks = with_marker(
            list(s.checks or []), {**value, "md": None if md is None else str(md)}
        )
        if s.md_regular is None and md is not None and s.md_source != "manual":
            # Osoba bez Time Sheet (arkusz przysyła sam bank): MD z arkusza.
            s.md_regular = md
            s.md_source = "rcp"
        if s.status != "accepted":
            await service.recompute_and_store(db, s)
    document.contract_id = None
    if document.status == "received":
        document.status = "accepted"
        document.decided_at = now
    document.updated_at = now
    return len(matched)


def signed_state(checks: Optional[list[Any]], kind: str) -> Optional[dict[str, Any]]:
    found = marker(checks)
    return found if found and found.get("kind") == kind else None


def is_complete(checks: Optional[list[Any]], kind: str) -> bool:
    found = signed_state(checks, kind)
    return bool(found and found.get("complete"))
