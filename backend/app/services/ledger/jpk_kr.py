"""Roczny plik JPK_KR_PD(1) z księgi NEXUSA (K8c). NEXUS niczego nie wysyła.

Schemat MF JPK_KR_PD(1) v1-1 (wzór 2024/09/04/09041) w ``jpk_kr_schema/``
(pobrany z gov.pl 16.11.2026; importy z crd.gov.pl — struktury danych v10-0E
i kody urzędów v8-0E — pobrane 16.11.2026 za zgodą Artura, adresy importów
przepisane na pliki obok, reszta bajt w bajt). Każde pobranie sprawdza plik
tym schematem, bez sieci.

Zasady wypełniania (broszura MF i pytania i odpowiedzi JPK_PD, 16.11.2026):

* **ZOiS7** (jednostki pozostałe): każde konto z zapisem w roku (także samo BO)
  i każde konto nadrzędne takich kont (pyt. 44, 141, 142); ``S_3`` = konto
  nadrzędne o jeden poziom wyżej, konto syntetyczne = samo siebie (pyt. 5, 13).
  Kwoty w PLN. Konto ostatecznego zapisu: saldo jednostronne; konto nadrzędne:
  sumy kont pod nim pole po polu (także salda — Wn i Ma osobno).
* **Znaczniki**: ``S_12_1`` = znacznik konta z K8a (``markers``), ``S_12_2`` =
  drugi znacznik pary ``KOD_Wn/KOD_Ma`` (MF: najwyżej dwa znaczniki bilansu
  i RZiS, pyt. 23, 129). Konta 5 dostają znaczniki wariantu kalkulacyjnego
  (pyt. 108, 128) — wpisuje je księgowa; 490 i pozabilansowe 9 bez wpisu = „INNE”
  (pyt. 61, 143). Konto nadrzędne = wspólny znacznik kont pod nim, inaczej „INNE”
  (pyt. 147). Bez ``S_12_3`` — CIT estoński nie ma znaczników PD (pyt. 114).
* **Dziennik**: dowód raz (pyt. 95), ``D_1`` = numer pozycji dziennika NEXUSA
  (ciągły w roku), ``D_2`` = „Dziennik Księga Główna” (pyt. 85), ``D_3`` =
  kontrahent z numerem podatkowym (bez list płac — pracownik nie jest
  kontrahentem, pyt. 123), ``D_12`` = numer KSeF. ``KontoZapis`` = pozycje
  dekretu, numer kolejny w pliku, Wn albo Ma, kwota w walucie dla pozycji
  walutowych. Storno czerwone = kwoty z minusem.
* **Kontrahent**: tylko z nadanym numerem podatkowym (pyt. 111, 146); ``T_1`` =
  id kartoteki NEXUSA, ``T_2`` = kraj nadania (także PL), ``T_3`` = numer jak
  na fakturze — VAT UE z prefiksem kraju (pyt. 104, aktualizacja 4.11.2026).
* **CIT estoński**: ``Znacznik_EST`` = 1 i węzeł RPD z zerami (pyt. 114).
  Spółka na zasadach ogólnych = plik się nie składa (NEXUS nie liczy RPD).

Plik zawiera dokumenty płacowe (D2) — pobiera go osoba z Płacami albo
administrator. Korekta = cały plik od nowa z ``CelZlozenia`` 2 (pyt. 139).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

from lxml import etree
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance_ledger import FinanceCounterparty
from app.models.finance_posting import FinanceAccount
from app.models.ledger import LedgerDocument, LedgerLine, LedgerPeriod, LedgerYear
from app.models.user import User
from app.services.finance_ledger.costs import LedgerError
from app.services.hr.payroll_lists import parameters as payroll_parameters
from app.services.ledger import engine, markers
from app.services.ledger.documents import Viewer
from app.services.ledger.jpk import _NOT_XML, KSEF, money
from app.services.ledger.settings import (
    JPK_KR_ADDRESS_FIELDS,
    JpkKrSettings,
    LedgerSettings,
)

NS = "http://jpk.mf.gov.pl/wzor/2024/09/04/09041/"
ETD = "http://crd.gov.pl/xml/schematy/dziedzinowe/mf/2022/01/05/eD/DefinicjeTypy/"
SCHEMA_DIR = Path(__file__).with_name("jpk_kr_schema")
SCHEMA = SCHEMA_DIR / "schemat.xsd"
COUNTRIES = SCHEMA_DIR / "KodyKrajow_v10-0E.xsd"
JOURNAL = "Dziennik Księga Główna"
OTHER = "INNE"
CURRENCY = "PLN"
ERRORS_SHOWN = 5
LISTED_MAX = 200
TEXT_MAX = 256
LONG_TEXT_MAX = 512
NAME_MAX = 240
#: Typ ``etd:TData``: daty do 2050-12-31 (testy na bazie losują lata dalej).
SCHEMA_LAST_YEAR = 2050
#: Numery podatkowe, które MF traktuje jako „nadany NIP” kontrahenta (PESEL nie).
TAX_ID_TYPES = ("nip", "vat_eu", "other")
#: Kody spoza ISO w numerach VAT UE i kartotece → kraj ISO (słownik ``TKodKraju``).
ISO_ALIASES = {"EL": "GR", "XI": "GB", "UK": "GB"}
ONLY_PAYROLL = (
    "JPK_KR_PD zawiera dokumenty płacowe — pobiera go osoba z Płacami albo "
    "administrator."
)
_WARSAW = ZoneInfo("Europe/Warsaw")

Pair = markers.Pair


# ── Dane wejściowe (czyste, bez bazy) ────────────────────────────────────────


@dataclass(frozen=True)
class Line:
    side: str
    account: str
    amount: int
    description: str = ""
    currency: str = CURRENCY
    amount_cur: Optional[int] = None


@dataclass(frozen=True)
class Doc:
    journal_no: int
    doc_type: str
    number: str
    op_date: date
    doc_date: date
    booked_on: date
    author: str
    description: str
    lines: tuple[Line, ...]
    counterparty_id: Optional[int] = None
    ksef_number: Optional[str] = None


@dataclass(frozen=True)
class Party:
    id: int
    id_type: Optional[str]
    id_value: Optional[str]
    country: Optional[str]


@dataclass
class Sums:
    """Kwoty konta w roku (grosze): BO Wn/Ma, obroty Wn/Ma bez BO."""

    bo_debit: int = 0
    bo_credit: int = 0
    debit: int = 0
    credit: int = 0

    @property
    def balance(self) -> int:
        return self.bo_debit - self.bo_credit + self.debit - self.credit


@dataclass
class Row:
    """Wiersz ZOiS: konto, nazwa, konto nadrzędne, kwoty i znaczniki."""

    account: str
    name: str
    parent: str
    bo_debit: int = 0
    bo_credit: int = 0
    debit: int = 0
    credit: int = 0
    balance_debit: int = 0
    balance_credit: int = 0
    pair: Optional[Pair] = None
    source: str = markers.SOURCE_NONE
    leaf: bool = True
    children_pairs: set[Pair] = field(default_factory=set)


# ── Znaczniki i konta ────────────────────────────────────────────────────────


def parent_of(account: str) -> str:
    """Konto o poziom wyżej (``403-1-1`` → ``403-1``); syntetyczne = samo."""

    parts = account.split("-")
    return "-".join(parts[:-1]) if len(parts) > 1 else account


def ancestors(account: str) -> list[str]:
    return markers.candidates(account)[1:]


def account_marker(
    account: str, own: Mapping[str, Optional[str]]
) -> tuple[Optional[Pair], str]:
    """Znacznik konta ostatecznego zapisu w JPK (inaczej niż w RZiS porównawczym:
    konta 5, 490 i 9 też go potrzebują — MF, pytania 108, 61, 143)."""

    for index, candidate in enumerate(markers.candidates(account)):
        pair = markers.parse(own.get(candidate))
        if pair is not None:
            return pair, markers.SOURCE_OWN if index == 0 else markers.SOURCE_PARENT
    head = markers.first_segment(account)
    if head.startswith(markers.OFF_BALANCE_PREFIX) or head.startswith("490"):
        return Pair(OTHER, OTHER), markers.SOURCE_RULE
    if head.startswith("5"):
        # Wariant kalkulacyjny (RKBI_*, RKD, RKE…) zależy od treści konta — wpisuje
        # go księgowa, reguły po numerze nie ma.
        return None, markers.SOURCE_NONE
    rule = markers.rule_for(account)
    if rule is not None:
        return rule, markers.SOURCE_RULE
    return None, markers.SOURCE_NONE


def zois(
    sums: Mapping[str, Sums],
    own: Mapping[str, Optional[str]],
    names: Mapping[str, str],
) -> list[Row]:
    """Wiersze ZOiS: konta z zapisami i wszystkie konta nad nimi."""

    rows: dict[str, Row] = {}

    def row(account: str) -> Row:
        if account not in rows:
            rows[account] = Row(
                account=account,
                name=name_for(account, names),
                parent=parent_of(account),
            )
        return rows[account]

    for account, amounts in sums.items():
        debit_side = max(amounts.balance, 0)
        credit_side = max(-amounts.balance, 0)
        pair, source = account_marker(account, own)
        leaf = row(account)
        leaf.pair, leaf.source = pair, source
        for target in [account, *ancestors(account)]:
            item = row(target)
            item.bo_debit += amounts.bo_debit
            item.bo_credit += amounts.bo_credit
            item.debit += amounts.debit
            item.credit += amounts.credit
            item.balance_debit += debit_side
            item.balance_credit += credit_side
            if target != account:
                item.leaf = False
                if pair is not None:
                    item.children_pairs.add(pair)
    for item in rows.values():
        if item.leaf:
            continue
        own_pair = item.pair
        if item.account in sums and own_pair is not None:
            item.children_pairs.add(own_pair)
        if len(item.children_pairs) == 1:
            item.pair = next(iter(item.children_pairs))
            item.source = markers.SOURCE_PARENT
        else:
            item.pair = Pair(OTHER, OTHER)
            item.source = markers.SOURCE_RULE
    return [rows[key] for key in sorted(rows, key=account_order)]


def account_order(account: str) -> tuple[Any, ...]:
    return tuple(
        (0, int(part), "") if part.isdigit() else (1, 0, part)
        for part in account.split("-")
    )


# ── Kontrahenci ──────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def country_codes() -> frozenset[str]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    root = etree.parse(str(COUNTRIES), parser).getroot()
    xsd = "{http://www.w3.org/2001/XMLSchema}"
    return frozenset(item.get("value") or "" for item in root.iter(f"{xsd}enumeration"))


def party_tax_id(party: Party) -> Optional[tuple[Optional[str], str]]:
    """(``T_2`` kraj ISO albo ``None``, ``T_3`` numer) — ``None`` = bez numeru
    podatkowego, kontrahenta nie wykazuje się (MF, pytanie 111)."""

    if party.id_type not in TAX_ID_TYPES:
        return None
    number = "".join(ch for ch in (party.id_value or "") if ch.isalnum()).upper()
    if not number:
        return None
    country = (party.country or "").upper()
    if party.id_type == "nip":
        digits = number[2:] if number.startswith("PL") else number
        return "PL", digits
    if party.id_type == "vat_eu" and number[:2].isalpha():
        country = number[:2]
    code = ISO_ALIASES.get(country, country)
    return (code if code in country_codes() else None), number


def document_party(doc: Doc, parties: Mapping[int, Party]) -> Optional[Party]:
    if doc.doc_type == "LP" or doc.counterparty_id is None:
        return None
    party = parties.get(doc.counterparty_id)
    if party is None or party_tax_id(party) is None:
        return None
    return party


# ── Braki ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Problem:
    code: str
    message: str
    items: tuple[str, ...] = ()


def company_missing(
    company: payroll_parameters.Company, settings: JpkKrSettings
) -> list[str]:
    out = []
    if not company.tax_office_code:
        out.append("kod urzędu skarbowego (Płace → Parametry → Dane płatnika)")
    missing = settings.missing()
    if missing:
        out.append(
            "dane do JPK_KR_PD (Sprawozdania, administrator): " + ", ".join(missing)
        )
    return out


def problems(
    *,
    year: int,
    open_months: list[int],
    rows: list[Row],
    company: payroll_parameters.Company,
    settings: JpkKrSettings,
    documents: int,
    payroll_accounts: frozenset[str] = frozenset(),
    viewer_payroll: bool = True,
) -> list[Problem]:
    """Braki blokujące plik (lista pusta = plik się składa)."""

    out: list[Problem] = []
    if year > SCHEMA_LAST_YEAR:
        out.append(
            Problem("year", f"Schemat MF przyjmuje daty do {SCHEMA_LAST_YEAR} roku.")
        )
    if open_months:
        out.append(
            Problem(
                "periods",
                "Niezamknięte okresy — plik roczny składa się z zamkniętych miesięcy.",
                tuple(f"{month:02d}/{year}" for month in open_months),
            )
        )
    if not documents:
        out.append(Problem("empty", "W roku nie ma zatwierdzonych dokumentów."))
    unmarked: list[str] = []
    for row in rows:
        if row.leaf and row.pair is None:
            shown = (
                markers.first_segment(row.account)
                if not viewer_payroll and row.account in payroll_accounts
                else row.account
            )
            if shown not in unmarked:
                unmarked.append(shown)
    if unmarked:
        out.append(
            Problem(
                "markers",
                "Konta bez znacznika MF (Sprawozdania → Pozycje kont; konta 5 — "
                "znaczniki wariantu kalkulacyjnego).",
                tuple(unmarked[:LISTED_MAX]),
            )
        )
    if not settings.estonian:
        out.append(
            Problem(
                "estonian",
                "NEXUS składa JPK_KR_PD tylko dla CIT estońskiego (RPD z zerami) — "
                "znaczniki PD i RPD na zasadach ogólnych są poza NEXUSEM.",
            )
        )
    missing = company_missing(company, settings)
    if missing:
        out.append(Problem("company", "Brakuje danych podatnika.", tuple(missing)))
    return out


# ── XML ──────────────────────────────────────────────────────────────────────


def clean(value: Optional[str], limit: int) -> str:
    text = " ".join(_NOT_XML.sub(" ", value or "").split())
    return text[:limit]


def sub(parent: Any, tag: str, text: Any = None, ns: str = NS, **attrs: str) -> Any:
    node = etree.SubElement(parent, f"{{{ns}}}{tag}", attrs)
    if text is not None:
        node.text = str(text)
    return node


def header(
    root: Any,
    *,
    code: str,
    system_code: str,
    version: str,
    ns: str,
    year_from: date,
    year_to: date,
    correction: bool,
    now: datetime,
    tax_office: str,
    with_period: bool,
) -> None:
    head = sub(root, "Naglowek", ns=ns)
    sub(
        head,
        "KodFormularza",
        code,
        ns=ns,
        kodSystemowy=system_code,
        wersjaSchemy=version,
    )
    sub(head, "WariantFormularza", 1, ns=ns)
    sub(head, "CelZlozenia", 2 if correction else 1, ns=ns)
    sub(
        head,
        "DataWytworzeniaJPK",
        now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ns=ns,
    )
    if with_period:
        sub(head, "DataOd", year_from.isoformat(), ns=ns)
        sub(head, "DataDo", year_to.isoformat(), ns=ns)
    sub(head, "RokDataOd", year_from.isoformat(), ns=ns)
    sub(head, "RokDataDo", year_to.isoformat(), ns=ns)
    # Rok podatkowy = obrotowy; pola są w schemacie obowiązkowe.
    sub(head, "RokPdDataOd", year_from.isoformat(), ns=ns)
    sub(head, "RokPdDataDo", year_to.isoformat(), ns=ns)
    sub(head, "DomyslnyKodWaluty", CURRENCY, ns=ns)
    sub(head, "KodUrzedu", tax_office, ns=ns)


def subject(
    root: Any,
    *,
    ns: str,
    company: payroll_parameters.Company,
    settings: JpkKrSettings,
    estonian_marker: bool,
) -> None:
    node = sub(root, "Podmiot1", ns=ns)
    ident = sub(node, "IdentyfikatorPodmiotu", ns=ns)
    sub(ident, "NIP", company.nip, ns=ETD)
    sub(ident, "PelnaNazwa", clean(company.name, NAME_MAX), ns=ETD)
    if company.regon:
        sub(ident, "REGON", company.regon, ns=ETD)
    address = sub(sub(node, "Adres", ns=ns), "AdresPol", ns=ns)
    sub(address, "KodKraju", "PL", ns=ETD)
    for key, (tag, limit, _) in JPK_KR_ADDRESS_FIELDS.items():
        value = clean(settings.address.get(key), limit)
        if value:
            sub(address, tag, value, ns=ETD)
    if estonian_marker:
        sub(node, "Znacznik_EST", 1, ns=ns)


@dataclass(frozen=True)
class Totals:
    documents: int
    documents_amount: int
    lines: int
    debit: int
    credit: int
    accounts: int
    parties: int


def build(
    *,
    year_from: date,
    year_to: date,
    docs: list[Doc],
    rows: list[Row],
    parties: Mapping[int, Party],
    company: payroll_parameters.Company,
    settings: JpkKrSettings,
    correction: bool,
    now: datetime,
) -> tuple[bytes, Totals]:
    """XML JPK_KR_PD(1) z dokumentów roku i wierszy ZOiS."""

    root = etree.Element(f"{{{NS}}}JPK", nsmap={None: NS, "etd": ETD})
    header(
        root,
        code="JPK_KR_PD",
        system_code="JPK_KR_PD (1)",
        version="1-1",
        ns=NS,
        year_from=year_from,
        year_to=year_to,
        correction=correction,
        now=now,
        tax_office=company.tax_office_code or "",
        with_period=True,
    )
    subject(
        root,
        ns=NS,
        company=company,
        settings=settings,
        estonian_marker=settings.estonian,
    )

    used: dict[int, Party] = {}
    for doc in docs:
        party = document_party(doc, parties)
        if party is not None:
            used.setdefault(party.id, party)
    for party in sorted(used.values(), key=lambda item: item.id):
        tax = party_tax_id(party)
        assert tax is not None
        node = sub(root, "Kontrahent")
        sub(node, "T_1", party.id)
        if tax[0]:
            sub(node, "T_2", tax[0])
        sub(node, "T_3", tax[1])

    zois_node = sub(root, "ZOiS")
    for row in rows:
        node = sub(zois_node, "ZOiS7")
        sub(node, "S_1", row.account)
        sub(node, "S_2", clean(row.name, TEXT_MAX) or row.account)
        sub(node, "S_3", row.parent)
        for tag, value in (
            ("S_4", row.bo_debit),
            ("S_5", row.bo_credit),
            ("S_6", row.debit),
            ("S_7", row.credit),
            ("S_8", row.debit),
            ("S_9", row.credit),
            ("S_10", row.balance_debit),
            ("S_11", row.balance_credit),
        ):
            sub(node, tag, money(value))
        pair = row.pair or Pair(OTHER, OTHER)
        sub(node, "S_12_1", pair.debit)
        if pair.credit != pair.debit:
            sub(node, "S_12_2", pair.credit)

    line_no = 0
    debit_total = credit_total = documents_amount = 0
    for doc in docs:
        node = sub(root, "Dziennik")
        amount = sum(line.amount for line in doc.lines if line.side == "debit")
        documents_amount += amount
        party = document_party(doc, parties)
        label = engine.DOC_TYPE_LABELS.get(doc.doc_type, doc.doc_type)
        sub(node, "D_1", doc.journal_no)
        sub(node, "D_2", JOURNAL)
        if party is not None:
            sub(node, "D_3", party.id)
        sub(node, "D_4", clean(doc.number, TEXT_MAX) or str(doc.journal_no))
        sub(node, "D_5", label)
        sub(node, "D_6", doc.op_date.isoformat())
        sub(node, "D_7", doc.doc_date.isoformat())
        sub(node, "D_8", doc.booked_on.isoformat())
        sub(node, "D_9", clean(doc.author, TEXT_MAX) or "NEXUS")
        sub(
            node,
            "D_10",
            clean(doc.description, LONG_TEXT_MAX)
            or f"{label} {doc.number}"[:LONG_TEXT_MAX],
        )
        sub(node, "D_11", money(amount))
        if doc.ksef_number and KSEF.match(doc.ksef_number):
            sub(node, "D_12", doc.ksef_number)
        for line in doc.lines:
            line_no += 1
            entry = sub(node, "KontoZapis")
            sub(entry, "Z_1", line_no)
            sub(
                entry,
                "Z_2",
                clean(line.description, LONG_TEXT_MAX)
                or clean(doc.description, LONG_TEXT_MAX)
                or f"{label} {doc.number}"[:LONG_TEXT_MAX],
            )
            sub(entry, "Z_3", line.account)
            foreign = line.currency != CURRENCY and line.amount_cur is not None
            if line.side == "debit":
                debit_total += line.amount
                sub(entry, "Z_4", money(line.amount))
                if foreign:
                    sub(entry, "Z_5", money(int(line.amount_cur or 0)))
                    sub(entry, "Z_6", line.currency)
            else:
                credit_total += line.amount
                sub(entry, "Z_7", money(line.amount))
                if foreign:
                    sub(entry, "Z_8", money(int(line.amount_cur or 0)))
                    sub(entry, "Z_9", line.currency)

    ctrl = sub(root, "Ctrl")
    sub(ctrl, "C_1", len(docs))
    sub(ctrl, "C_2", money(documents_amount))
    sub(ctrl, "C_3", line_no)
    sub(ctrl, "C_4", money(debit_total))
    sub(ctrl, "C_5", money(credit_total))
    rpd = sub(root, "RPD")
    for index in range(1, 9):
        sub(rpd, f"K_{index}", money(0))
    content = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
    return content, Totals(
        documents=len(docs),
        documents_amount=documents_amount,
        lines=line_no,
        debit=debit_total,
        credit=credit_total,
        accounts=len(rows),
        parties=len(used),
    )


@lru_cache(maxsize=2)
def _schema(path: str) -> Any:
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    return etree.XMLSchema(etree.parse(path, parser))


def validate(content: bytes, schema: Path = SCHEMA) -> list[str]:
    """Błędy schematu MF (pierwsze kilka); pusta lista = plik poprawny."""

    compiled = _schema(str(schema))
    document = etree.fromstring(
        content,
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    if compiled.validate(document):
        return []
    return [
        f"wiersz {error.line}: {error.message}"
        for error in list(compiled.error_log)[:ERRORS_SHOWN]
    ]


def sums_from_docs(docs: Iterable[Doc]) -> dict[str, Sums]:
    out: dict[str, Sums] = defaultdict(Sums)
    for doc in docs:
        opening = doc.doc_type == "BO"
        for line in doc.lines:
            item = out[line.account]
            if opening:
                if line.side == "debit":
                    item.bo_debit += line.amount
                else:
                    item.bo_credit += line.amount
            elif line.side == "debit":
                item.debit += line.amount
            else:
                item.credit += line.amount
    return dict(out)


# ── Baza ─────────────────────────────────────────────────────────────────────


def can_download(viewer: Viewer) -> bool:
    return viewer.payroll or viewer.admin


async def year_row(db: AsyncSession, year: int) -> LedgerYear:
    row = await db.scalar(select(LedgerYear).where(LedgerYear.year == year))
    if row is None:
        raise LedgerError(f"Nie ma roku obrotowego {year}.", status=404)
    return row


async def open_months(db: AsyncSession, year_id: int) -> list[int]:
    rows = await db.scalars(
        select(LedgerPeriod.month)
        .where(LedgerPeriod.year_id == year_id, LedgerPeriod.status != "closed")
        .order_by(LedgerPeriod.month)
    )
    return [int(month) for month in rows.all()]


async def account_names(
    db: AsyncSession,
) -> tuple[dict[str, Optional[str]], dict[str, str]]:
    """``report_line`` i nazwy z planu kont plus nazwy analityk słownika
    kontrahentów (konto rozrachunkowe z kartoteki)."""

    rows = (
        await db.execute(
            select(
                FinanceAccount.number, FinanceAccount.name, FinanceAccount.report_line
            )
        )
    ).all()
    own = {number: line for number, _, line in rows}
    names = {number: name for number, name, _ in rows}
    parties = (
        await db.execute(
            select(
                FinanceCounterparty.name,
                FinanceCounterparty.cost_account,
                FinanceCounterparty.revenue_account,
            )
        )
    ).all()
    for name, cost, revenue in parties:
        for account in (cost, revenue):
            if account and account not in names:
                names[account] = name
    return own, names


def name_for(account: str, names: Mapping[str, str]) -> str:
    if account in names:
        return names[account]
    for candidate in ancestors(account):
        if candidate in names:
            return f"{names[candidate]} · {account.rsplit('-', 1)[-1]}"
    return account


async def year_sums(
    db: AsyncSession, year_id: int
) -> tuple[dict[str, Sums], frozenset[str], int]:
    """Kwoty kont roku (zatwierdzone), konta z dokumentów płacowych, liczba dowodów."""

    is_bo = LedgerDocument.doc_type == "BO"
    debit = LedgerLine.side == "debit"

    def total(condition: Any) -> Any:
        return func.coalesce(func.sum(case((condition, LedgerLine.amount), else_=0)), 0)

    rows = await db.execute(
        select(
            LedgerLine.account,
            func.bool_or(LedgerDocument.sensitivity.is_not(None)),
            total(is_bo & debit),
            total(is_bo & ~debit),
            total(~is_bo & debit),
            total(~is_bo & ~debit),
        )
        .join(LedgerDocument, LedgerDocument.id == LedgerLine.document_id)
        .where(LedgerDocument.year_id == year_id, LedgerDocument.status == "approved")
        .group_by(LedgerLine.account)
    )
    sums: dict[str, Sums] = {}
    payroll: set[str] = set()
    for account, sensitive, bo_wn, bo_ma, wn, ma in rows.all():
        sums[account] = Sums(int(bo_wn), int(bo_ma), int(wn), int(ma))
        if sensitive:
            payroll.add(account)
    documents = await db.scalar(
        select(func.count(LedgerDocument.id)).where(
            LedgerDocument.year_id == year_id, LedgerDocument.status == "approved"
        )
    )
    return sums, frozenset(payroll), int(documents or 0)


async def year_documents(db: AsyncSession, year_id: int) -> list[Doc]:
    """Zatwierdzone dokumenty roku w kolejności dziennika, z pozycjami."""

    docs = (
        (
            await db.execute(
                select(LedgerDocument)
                .where(
                    LedgerDocument.year_id == year_id,
                    LedgerDocument.status == "approved",
                )
                .order_by(LedgerDocument.journal_no, LedgerDocument.id)
            )
        )
        .scalars()
        .all()
    )
    if not docs:
        return []
    lines: dict[int, list[Line]] = defaultdict(list)
    line_rows = await db.execute(
        select(
            LedgerLine.document_id,
            LedgerLine.side,
            LedgerLine.account,
            LedgerLine.amount,
            LedgerLine.description,
            LedgerLine.currency,
            LedgerLine.amount_cur,
        )
        .join(LedgerDocument, LedgerDocument.id == LedgerLine.document_id)
        .where(LedgerDocument.year_id == year_id, LedgerDocument.status == "approved")
        .order_by(LedgerLine.document_id, LedgerLine.line_no)
    )
    for doc_id, side, account, amount, text, currency, amount_cur in line_rows.all():
        lines[doc_id].append(
            Line(
                side=side,
                account=account,
                amount=int(amount),
                description=text or "",
                currency=currency or CURRENCY,
                amount_cur=int(amount_cur) if amount_cur is not None else None,
            )
        )
    user_ids = {
        user_id
        for doc in docs
        for user_id in (doc.created_by, doc.approved_by)
        if user_id is not None
    }
    users = (
        dict(
            (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(user_ids))
                )
            ).all()
        )
        if user_ids
        else {}
    )
    out = []
    for doc in docs:
        booked = (
            doc.approved_at.astimezone(_WARSAW).date()
            if doc.approved_at is not None
            else doc.op_date
        )
        out.append(
            Doc(
                journal_no=int(doc.journal_no or 0),
                doc_type=doc.doc_type,
                number=doc.number,
                op_date=doc.op_date,
                doc_date=doc.doc_date,
                booked_on=booked,
                author=users.get(doc.created_by) or users.get(doc.approved_by) or "",
                description=doc.description or "",
                lines=tuple(lines.get(doc.id, ())),
                counterparty_id=doc.counterparty_id,
                ksef_number=(doc.meta or {}).get("ksef_number"),
            )
        )
    return out


async def load_parties(db: AsyncSession, ids: set[int]) -> dict[int, Party]:
    if not ids:
        return {}
    rows = await db.execute(
        select(
            FinanceCounterparty.id,
            FinanceCounterparty.id_type,
            FinanceCounterparty.id_value,
            FinanceCounterparty.country,
        ).where(FinanceCounterparty.id.in_(ids))
    )
    return {
        row.id: Party(row.id, row.id_type, row.id_value, row.country)
        for row in rows.all()
    }


def problem_json(item: Problem) -> dict[str, Any]:
    return {"code": item.code, "message": item.message, "items": list(item.items)}


def problems_text(found: list[Problem]) -> str:
    return " | ".join(
        item.message + (f" ({', '.join(item.items[:10])})" if item.items else "")
        for item in found
    )


async def overview(
    db: AsyncSession, viewer: Viewer, settings: LedgerSettings, *, year: int
) -> dict[str, Any]:
    """Stan pliku za rok: braki blokujące, liczby i co wolno tej osobie."""

    row = await year_row(db, year)
    sums, payroll_accounts, documents = await year_sums(db, row.id)
    own, names = await account_names(db)
    rows = zois(sums, own, names)
    company = await payroll_parameters.load_company(db)
    found = problems(
        year=year,
        open_months=await open_months(db, row.id),
        rows=rows,
        company=company,
        settings=settings.jpk_kr,
        documents=documents,
        payroll_accounts=payroll_accounts,
        viewer_payroll=viewer.payroll or viewer.admin,
    )
    warnings = []
    if row.mode != "nexus":
        warnings.append(
            "Księgą urzędową roku jest Symfonia FK — plik z NEXUSA służy do "
            "porównania z plikiem z Symfonii, wysyła się plik z księgi urzędowej."
        )
    if row.status != "closed":
        warnings.append(
            "Rok nie jest zamknięty: przeksięgowanie wyniku na 860 i BO następnego "
            "roku przyjdą z K8b — plik pokazuje księgi bez nich."
        )
    return {
        "year": year,
        "mode": row.mode,
        "documents": documents,
        "accounts": len(rows),
        "problems": [problem_json(item) for item in found],
        "warnings": warnings,
        "ready": not found,
        "can_download": can_download(viewer),
        "can_compare": can_download(viewer) and row.mode != "nexus",
        "can_edit_settings": viewer.admin,
        "settings": {
            "address": dict(settings.jpk_kr.address),
            "estonian": settings.jpk_kr.estonian,
            "estonian_since": settings.jpk_kr.estonian_since,
        },
        "file_name": f"JPK_KR_PD_{year}.xml",
    }


@dataclass(frozen=True)
class Prepared:
    year: LedgerYear
    docs: list[Doc]
    rows: list[Row]
    parties: dict[int, Party]
    company: payroll_parameters.Company
    problems: list[Problem]


async def prepare(db: AsyncSession, settings: LedgerSettings, *, year: int) -> Prepared:
    """Dane pliku: dokumenty, ZOiS, kontrahenci i braki (pełne — D2)."""

    row = await year_row(db, year)
    docs = await year_documents(db, row.id)
    own, names = await account_names(db)
    rows = zois(sums_from_docs(docs), own, names)
    parties = await load_parties(
        db, {doc.counterparty_id for doc in docs if doc.counterparty_id is not None}
    )
    company = await payroll_parameters.load_company(db)
    found = problems(
        year=year,
        open_months=await open_months(db, row.id),
        rows=rows,
        company=company,
        settings=settings.jpk_kr,
        documents=len(docs),
    )
    return Prepared(row, docs, rows, parties, company, found)


async def file(
    db: AsyncSession,
    viewer: Viewer,
    settings: LedgerSettings,
    *,
    year: int,
    correction: bool,
    now: datetime,
) -> tuple[str, bytes]:
    """Plik JPK_KR_PD za rok — tylko bez braków i po sprawdzeniu schematem MF."""

    if not can_download(viewer):
        raise LedgerError(ONLY_PAYROLL, status=403)
    data = await prepare(db, settings, year=year)
    found = data.problems
    if found:
        raise LedgerError(
            "Plik JPK_KR_PD się nie składa — " + problems_text(found),
            status=422,
        )
    content, _ = build(
        year_from=data.year.starts_on,
        year_to=data.year.ends_on,
        docs=data.docs,
        rows=data.rows,
        parties=data.parties,
        company=data.company,
        settings=settings.jpk_kr,
        correction=correction,
        now=now,
    )
    errors = validate(content)
    if errors:
        raise LedgerError(
            f"Plik JPK_KR_PD nie przechodzi schematu MF — {' | '.join(errors)}",
            status=422,
        )
    return f"JPK_KR_PD_{year}.xml", content
