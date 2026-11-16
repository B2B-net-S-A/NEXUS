"""VAT-UEK(5) (K5b-3c): korekta informacji podsumowującej VAT-UE.

Decyzja Artura z 15.11.2026: schemat VAT-UEK(5) z crd.gov.pl w repo (wzór
2021/01/26/10316, wersja 2-1E — najnowsza na liście struktur e-Deklaracji),
NEXUS składa plik korekty i sprawdza go schematem przed pobraniem. Schematy
w ``vat_uek_schema/`` (pobrane 16.11.2026; importy te same co w VAT-UE(5),
adresy przepisane na pliki obok, reszta bajt w bajt).

* **Okres korekty** = miesiąc faktury pierwotnej (VAT-UE, w którym ją ujęto).
  Korekta faktury z wcześniejszego okresu nie pomniejsza bieżącego VAT-UE
  (``vat_ue.collect``, problem ``earlier``) — idzie tutaj.
* **Pozycja** (MF): część „BYŁO” = dane z poprzednio złożonej informacji,
  „JEST” = dane prawidłowe, obie jako łączna wartość za okres (nie różnica).
  Sama „JEST” = kontrahent dopisany, sama „BYŁO” = kontrahent usunięty.
* **Skąd „BYŁO”** — decyzja Artura 16.11.2026 („per miesiąc korekty”): NEXUS
  nie przechowuje złożonych VAT-UE, więc VAT-UEK za okres M składa się z korekt
  wystawionych w miesiącu K. „BYŁO” = suma za M z rejestru M liczona dziś
  (z korektami z tego samego miesiąca, jak VAT-UE) + korekty faktur z M
  z miesięcy między M a K (zakładamy, że ich VAT-UEK złożono); „JEST” =
  „BYŁO” + korekty z K. Pozycje tylko dla kontrahentów z korektami z K,
  których kwota w pełnych złotych się zmienia.
* **Blokady pliku** (422 z powodem): nabywca bez numeru VAT UE, suma poniżej
  zera, faktura pierwotna bez dokumentu w księdze za M (VAT-UE poszedł spoza
  NEXUSA — korekta w Symfonii), listy rejestru K, przy których JPK nie
  powstaje, brak danych płatnika (K7a). Bez danych osób zespołu — pobiera
  każdy z modułem VAT, jak VAT-UE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from lxml import etree
from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.ledger import LedgerDocument
from app.services.finance_ledger.costs import LedgerError
from app.services.hr.payroll_lists import parameters as payroll_parameters
from app.services.ledger import jpk, vat, vat_ue
from app.services.ledger.documents import Viewer
from app.services.ledger.settings import LedgerSettings

NS = "http://crd.gov.pl/wzor/2021/01/26/10316/"
ETD = vat_ue.ETD
SCHEMA_DIR = Path(__file__).with_name("vat_uek_schema")
SCHEMA = SCHEMA_DIR / "schemat.xsd"
NOTES: tuple[str, ...] = (
    "„Było” = VAT-UE za ten okres z rejestru NEXUSA wraz z korektami z miesięcy "
    "wcześniejszych niż miesiąc korekty (ich VAT-UEK powinny być już złożone); "
    "„Jest” = po korektach z miesiąca korekty.",
)

Key = tuple[str, str, str]


def _first(year: int, month: int) -> date:
    return date(year, month, 1)


def _next(day: date) -> date:
    return date(day.year + (day.month == 12), day.month % 12 + 1, 1)


def _label(period: str) -> str:
    year, month = period.split("-")
    return f"{month}.{year}"


@dataclass
class Position:
    """Pozycja VAT-UEK: kontrahent w sekcji, „BYŁO” i „JEST” w groszach PLN."""

    section: str
    country: str
    number: str
    name: str
    before: int = 0
    after: int = 0
    documents: list[str] = field(default_factory=list)

    @property
    def before_amount(self) -> int:
        return jpk.zl(self.before)

    @property
    def after_amount(self) -> int:
        return jpk.zl(self.after)


def _corrections(
    rows: Iterable[dict[str, Any]], period: str
) -> tuple[dict[Key, tuple[str, int, list[str]]], list[dict[str, Any]]]:
    """Korekty faktur z ``period`` w wierszach rejestru sprzedaży: suma netto
    per kontrahent (nazwa, grosze, numery dokumentów) i problemy nabywcy."""

    found: dict[Key, tuple[str, int, list[str]]] = {}
    problems: list[dict[str, Any]] = []
    for row in rows:
        if not row.get("correction") or row.get("corrected_month") != period:
            continue
        for group in row["groups"]:
            section = vat_ue.SECTIONS.get(group["key"])
            if section is None:
                continue
            party, problem = vat_ue.resolve(row, section)
            if party is None:
                problems.append(problem)
                continue
            key = (section, *party)
            name, total, numbers = found.get(
                key, (str(row.get("counterparty") or ""), 0, [])
            )
            found[key] = (name, total + group["net"], [*numbers, row["number"]])
    return found, problems


def combine(
    base: dict[Key, vat_ue.Line],
    earlier: Iterable[dict[str, Any]],
    current: Iterable[dict[str, Any]],
    *,
    period: str,
) -> tuple[list[Position], list[dict[str, Any]]]:
    """Pozycje VAT-UEK za ``period`` z korekt miesiąca K (``current``).

    ``base`` — sumy VAT-UE za okres (``vat_ue.gather`` rejestru tego okresu),
    ``earlier`` / ``current`` — wiersze rejestrów sprzedaży miesięcy między
    okresem a K i samego K; liczą się tylko korekty faktur z ``period``."""

    before_found, problems = _corrections(earlier, period)
    current_found, current_problems = _corrections(current, period)
    problems += current_problems
    out: list[Position] = []
    for key, (name, delta, numbers) in current_found.items():
        line = base.get(key)
        before = (line.grosze if line else 0) + before_found.get(key, ("", 0, []))[1]
        position = Position(
            *key,
            name=(line.name if line and line.name else name),
            before=before,
            after=before + delta,
            documents=numbers,
        )
        label = f"{position.country}{position.number}"
        if position.before_amount < 0 or position.after_amount < 0:
            problems.append(
                {
                    "number": ", ".join(numbers[:5]),
                    "kind": "negative",
                    "detail": f"{label}: suma okresu poniżej zera — sprawdź faktury "
                    "i korekty kontrahenta",
                }
            )
        elif max(position.before_amount, position.after_amount) > vat_ue.AMOUNT_MAX:
            problems.append(
                {
                    "number": ", ".join(numbers[:5]),
                    "kind": "negative",
                    "detail": f"{label}: kwota za duża dla VAT-UEK",
                }
            )
        elif position.before_amount != position.after_amount:
            out.append(position)
    out.sort(key=lambda item: (item.section, item.country, item.number))
    return out, problems


def _sub(parent: Any, tag: str, text: Any = None, ns: str = NS, **attrs: str) -> Any:
    node = etree.SubElement(parent, f"{{{ns}}}{tag}", attrs)
    if text is not None:
        node.text = str(text)
    return node


#: Sekcja → (element grupy, prefiks pól BYŁO, prefiks pól JEST, z polem
#: transakcji trójstronnej).
GROUPS: dict[str, tuple[str, str, str, bool]] = {
    "goods": ("Grupa1", "P_DB", "P_DJ", True),
    "services": ("Grupa3", "P_UB", "P_UJ", False),
}


def build(
    positions: list[Position],
    *,
    company: payroll_parameters.Company,
    year: int,
    month: int,
) -> bytes:
    """XML VAT-UEK(5) za okres ``year``/``month``."""

    root = etree.Element(f"{{{NS}}}Deklaracja", nsmap={None: NS, "etd": ETD})
    head = _sub(root, "Naglowek")
    _sub(
        head,
        "KodFormularza",
        "VAT-UEK",
        kodSystemowy="VATUEK (5)",
        wersjaSchemy="2-1E",
    )
    _sub(head, "WariantFormularza", 5)
    _sub(head, "Rok", year)
    _sub(head, "Miesiac", month)
    _sub(head, "CelZlozenia", 1)
    _sub(head, "KodUrzedu", company.tax_office_code)
    subject = _sub(_sub(root, "Podmiot1", rola="Podatnik"), "OsobaNiefizyczna", ns=ETD)
    _sub(subject, "NIP", company.nip, ns=ETD)
    _sub(subject, "PelnaNazwa", jpk._clip(company.name, 240), ns=ETD)
    items = _sub(root, "PozycjeSzczegolowe")
    # Kolejność XSD: wszystkie Grupa1 (towary), potem Grupa3 (usługi).
    for section, (element, was, now, triangular) in GROUPS.items():
        for position in positions:
            if position.section != section:
                continue
            group = _sub(items, element)
            for prefix, amount in (
                (was, position.before_amount),
                (now, position.after_amount),
            ):
                # Zero = kontrahenta nie było (sama „JEST”) albo znika (sama „BYŁO”).
                if not amount:
                    continue
                _sub(group, f"{prefix}a", position.country)
                _sub(group, f"{prefix}b", position.number)
                _sub(group, f"{prefix}c", amount)
                if triangular:
                    # 1 = pozycja nie dotyczy transakcji trójstronnych.
                    _sub(group, f"{prefix}d", 1)
    _sub(root, "Pouczenie", 1)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


@lru_cache(maxsize=1)
def _schema() -> Any:
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    return etree.XMLSchema(etree.parse(str(SCHEMA), parser))


def validate(content: bytes) -> list[str]:
    """Błędy schematu MF (pierwsze kilka); pusta lista = plik poprawny."""

    schema = _schema()
    document = etree.fromstring(
        content, etree.XMLParser(resolve_entities=False, no_network=True)
    )
    if schema.validate(document):
        return []
    return [
        f"wiersz {error.line}: {error.message}"
        for error in list(schema.error_log)[: jpk.ERRORS_SHOWN]
    ]


def _position_payload(position: Position) -> dict[str, Any]:
    return {
        "section": position.section,
        "section_label": vat_ue.SECTION_LABELS[position.section],
        "country": position.country,
        "number": position.number,
        "name": position.name,
        # None = kontrahenta nie było w informacji / po korekcie znika.
        "before": position.before_amount or None,
        "after": position.after_amount or None,
        "documents": position.documents[:20],
        "documents_count": len(position.documents),
    }


def _period_filter(query: Any, viewer: Viewer) -> Any:
    query = query.where(
        LedgerDocument.source_type == vat.SALES_SOURCE,
        LedgerDocument.status == "approved",
        LedgerDocument.reversed_by_id.is_(None),
        LedgerDocument.reverses_id.is_(None),
    )
    if not viewer.payroll:
        query = query.where(LedgerDocument.sensitivity.is_(None))
    return query


async def _correction_months(
    db: AsyncSession, viewer: Viewer, start: date, end: date, until: date
) -> list[str]:
    """Miesiące (``RRRR-MM``) po okresie [start, end) do ``until`` włącznie,
    w których księga ma zatwierdzone korekty faktur z tego okresu."""

    originals = select(ClientSalesInvoice.id).where(
        func.coalesce(ClientSalesInvoice.sale_date, ClientSalesInvoice.issue_date)
        >= start,
        func.coalesce(ClientSalesInvoice.sale_date, ClientSalesInvoice.issue_date)
        < end,
    )
    corrections = select(cast(ClientSalesInvoice.id, String)).where(
        ClientSalesInvoice.invoice_kind == "correction",
        ClientSalesInvoice.corrects_invoice_id.in_(originals),
    )
    query = _period_filter(select(LedgerDocument.op_date).distinct(), viewer).where(
        LedgerDocument.source_id.in_(corrections),
        LedgerDocument.op_date >= end,
        LedgerDocument.op_date < _next(until),
    )
    days = (await db.scalars(query)).all()
    return sorted({f"{day.year}-{day.month:02d}" for day in days})


async def _outside_books(
    db: AsyncSession, viewer: Viewer, document_ids: list[int], start: date, end: date
) -> dict[int, dict[str, Any]]:
    """Korekty z K (id dokumentu → problem), których faktura pierwotna nie ma dokumentu w księdze za
    okres — ich VAT-UE poszedł spoza NEXUSA i „BYŁO” byłoby zgadywaniem."""

    if not document_ids:
        return {}
    rows = (
        await db.execute(
            select(
                LedgerDocument.id,
                LedgerDocument.number,
                ClientSalesInvoice.corrects_invoice_id,
            )
            .join(
                ClientSalesInvoice,
                cast(ClientSalesInvoice.id, String) == LedgerDocument.source_id,
            )
            .where(LedgerDocument.id.in_(document_ids))
        )
    ).all()
    originals = {item for _, _, item in rows if item}
    booked: set[str] = set()
    if originals:
        booked = set(
            (
                await db.scalars(
                    _period_filter(select(LedgerDocument.source_id), viewer).where(
                        LedgerDocument.source_id.in_([str(item) for item in originals]),
                        LedgerDocument.op_date >= start,
                        LedgerDocument.op_date < end,
                    )
                )
            ).all()
        )
    return {
        doc_id: {
            "number": number,
            "kind": "outside",
            "detail": "faktura pierwotna nie ma dokumentu w księdze NEXUSA za ten "
            "okres — VAT-UE poszedł spoza NEXUSA, korektę przygotuj w Symfonii",
        }
        for doc_id, number, original in rows
        if original and str(original) not in booked
    }


async def _gather(
    db: AsyncSession,
    viewer: Viewer,
    settings: LedgerSettings,
    *,
    year: int,
    month: int,
    issued_year: int,
    issued_month: int,
) -> dict[str, Any]:
    start = _first(year, month)
    end = _next(start)
    issued = _first(issued_year, issued_month)
    if issued < end:
        raise LedgerError(
            "Miesiąc korekt musi być późniejszy niż okres VAT-UE, który korygujesz.",
            status=422,
        )
    period = f"{year}-{month:02d}"
    issued_period = f"{issued_year}-{issued_month:02d}"
    base, _ = vat_ue.gather(
        await vat.registers(db, viewer, settings, year=year, month=month)
    )
    months = await _correction_months(db, viewer, start, end, issued)
    earlier_rows: list[dict[str, Any]] = []
    for item in months:
        if item == issued_period:
            continue
        other_year, other_month = (int(part) for part in item.split("-"))
        data = await vat.registers(
            db, viewer, settings, year=other_year, month=other_month
        )
        earlier_rows += data["sales"]
    current_rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    if issued_period in months:
        data = await vat.registers(
            db, viewer, settings, year=issued_year, month=issued_month
        )
        current_rows = data["sales"]
        blockers = [
            f"{issue['label']} ({_label(issued_period)}): {issue['count']}"
            for issue in data["issues"]
            if issue["kind"] in jpk.BLOCKING
        ]
    current_ids = [
        row["document_id"]
        for row in current_rows
        if row.get("correction")
        and row.get("corrected_month") == period
        and any(group["key"] in vat_ue.SECTIONS for group in row["groups"])
    ]
    outside = await _outside_books(db, viewer, current_ids, start, end)
    # Bez faktury pierwotnej w księdze „BYŁO” byłoby zerem — sam problem
    # „outside”, bez pozycji i bez „poniżej zera” z tej samej korekty.
    positions, problems = combine(
        base,
        earlier_rows,
        [row for row in current_rows if row["document_id"] not in outside],
        period=period,
    )
    problems = list(outside.values()) + problems
    company, missing = await vat_ue._company(db)
    return {
        "positions": positions,
        "problems": problems,
        "blockers": blockers,
        "missing": missing,
        "company": company,
        "earlier": [item for item in months if item != issued_period],
        "corrections": len(current_ids),
    }


async def overview(
    db: AsyncSession,
    viewer: Viewer,
    settings: LedgerSettings,
    *,
    year: int,
    month: int,
    issued_year: int,
    issued_month: int,
) -> dict[str, Any]:
    """Pozycje VAT-UEK za okres z korekt wystawionych w miesiącu korekt."""

    found = await _gather(
        db,
        viewer,
        settings,
        year=year,
        month=month,
        issued_year=issued_year,
        issued_month=issued_month,
    )
    positions: list[Position] = found["positions"]
    ready = not (found["problems"] or found["blockers"] or found["missing"])
    return {
        "year": year,
        "month": month,
        "issued_year": issued_year,
        "issued_month": issued_month,
        "lines": [_position_payload(item) for item in positions],
        "corrections": found["corrections"],
        "earlier_months": found["earlier"],
        "problems": found["problems"],
        "blockers": found["blockers"],
        "missing": found["missing"],
        "can_download": ready and bool(positions),
        "notes": NOTES,
    }


async def file(
    db: AsyncSession,
    viewer: Viewer,
    settings: LedgerSettings,
    *,
    year: int,
    month: int,
    issued_year: int,
    issued_month: int,
) -> tuple[str, bytes]:
    """Plik VAT-UEK(5) po walidacji schematem MF (422 z powodem)."""

    found = await _gather(
        db,
        viewer,
        settings,
        year=year,
        month=month,
        issued_year=issued_year,
        issued_month=issued_month,
    )
    period = f"{month:02d}.{year}"
    issued = f"{issued_month:02d}.{issued_year}"
    if not found["corrections"]:
        raise LedgerError(
            f"W {issued} księga nie ma korekt faktur z {period} (usługi dla "
            "podatników z UE, WDT) — VAT-UEK za ten okres się nie składa.",
            status=422,
        )
    reasons = (
        found["missing"]
        + found["blockers"]
        + [f"{item['number']}: {item['detail']}" for item in found["problems"]]
    )
    if reasons:
        raise LedgerError(
            f"VAT-UEK nie powstanie — {'; '.join(reasons[:5])}.", status=422
        )
    if not found["positions"]:
        raise LedgerError(
            f"Korekty z {issued} nie zmieniają kwot VAT-UE za {period} w pełnych "
            "złotych — VAT-UEK się nie składa.",
            status=422,
        )
    content = build(
        found["positions"], company=found["company"], year=year, month=month
    )
    errors = validate(content)
    if errors:
        raise LedgerError(
            f"Plik VAT-UEK nie przechodzi schematu MF — {' | '.join(errors)}",
            status=422,
        )
    return (
        f"VAT-UEK_{year}-{month:02d}_korekty_{issued_year}-{issued_month:02d}.xml",
        content,
    )
