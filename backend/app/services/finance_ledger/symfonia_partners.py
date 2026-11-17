"""Kontrahenci „czekają na Symfonię”: lista i plik roboczy dla księgowej (E0b).

Po wyłączeniu eBI24 nikt nie zakłada kontrahentów w Symfonii FK, więc NEXUS
wypisuje tych, którzy faktur już dotyczą, a ID Symfonii jeszcze nie mają:

* ``kartoteka`` — wiersz kartoteki bez ``symfonia_partner_id`` (np. dostawca
  z formularza zakupu zagranicznego),
* ``koszty`` — sprzedawca z kolejki kosztów (KSeF, PDF), którego numeru nie ma
  w kartotece; NEXUS zna wtedy tylko nazwę i numer, adresu nie (XML kosztów
  nie pobieramy),
* ``sprzedaz`` — nabywca faktury sprzedaży spoza kartoteki (adres z karty
  klienta, jeśli jest).

Plik to CSV roboczy (UTF-8 z BOM, średniki): format importu kartoteki w Symfonii
FK nie wynika z próbek księgowej, więc plik nie udaje formatu Symfonii. Jego
nagłówki są aliasami importu E0 (``counterparty_import``): księgowa wpisuje „ID
Symfonii”, odsyła ten sam plik, a import zakłada kontrahenta albo uzupełnia
istniejącego. Konta nadaje Symfonia i nie ma ich w pliku: wynikają z ID
(``derived_accounts``), jak w eksporcie z eBI24 (2326 z 2326 partnerów).
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.finance_ledger import FinanceCostEntry, FinanceCounterparty
from app.services.finance_ledger import costs, identifiers

SOURCE_LABELS = {
    "kartoteka": "kartoteka",
    "koszty": "faktura kosztowa",
    "sprzedaz": "faktura sprzedaży",
}
#: Kolejność w wierszu: kto ma adres, wygrywa nazwę i adres przy łączeniu źródeł.
_SOURCE_ORDER = ("kartoteka", "sprzedaz", "koszty")
#: Krajowi: odbiorcy ``200-2``, dostawcy ``201-2``; zagraniczni ``202-2`` i ``203-2``.
_ACCOUNT_PREFIXES = {True: ("200-2", "201-2"), False: ("202-2", "203-2")}

CSV_COLUMNS: tuple[str, ...] = (
    "Nazwa",
    "NIP / VAT UE",
    "Typ numeru",
    "Kraj",
    "Ulica",
    "Kod pocztowy",
    "Miasto",
    "ID Symfonii",
    "Konto odbiorcy (prefiks)",
    "Konto dostawcy (prefiks)",
    "Źródło w NEXUSIE",
)


@dataclass
class Candidate:
    id_type: Optional[str]
    id_value: Optional[str]
    name: str
    street: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    sources: list[str] = field(default_factory=list)
    counterparty_id: Optional[int] = None
    problems: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.id_type}:{self.id_value}"

    @property
    def warnings(self) -> list[str]:
        # Adres klienta to jedno pole (``clients.address``) — liczy się, że jest.
        if not (self.street or self.city):
            return ["brak adresu"]
        return []

    @property
    def ready(self) -> bool:
        return not self.problems


def derived_accounts(
    partner_id: Optional[str], country: Optional[str]
) -> Optional[tuple[str, str]]:
    """(konto kosztowe, konto przychodowe) z ID Symfonii i kraju; brak = ``None``."""

    partner = (partner_id or "").strip()
    if not partner.isdigit() or not country:
        return None
    receivable, payable = _ACCOUNT_PREFIXES[country.upper() == "PL"]
    return f"{payable}-{partner}", f"{receivable}-{partner}"


def account_prefixes(country: Optional[str]) -> tuple[str, str]:
    """(prefiks konta odbiorcy, prefiks konta dostawcy) dla kraju kontrahenta."""

    return _ACCOUNT_PREFIXES[(country or "PL").upper() == "PL"]


def country_of(
    id_type: Optional[str], id_value: Optional[str], stored: Optional[str]
) -> Optional[str]:
    """Kraj: zapisany, a bez niego z numeru (NIP = PL, VAT UE = prefiks)."""

    if stored:
        return stored.upper()
    if id_type == "nip":
        return "PL"
    if id_type == "vat_eu" and id_value:
        return id_value[:2]
    return None


def _clean(value: Optional[str]) -> Optional[str]:
    text = " ".join((value or "").split())
    return text or None


def _candidate(
    source: str,
    raw_number: Optional[str],
    name: Optional[str],
    *,
    street: Optional[str] = None,
    country: Optional[str] = None,
    id_type: Optional[str] = None,
    postal_code: Optional[str] = None,
    city: Optional[str] = None,
    counterparty_id: Optional[int] = None,
    validate: bool = True,
) -> Candidate:
    """Kandydat z kontrolą numeru; zły numer nie trafia do pliku."""

    problems: list[str] = []
    found = None
    if validate:
        try:
            found = identifiers.normalize(raw_number, id_type)
        except identifiers.IdentifierError as exc:
            problems.append(f"numer: {exc}")
    elif raw_number:
        found = identifiers.Identifier(id_type or "other", raw_number)
    if found is None and not problems:
        problems.append("brak numeru identyfikacyjnego")
    title = _clean(name)
    if title is None:
        problems.append("brak nazwy")
    kind, value = (found.type, found.value) if found else (id_type, raw_number)
    code = country_of(kind, value, country)
    if code is None:
        problems.append("brak kraju")
    return Candidate(
        id_type=kind,
        id_value=value,
        name=title or "—",
        street=_clean(street),
        postal_code=_clean(postal_code),
        city=_clean(city),
        country=code,
        sources=[source],
        counterparty_id=counterparty_id,
        problems=problems,
    )


async def _from_registry(db: AsyncSession) -> tuple[list[Candidate], set[tuple]]:
    rows = list(await db.scalars(select(FinanceCounterparty)))
    known = {(row.id_type, row.id_value) for row in rows if row.id_value}
    waiting = [
        _candidate(
            "kartoteka",
            row.id_value,
            row.name,
            id_type=row.id_type,
            street=row.street,
            postal_code=row.postal_code,
            city=row.city,
            country=row.country,
            counterparty_id=row.id,
            validate=False,
        )
        for row in rows
        if not row.symfonia_partner_id
    ]
    return waiting, known


async def _from_costs(db: AsyncSession, *, payroll: bool) -> list[Candidate]:
    src = costs._sources()
    on_source, _ = costs._joined(src)
    entry = FinanceCostEntry
    rows = await db.execute(
        select(entry.seller_nip, src.c.seller_name)
        .join(src, on_source)
        .where(
            entry.counterparty_id.is_(None),
            entry.seller_nip.is_not(None),
            entry.stage != "rejected",
            *costs._payroll_scope(payroll),
        )
        .order_by(entry.received_at.desc(), entry.id.desc())
    )
    # Bez wymuszania typu: 10 cyfr to NIP z sumą kontrolną, prefiks kraju UE to
    # VAT UE (dokument wydatku z PDF bywa od dostawcy zagranicznego).
    return [_candidate("koszty", number, name) for number, name in rows.all() if number]


#: ``AdresL2`` w FA to zwykle „kod miasto” (``00-001 Warszawa``, ``10115 Berlin``).
_POSTAL_CITY = re.compile(r"^(\d[\d-]{2,9})\s+(\D.*)$")


def split_postal_city(line: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """(kod pocztowy, miasto) z drugiej linii adresu FA; bez kodu całość to miasto."""

    text = _clean(line)
    if text is None:
        return None, None
    found = _POSTAL_CITY.match(text)
    return (found.group(1), found.group(2)) if found else (None, text)


async def _from_sales(db: AsyncSession) -> list[Candidate]:
    """Nabywcy faktur sprzedaży, najnowsza faktura pierwsza (jej adres wygrywa
    przy łączeniu); adres z ``Podmiot2/Adres`` faktury, bez niego ``clients.address``."""

    invoice = ClientSalesInvoice
    rows = await db.execute(
        select(
            invoice.buyer_nip,
            invoice.buyer_foreign_id,
            invoice.buyer_name,
            invoice.buyer_country,
            invoice.buyer_address_line1,
            invoice.buyer_address_line2,
            Client.name,
            Client.address,
        )
        .outerjoin(Client, Client.id == invoice.client_id)
        .where(
            (invoice.buyer_nip.is_not(None)) | (invoice.buyer_foreign_id.is_not(None))
        )
        .order_by(invoice.issue_date.desc(), invoice.id.desc())
    )
    out = []
    for (
        nip,
        foreign,
        buyer_name,
        country,
        line1,
        line2,
        client_name,
        address,
    ) in rows.all():
        postal_code, city = split_postal_city(line2)
        from_invoice = bool(_clean(line1) or city)
        out.append(
            _candidate(
                "sprzedaz",
                nip or foreign,
                buyer_name or client_name,
                street=line1 if from_invoice else address,
                postal_code=postal_code if from_invoice else None,
                city=city if from_invoice else None,
                # Kraj z adresu tylko bez polskiego NIP-u: NIP to zawsze kontrahent
                # krajowy (konta 200-2/201-2), nawet z adresem oddziału za granicą.
                country=None if nip else country,
                id_type="nip" if nip else None,
            )
        )
    return out


def _merge(items: Iterable[Candidate]) -> list[Candidate]:
    """Jeden wiersz na numer; dane daje pierwsze źródło z ``_SOURCE_ORDER``."""

    merged: dict[str, Candidate] = {}
    for item in sorted(items, key=lambda c: _SOURCE_ORDER.index(c.sources[0])):
        key = item.key if item.id_value else f"row:{item.counterparty_id}"
        current = merged.get(key)
        if current is None:
            merged[key] = item
            continue
        for label in item.sources:
            if label not in current.sources:
                current.sources.append(label)
        for attr in ("street", "postal_code", "city"):
            if not getattr(current, attr) and getattr(item, attr):
                setattr(current, attr, getattr(item, attr))
        if current.counterparty_id is None:
            current.counterparty_id = item.counterparty_id
    return sorted(merged.values(), key=lambda c: (bool(c.problems), c.name.casefold()))


async def pending(db: AsyncSession, *, payroll: bool) -> list[Candidate]:
    """Kontrahenci bez ID Symfonii: kartoteka, potem sprzedawcy i nabywcy spoza niej."""

    registry, known = await _from_registry(db)
    outside = [
        item
        for item in [*await _from_sales(db), *await _from_costs(db, payroll=payroll)]
        if (item.id_type, item.id_value) not in known
    ]
    return _merge([*registry, *outside])


def payload(item: Candidate) -> dict[str, Any]:
    receivable, payable = account_prefixes(item.country)
    return {
        "key": item.key if item.id_value else f"row:{item.counterparty_id}",
        "name": item.name,
        "id_type": item.id_type,
        "id_type_label": identifiers.TYPE_LABELS.get(item.id_type or ""),
        "id_value": item.id_value,
        "street": item.street,
        "postal_code": item.postal_code,
        "city": item.city,
        "country": item.country,
        "sources": [SOURCE_LABELS[label] for label in item.sources],
        "counterparty_id": item.counterparty_id,
        "receivable_prefix": receivable,
        "payable_prefix": payable,
        "problems": item.problems,
        "warnings": item.warnings,
        "ready": item.ready,
    }


async def view(db: AsyncSession, *, payroll: bool) -> dict[str, Any]:
    items = await pending(db, payroll=payroll)
    ready = [item for item in items if item.ready]
    registered = await db.scalar(
        select(func.count())
        .select_from(FinanceCounterparty)
        .where(FinanceCounterparty.symfonia_partner_id.is_not(None))
    )
    return {
        "items": [payload(item) for item in items],
        "total": len(items),
        "ready": len(ready),
        "without_address": sum(1 for item in ready if item.warnings),
        "with_problems": len(items) - len(ready),
        #: Ilu kontrahentów kartoteka zna z ID Symfonii. Przy zerze lista zawiera
        #: też tych, którzy już są w Symfonii — najpierw import z eBI24.
        "registered": int(registered or 0),
    }


def _safe(value: str) -> str:
    """Nazwa z KSeF zaczynająca się od ``=``, ``+``, ``-`` albo ``@`` to w Excelu
    formuła; spacja z przodu robi z niej tekst, a import ją zdejmuje."""

    return f" {value}" if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def render_csv(items: Iterable[Candidate]) -> tuple[bytes, int]:
    """Plik roboczy dla księgowej: tylko gotowi, bez problemów z numerem."""

    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    count = 0
    for item in items:
        if not item.ready:
            continue
        receivable, payable = account_prefixes(item.country)
        writer.writerow(
            [
                _safe(item.name),
                item.id_value or "",
                identifiers.TYPE_LABELS.get(item.id_type or "", ""),
                item.country or "",
                _safe(item.street or ""),
                item.postal_code or "",
                _safe(item.city or ""),
                "",
                receivable,
                payable,
                ", ".join(SOURCE_LABELS[label] for label in item.sources),
            ]
        )
        count += 1
    return b"\xef\xbb\xbf" + out.getvalue().encode("utf-8"), count
