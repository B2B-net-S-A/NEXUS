"""VAT-UE(5) (K5b-3a): informacja podsumowująca z rejestru sprzedaży miesiąca.

Decyzja Artura z 15.11.2026: schemat VAT-UE(5) z crd.gov.pl w repo (wzór
2021/01/12/10293, wersja 2-0E — najnowsza na liście struktur e-Deklaracji),
NEXUS składa plik i sprawdza go schematem przed pobraniem. Schematy w
``vat_ue_schema/`` (pobrane 15.11.2026; adresy importów przepisane na pliki
obok, reszta bajt w bajt), więc walidacja nie sięga do sieci.

* **Z czego**: wiersze rejestru sprzedaży (K5a) z grup ``np_ue`` (usługi dla
  podatników z UE, art. 100 ust. 1 pkt 4 — sekcja usług, Grupa3) i ``0_wdt``
  (wewnątrzwspólnotowa dostawa towarów — Grupa1, bez transakcji trójstronnej).
  Okres = okres rejestru (obowiązek podatkowy), jak JPK_V7M.
* **Kwoty**: suma netto w PLN per kontrahent (kraj + numer VAT UE) i sekcja,
  w pełnych złotych (od 50 gr w górę) — formularz nie ma groszy.
* **Kontrahent**: numer VAT UE bez kodu kraju, kraj z prefiksu (Grecja = EL);
  bez numeru VAT UE albo z kraju spoza słownika sekcji = problem (blokuje plik).
* **Korekty** (przegląd K5b-3a): korekta faktury z tego samego miesiąca nettuje
  się z nią; korekta wcześniejszego okresu nie pomniejsza tego miesiąca — idzie
  na VAT-UEK za tamten okres (lista „do VAT-UEK”, nie blokuje pliku); korekta
  bez faktury pierwotnej w NEXUSIE blokuje plik.
* **Blokady**: listy rejestru, przy których JPK nie powstaje (stawki bez pola
  JPK, faktura z KSeF bez dokumentu, bufor), brak NIP-u, nazwy albo kodu urzędu
  w danych płatnika (K7a), nabywca bez numeru VAT UE i suma kontrahenta poniżej
  zera.
* VAT-UE(5) ma tylko złożenie (``CelZlozenia`` = 1); korekty składa się na
  VAT-UEK(5). WNT i call-off stock — NEXUS ich nie ewidencjonuje.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from lxml import etree
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.finance_ledger.costs import LedgerError
from app.services.hr.payroll_lists import parameters as payroll_parameters
from app.services.ledger import jpk, vat
from app.services.ledger.documents import Viewer
from app.services.ledger.settings import LedgerSettings

NS = "http://crd.gov.pl/wzor/2021/01/12/10293/"
ETD = "http://crd.gov.pl/xml/schematy/dziedzinowe/mf/2020/03/11/eD/DefinicjeTypy/"
SCHEMA_DIR = Path(__file__).with_name("vat_ue_schema")
SCHEMA = SCHEMA_DIR / "schemat.xsd"
_XSD = "{http://www.w3.org/2001/XMLSchema}"
#: Grupa rejestru sprzedaży → sekcja VAT-UE.
SECTIONS: dict[str, str] = {"0_wdt": "goods", "np_ue": "services"}
SECTION_LABELS: dict[str, str] = {
    "goods": "Wewnątrzwspólnotowa dostawa towarów",
    "services": "Usługi (art. 100 ust. 1 pkt 4)",
}
#: Typ kraju w schemacie dla sekcji (usługi bez XI — Irlandia Północna to VAT UE
#: tylko dla towarów).
SECTION_COUNTRY_TYPES: dict[str, str] = {
    "goods": "TKodKrajuUE",
    "services": "TKodKrajuUEUslugi",
}
_NUMBER = re.compile(r"^(\d|[A-Z]|\+|\*){1,12}$")
#: Kody ze słownika z 2021 r., które dziś nie są numerem VAT UE (po brexicie GB
#: zostało tylko dla korekt wcześniejszych okresów).
NOT_EU_NOW = frozenset({"GB"})
#: Kwota kontrahenta: ``TKwotaC`` z ``totalDigits`` 12.
AMOUNT_MAX = 10**12 - 1
NOTES: tuple[str, ...] = (
    "Korekta informacji za wcześniejszy okres (VAT-UEK) — jeszcze nie w NEXUSIE; "
    "przygotuj ją w Symfonii albo e-Deklaracjach.",
    "Wewnątrzwspólnotowe nabycia (WNT) i call-off stock — NEXUS ich nie ewidencjonuje.",
)


@dataclass
class Line:
    """Pozycja VAT-UE: kontrahent w sekcji z sumą netto (grosze PLN)."""

    section: str
    country: str
    number: str
    name: str
    grosze: int = 0
    documents: list[str] = field(default_factory=list)

    @property
    def amount(self) -> int:
        """Pełne złote (od 50 gr w górę, art. 63 OP — jak deklaracja)."""

        return jpk.zl(self.grosze)


@lru_cache(maxsize=1)
def country_codes() -> dict[str, frozenset[str]]:
    """Kody krajów sekcji ze słownika schematu (``KodyKrajowUE``)."""

    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    tree = etree.parse(str(SCHEMA_DIR / "KodyKrajowUE_v3-0E.xsd"), parser)
    codes: dict[str, frozenset[str]] = {}
    for node in tree.iter(f"{_XSD}simpleType"):
        values = {
            item.get("value")
            for item in node.iter(f"{_XSD}enumeration")
            if item.get("value")
        }
        codes[node.get("name") or ""] = frozenset(values)
    return {
        section: codes.get(type_name, frozenset())
        for section, type_name in SECTION_COUNTRY_TYPES.items()
    }


#: Rodzaje problemów, które nie blokują pliku (korekta na VAT-UEK).
NOT_BLOCKING = ("earlier",)


def blocking(problems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in problems if item.get("kind") not in NOT_BLOCKING]


def collect(data: dict[str, Any]) -> tuple[list[Line], list[dict[str, Any]]]:
    """Pozycje VAT-UE z rejestru sprzedaży i wiersze, których nie da się ująć
    (``kind``: ``counterparty``, ``negative``, ``unknown`` — blokują; ``earlier``
    — korekta wcześniejszego okresu do VAT-UEK)."""

    allowed = country_codes()
    period = f"{data['year']}-{data['month']:02d}"
    lines: dict[tuple[str, str, str], Line] = {}
    problems: list[dict[str, Any]] = []
    for row in data["sales"]:
        for group in row["groups"]:
            section = SECTIONS.get(group["key"])
            if section is None:
                continue
            if row.get("correction"):
                corrected = row.get("corrected_month")
                if corrected is None:
                    problems.append(
                        {
                            "number": row["number"],
                            "kind": "unknown",
                            "detail": "korekta bez faktury pierwotnej w NEXUSIE — nie "
                            "wiadomo, czy należy do tego miesiąca, czy na VAT-UEK",
                        }
                    )
                    continue
                if corrected != period:
                    year, month = corrected.split("-")
                    problems.append(
                        {
                            "number": row["number"],
                            "kind": "earlier",
                            "detail": f"korekta faktury z {month}.{year} — na VAT-UEK "
                            f"za {month}.{year}, nie w tym VAT-UE",
                        }
                    )
                    continue
            # Kraj z prefiksu numeru VAT UE, nie z kartoteki (XI pod krajem GB).
            raw = "".join(
                ch for ch in (row.get("tax_id") or "") if ch.isalnum()
            ).upper()
            prefix = raw[:2] if raw[:2].isalpha() else None
            code, number = jpk.counterparty(raw or None, prefix or row.get("country"))
            if not code or number == jpk.BRAK:
                problems.append(
                    {
                        "number": row["number"],
                        "kind": "counterparty",
                        "detail": "nabywca bez numeru VAT UE — VAT-UE wymaga numeru "
                        "z kodem kraju (kartoteka albo faktura w KSeF)",
                    }
                )
                continue
            if (
                code not in allowed[section]
                or code in NOT_EU_NOW
                or not _NUMBER.match(number)
            ):
                problems.append(
                    {
                        "number": row["number"],
                        "kind": "counterparty",
                        "detail": f"numer {code}{number} nie pasuje do VAT-UE "
                        f"({SECTION_LABELS[section].lower()})",
                    }
                )
                continue
            key = (section, code, number)
            line = lines.setdefault(
                key,
                Line(section, code, number, str(row.get("counterparty") or "")),
            )
            line.grosze += group["net"]
            line.documents.append(row["number"])
    out: list[Line] = []
    for line in lines.values():
        if line.amount < 0:
            problems.append(
                {
                    "number": ", ".join(line.documents[:5]),
                    "kind": "negative",
                    "detail": f"{line.country}{line.number}: suma miesiąca poniżej "
                    "zera — sprawdź faktury i korekty kontrahenta",
                }
            )
        elif line.amount > AMOUNT_MAX:
            problems.append(
                {
                    "number": ", ".join(line.documents[:5]),
                    "kind": "negative",
                    "detail": f"{line.country}{line.number}: kwota za duża dla VAT-UE",
                }
            )
        elif line.amount:
            out.append(line)
    out.sort(key=lambda item: (item.section, item.country, item.number))
    return out, problems


def _sub(parent: Any, tag: str, text: Any = None, ns: str = NS, **attrs: str) -> Any:
    node = etree.SubElement(parent, f"{{{ns}}}{tag}", attrs)
    if text is not None:
        node.text = str(text)
    return node


def build(
    lines: list[Line],
    *,
    company: payroll_parameters.Company,
    year: int,
    month: int,
) -> bytes:
    """XML VAT-UE(5) (złożenie) z pozycji miesiąca."""

    root = etree.Element(f"{{{NS}}}Deklaracja", nsmap={None: NS, "etd": ETD})
    head = _sub(root, "Naglowek")
    _sub(
        head,
        "KodFormularza",
        "VAT-UE",
        kodSystemowy="VAT-UE (5)",
        wersjaSchemy="2-0E",
    )
    _sub(head, "WariantFormularza", 5)
    _sub(head, "Rok", year)
    _sub(head, "Miesiac", month)
    _sub(head, "CelZlozenia", 1)
    _sub(head, "KodUrzedu", company.tax_office_code)
    subject = _sub(_sub(root, "Podmiot1", rola="Podatnik"), "OsobaNiefizyczna", ns=ETD)
    _sub(subject, "NIP", company.nip, ns=ETD)
    _sub(subject, "PelnaNazwa", jpk._clip(company.name, 240), ns=ETD)
    positions = _sub(root, "PozycjeSzczegolowe")
    for line in lines:
        if line.section == "goods":
            group = _sub(positions, "Grupa1")
            _sub(group, "P_Da", line.country)
            _sub(group, "P_Db", line.number)
            _sub(group, "P_Dc", line.amount)
            # 1 = pozycja nie dotyczy transakcji trójstronnych (dokumentacja XSD).
            _sub(group, "P_Dd", 1)
    for line in lines:
        if line.section == "services":
            group = _sub(positions, "Grupa3")
            _sub(group, "P_Ua", line.country)
            _sub(group, "P_Ub", line.number)
            _sub(group, "P_Uc", line.amount)
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


def _line_payload(line: Line) -> dict[str, Any]:
    return {
        "section": line.section,
        "section_label": SECTION_LABELS[line.section],
        "country": line.country,
        "number": line.number,
        "name": line.name,
        "amount": line.amount,
        "net": line.grosze,
        "documents": line.documents[:20],
        "documents_count": len(line.documents),
    }


async def _company(
    db: AsyncSession,
) -> tuple[payroll_parameters.Company, list[str]]:
    company = await payroll_parameters.load_company(db)
    missing = []
    if not company.nip:
        missing.append("NIP firmy (Płace → Parametry → Dane płatnika)")
    if not company.name:
        missing.append("nazwa firmy (Płace → Parametry → Dane płatnika)")
    if not company.tax_office_code:
        missing.append("kod urzędu skarbowego (Płace → Parametry → Dane płatnika)")
    return company, missing


async def _month(
    db: AsyncSession, viewer: Viewer, settings: LedgerSettings, year: int, month: int
) -> dict[str, Any]:
    data = await vat.registers(db, viewer, settings, year=year, month=month)
    lines, problems = collect(data)
    blockers = [
        f"{issue['label']}: {issue['count']}"
        for issue in data["issues"]
        if issue["kind"] in jpk.BLOCKING
    ]
    _, missing = await _company(db)
    return {
        "lines": lines,
        "problems": problems,
        "blockers": blockers,
        "missing": missing,
    }


async def overview(
    db: AsyncSession, viewer: Viewer, settings: LedgerSettings, *, year: int, month: int
) -> dict[str, Any]:
    """Pozycje VAT-UE miesiąca, problemy i czy plik da się pobrać."""

    found = await _month(db, viewer, settings, year, month)
    lines: list[Line] = found["lines"]
    ready = not (blocking(found["problems"]) or found["blockers"] or found["missing"])
    return {
        "year": year,
        "month": month,
        "lines": [_line_payload(line) for line in lines],
        "totals": {
            section: sum(line.amount for line in lines if line.section == section)
            for section in SECTION_LABELS
        },
        "problems": found["problems"],
        "blockers": found["blockers"],
        "missing": found["missing"],
        "can_download": ready and bool(lines),
        "notes": NOTES,
    }


async def file(
    db: AsyncSession, viewer: Viewer, settings: LedgerSettings, *, year: int, month: int
) -> tuple[str, bytes]:
    """Plik VAT-UE(5) miesiąca po walidacji schematem MF (422 z powodem)."""

    found = await _month(db, viewer, settings, year, month)
    reasons = (
        found["missing"]
        + found["blockers"]
        + [
            f"{item['number']}: {item['detail']}"
            for item in blocking(found["problems"])
        ]
    )
    if reasons:
        raise LedgerError(
            f"VAT-UE nie powstanie — {'; '.join(reasons[:5])}.", status=422
        )
    if not found["lines"]:
        raise LedgerError(
            "W tym miesiącu nie ma usług dla podatników z UE ani WDT — VAT-UE "
            "się nie składa.",
            status=422,
        )
    company, _ = await _company(db)
    content = build(found["lines"], company=company, year=year, month=month)
    errors = validate(content)
    if errors:
        raise LedgerError(
            f"Plik VAT-UE nie przechodzi schematu MF — {' | '.join(errors)}",
            status=422,
        )
    return f"VAT-UE_{year}-{month:02d}.xml", content
