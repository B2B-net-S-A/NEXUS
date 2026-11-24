"""Rejestry VAT (K5a): sprzedaż i zakup z zatwierdzonych dokumentów księgi.

Etap K5 planu „Księgowość w NEXUSIE”; reguła modułu:
``docs/claude/finanse-insights/ksiega-nexusa-k5-vat.md``.

* **Okres VAT = okres dokumentu w księdze** (K2): FVS — miesiąc sprzedaży
  (korekta — wystawienia), FVZ — miesiąc wpływu faktury do KSeF. Rejestr to
  stan dziś: dokument ze stornem wypada, jego nowa wersja wchodzi.
* **Sprzedaż** (FVS ze źródła ``client_sales_invoice``): VAT = obroty Ma − Wn
  konta VAT należnego (Ustawienia → konta faktur sprzedaży), brutto = rozrachunek
  z odbiorcą, netto = brutto − VAT — kwoty w PLN z dekretu, czyli po kursie
  dokumentu. Podział na stawki (pola JPK_V7M) z pozycji faktury w KSeF (P_11
  netto, P_12 stawka, wiersz „StanPrzed” korekty ze znakiem minus): jedna
  stawka = całe kwoty; kilka = netto w proporcji pozycji, VAT tylko na stawkach
  z podatkiem, w proporcji netto × stawka (ostatnia bierze resztę groszy).
* **Zakup** (FVZ ze źródła ``finance_cost_entry``): VAT naliczony = obroty
  Wn − Ma konta VAT naliczonego (moduł VAT, admin), brutto = rozrachunek
  z dostawcą, netto = brutto − VAT. Faktura bez VAT naliczonego w dekrecie
  (bez odliczenia) nie wchodzi do rejestru. Wn na koncie przyjęcia środków
  trwałych (K6) = K_40/K_41, reszta = K_42/K_43.
* **D2**: faktury osób zespołu (``sensitivity = 'payroll'``) widzi tylko Płace
  i admin — osoba bez Płac dostaje rejestry, sumy i listy „do sprawdzenia” bez
  nich, a ``payroll_hidden`` mówi tylko, że są (bez liczby).
* **Zakup zagraniczny** (K5b-2, FVZ ze źródła ``foreign_purchase`` —
  formularz w zakładce VAT): import usług bez KSeF. VAT należny z dokumentu
  idzie do rejestru sprzedaży w grupie z dokumentu (K_29/K_30 — usługa od
  podatnika VAT z UE, art. 28b; K_27/K_28 — reszta), VAT naliczony (odliczenie)
  do rejestru zakupu jak każda FVZ.
* **Znaczniki GTU i TP** (K5b-2): per kontrahent z ustawień, na każdym wierszu
  sprzedaży z faktury (FVS) tego kontrahenta; importu usług nie oznacza się
  (GTU nie stosuje się do nabyć z podatkiem należnym — broszura MF).
* **Do sprawdzenia**: stawka spoza słownika, FVS/FVZ w buforze, faktura
  sprzedaży z KSeF z tego miesiąca bez dokumentu w księdze (np. zaliczka —
  VAT od zaliczki jest należny), faktura kosztowa z wpływem w tym miesiącu bez
  FVZ, zapisy na kontach VAT spoza rejestru (PK; bez rozliczenia VAT, wyciągu
  i BO).
* JPK_V7M — ``jpk.py``; VAT-UE i dokument rozliczenia VAT — K5b-3.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable, Optional

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_month_bounds
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.finance_ledger import FinanceCostEntry, FinanceCounterparty
from app.models.ledger import LedgerDocument, LedgerLine
from app.services.finance_ledger import costs
from app.services.finance_ledger import posting_options
from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import sources
from app.services.ledger.documents import FOREIGN_PURCHASE_SOURCE, Viewer
from app.services.ledger.settings import MARKERS, LedgerSettings

SALES_SOURCE = sources.SOURCE_TYPES[sources.SALES]
COST_SOURCE = sources.SOURCE_TYPES[sources.COSTS]
#: Formularz zakupu zagranicznego (K5b-2, ``ledger/foreign.py``).
FOREIGN_SOURCE = FOREIGN_PURCHASE_SOURCE
PURCHASE_SOURCES = (COST_SOURCE, FOREIGN_SOURCE)
REGISTER_SOURCES = (SALES_SOURCE, COST_SOURCE, FOREIGN_SOURCE)
#: Dokumenty, które z zasady dotykają kont VAT poza rejestrem: rozliczenie VAT
#: (K5b), wyciąg (przelew do urzędu, /SFP/) i bilans otwarcia.
OUTSIDE_OK = ("VAT", "WB", "BO")
#: Etapy kolejki kosztów, które nie są fakturą do odliczenia.
COST_SKIPPED_STAGES = ("rejected",)
COST_SKIPPED_CATEGORIES = ("proforma",)
LISTED_MAX = 50


@dataclass(frozen=True)
class Category:
    """Grupa rejestru = para pól JPK_V7M (netto, VAT)."""

    key: str
    label: str
    net_field: str
    vat_field: Optional[str]
    rate: Decimal
    #: Pole „w tym” (usługi dla podatników z UE: K_11 i K_12).
    also: Optional[str] = None


SALES_CATEGORIES: tuple[Category, ...] = (
    Category("23", "Stawka 23% (22%)", "K_19", "K_20", Decimal("0.23")),
    Category("8", "Stawka 8% (7%)", "K_17", "K_18", Decimal("0.08")),
    Category("5", "Stawka 5%", "K_15", "K_16", Decimal("0.05")),
    Category("0", "Stawka 0% w kraju", "K_13", None, Decimal("0")),
    Category(
        "0_wdt", "Wewnątrzwspólnotowa dostawa towarów (0%)", "K_21", None, Decimal("0")
    ),
    Category("0_ex", "Eksport towarów (0%)", "K_22", None, Decimal("0")),
    Category("zw", "Zwolnione od podatku", "K_10", None, Decimal("0")),
    Category("np", "Poza terytorium kraju", "K_11", None, Decimal("0")),
    Category(
        "np_ue",
        "Usługi dla podatników z UE (art. 100 ust. 1 pkt 4)",
        "K_11",
        None,
        Decimal("0"),
        also="K_12",
    ),
    # Import usług (K5b-2) — VAT należny z dokumentu zakupu zagranicznego.
    Category(
        "imp_other",
        "Import usług (pozostały)",
        "K_27",
        "K_28",
        Decimal("0"),
    ),
    Category(
        "imp_28b",
        "Import usług z UE (art. 28b)",
        "K_29",
        "K_30",
        Decimal("0"),
    ),
)
#: Grupy importu usług — wybiera je formularz zakupu zagranicznego.
IMPORT_GROUPS: tuple[str, ...] = ("imp_other", "imp_28b")
PURCHASE_CATEGORIES: tuple[Category, ...] = (
    Category("assets", "Nabycie środków trwałych", "K_40", "K_41", Decimal("0")),
    Category(
        "other", "Nabycie pozostałych towarów i usług", "K_42", "K_43", Decimal("0")
    ),
)
CATEGORIES: dict[str, Category] = {
    item.key: item for item in SALES_CATEGORIES + PURCHASE_CATEGORIES
}
#: Stawka z pozycji faktury (P_12 w KSeF) → grupa sprzedaży.
RATES: dict[str, str] = {
    "23": "23",
    "22": "23",
    "8": "8",
    "7": "8",
    "5": "5",
    "0": "0",
    "0 KR": "0",
    "0 WDT": "0_wdt",
    "0 EX": "0_ex",
    "zw": "zw",
    "np": "np",
    "np I": "np",
    "np II": "np_ue",
}


@dataclass(frozen=True)
class Row:
    """Wiersz rejestru: dokument księgi z kwotami w groszach PLN per grupa."""

    document_id: int
    number: str
    ksef_number: Optional[str]
    issue_date: Optional[date]
    #: Data sprzedaży (FVS) albo wpływu (FVZ) = data dokumentu w księdze.
    day: date
    counterparty: str
    tax_id: Optional[str]
    country: Optional[str]
    #: Sumy z dekretu — także gdy wiersz nie ma podziału na pola JPK (inaczej
    #: „do zapłaty” rozjeżdżało się z kontem VAT; przegląd K5a).
    net: int
    vat: int
    amounts: dict[str, tuple[int, int]]
    correction: bool = False
    payroll: bool = False
    problem: Optional[str] = None
    counterparty_id: Optional[int] = None
    #: Znaczniki JPK wiersza (GTU, TP) — z ustawień kontrahenta (K5b-2).
    markers: tuple[str, ...] = ()
    #: Korekta FVS: miesiąc sprzedaży faktury korygowanej (``RRRR-MM``) — VAT-UE
    #: (K5b-3a) ujmuje korektę wcześniejszego okresu na VAT-UEK za tamten okres.
    corrected_month: Optional[str] = None


def _decimal(value: object) -> Optional[Decimal]:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() else None


def _share(total: int, weights: list[Decimal]) -> list[int]:
    """Grosze rozdzielone w proporcji wag; ostatnia waga bierze resztę."""

    whole = sum(weights)
    out = [
        int(
            (Decimal(total) * weight / whole).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        for weight in weights[:-1]
    ]
    out.append(total - sum(out))
    return out


def split_sales(
    items: Iterable[Any], net: int, vat: int
) -> tuple[dict[str, tuple[int, int]], Optional[str]]:
    """Netto i VAT faktury (grosze PLN) na grupy JPK z pozycji faktury."""

    weights: dict[str, Decimal] = defaultdict(Decimal)
    unknown: set[str] = set()
    without_net: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        rate = str(item.get("vat_rate") or "").strip()
        key = RATES.get(rate)
        if key is None:
            unknown.add(rate or "brak stawki")
            continue
        amount = _decimal(item.get("net"))
        if amount is None:
            without_net.add(key)
            weights[key] += 0
            continue
        weights[key] += -amount if item.get("before_correction") else amount
    if unknown:
        return {}, f"stawka spoza słownika JPK: {', '.join(sorted(unknown))}"
    order = [item.key for item in SALES_CATEGORIES]
    keys = [key for key in order if key in weights]
    if not keys:
        return {}, "pozycje faktury bez stawki VAT"
    if len(keys) > 1:
        keys = [key for key in keys if weights[key] != 0 or key in without_net]
    if len(keys) == 1:
        if vat and CATEGORIES[keys[0]].rate == 0:
            # VAT na stawce bez podatku (np, zw, 0%) nie ma pola w JPK — po cichu
            # by zniknął z deklaracji (przegląd K5b).
            return {}, "VAT na stawce bez podatku (np, zw, 0%) — sprawdź fakturę"
        return {keys[0]: (net, vat)}, None
    if without_net or not keys:
        return {}, "kilka stawek, a pozycje bez kwoty netto — rozdziel ręcznie"
    nets = [weights[key] for key in keys]
    if len({value > 0 for value in nets}) > 1 or sum(nets) == 0:
        return {}, "korekta zmienia stawki — rozdziel ręcznie"
    net_parts = _share(net, nets)
    taxed = [key for key in keys if CATEGORIES[key].rate > 0]
    vat_parts: dict[str, int] = {}
    if taxed:
        shares = _share(vat, [weights[key] * CATEGORIES[key].rate for key in taxed])
        vat_parts = dict(zip(taxed, shares))
    elif vat:
        return {}, "VAT na fakturze bez stawki z podatkiem"
    return (
        {key: (part, vat_parts.get(key, 0)) for key, part in zip(keys, net_parts)},
        None,
    )


def _matches(account: str, base: str) -> bool:
    return bool(base) and (account == base or account.startswith(base + "-"))


Line = tuple[str, str, int, Optional[int]]


def sales_amounts(lines: Iterable[Line], *, output_account: str) -> tuple[int, int]:
    """Netto i VAT należny dokumentu FVS (grosze PLN, korekta in minus < 0)."""

    vat = gross = 0
    for side, account, amount, party in lines:
        sign = 1 if side == "debit" else -1
        if _matches(account, output_account):
            vat -= sign * amount
        elif party is not None:
            gross += sign * amount
    return gross - vat, vat


@dataclass(frozen=True)
class Purchase:
    """FVZ w rejestrach: grupa, netto i VAT naliczony; ``output`` = VAT należny
    rozliczany przez nabywcę w tym samym dokumencie (import usług, odwrotne
    obciążenie) — trafia do rejestru sprzedaży."""

    key: str
    net: int
    vat: int
    output: int


def purchase_amounts(
    lines: Iterable[Line],
    *,
    input_account: str,
    output_account: str,
    intake_account: str,
) -> Optional[Purchase]:
    """Kwoty FVZ z dekretu; ``None`` = bez VAT naliczonego i należnego."""

    vat = output = gross = intake = 0
    touched = False
    for side, account, amount, party in lines:
        sign = 1 if side == "debit" else -1
        if _matches(account, input_account):
            touched = True
            vat += sign * amount
        elif _matches(account, output_account):
            touched = True
            output -= sign * amount
        elif party is not None:
            gross -= sign * amount
        if _matches(account, intake_account):
            # Ruch netto, nie strona: korekta zakupu środka trwałego ma Ma na
            # koncie przyjęcia i dalej jest K_40/K_41 (przegląd K5a).
            intake += sign * amount
    if not touched:
        return None
    # VAT doliczony przez sprzedawcę = naliczony bez części rozliczanej przez
    # nabywcę (VAT należny); bez odliczenia (naliczony 0) sprzedawca nie
    # doliczył nic — netto to kwota od dostawcy, nie koszt z VAT (K5b-2).
    seller_vat = vat - output if vat else 0
    return Purchase("assets" if intake else "other", gross - seller_vat, vat, output)


def summarize(sales_rows: list[Row], purchase_rows: list[Row]) -> dict[str, Any]:
    """Sumy grup (pola JPK) i saldo VAT miesiąca (bez nadwyżki z poprzedniego)."""

    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for row in sales_rows + purchase_rows:
        for key, (net, vat) in row.amounts.items():
            totals[key][0] += net
            totals[key][1] += vat
    groups = []
    for register, categories in (
        ("sales", SALES_CATEGORIES),
        ("purchases", PURCHASE_CATEGORIES),
    ):
        for item in categories:
            if item.key not in totals:
                continue
            net, vat = totals[item.key]
            groups.append(
                {
                    "register": register,
                    "key": item.key,
                    "label": item.label,
                    "net_field": item.net_field,
                    "vat_field": item.vat_field,
                    "also": item.also,
                    "net": net,
                    "vat": vat,
                }
            )
    output_vat = sum(row.vat for row in sales_rows)
    input_vat = sum(row.vat for row in purchase_rows)
    return {
        "groups": groups,
        "output_vat": output_vat,
        "input_vat": input_vat,
        "due": output_vat - input_vat,
    }


def _party_tax_id(
    party: Optional[FinanceCounterparty],
) -> tuple[Optional[str], Optional[str]]:
    """Numer i kraj nadania z rodzaju identyfikatora, nie z kraju adresu:
    NIP = Polska, VAT UE = prefiks numeru (przegląd K5b), PESEL = bez numeru VAT."""

    if party is None or not party.id_value:
        return None, None
    if party.id_type == "nip":
        return party.id_value, "PL"
    if party.id_type == "vat_eu":
        prefix = party.id_value[:2].upper()
        return party.id_value, prefix if prefix.isalpha() else party.country
    if party.id_type == "pesel":
        return None, None
    return party.id_value, party.country or None


def _tax_id(
    nip: Optional[str], foreign: Optional[str]
) -> tuple[Optional[str], Optional[str]]:
    if nip:
        return nip, "PL"
    if foreign:
        prefix = foreign[:2]
        return foreign, prefix.upper() if prefix.isalpha() else None
    return None, None


async def _documents(
    db: AsyncSession, start: date, end: date, viewer: Viewer, *, status: str
) -> list[LedgerDocument]:
    query = select(LedgerDocument).where(
        LedgerDocument.source_type.in_(REGISTER_SOURCES),
        LedgerDocument.status == status,
        LedgerDocument.reversed_by_id.is_(None),
        LedgerDocument.reverses_id.is_(None),
        LedgerDocument.op_date >= start,
        LedgerDocument.op_date < end,
    )
    if not viewer.payroll:
        query = query.where(LedgerDocument.sensitivity.is_(None))
    return list(
        (
            await db.scalars(query.order_by(LedgerDocument.op_date, LedgerDocument.id))
        ).all()
    )


async def _lines(db: AsyncSession, ids: list[int]) -> dict[int, list[Line]]:
    found: dict[int, list[Line]] = defaultdict(list)
    if not ids:
        return found
    rows = await db.execute(
        select(
            LedgerLine.document_id,
            LedgerLine.side,
            LedgerLine.account,
            LedgerLine.amount,
            LedgerLine.counterparty_id,
        ).where(LedgerLine.document_id.in_(ids))
    )
    for doc_id, side, account, amount, party in rows.all():
        found[doc_id].append((side, account, int(amount), party))
    return found


def _source_ids(docs: Iterable[LedgerDocument]) -> list[int]:
    return [int(doc.source_id) for doc in docs if (doc.source_id or "").isdigit()]


async def _sales_rows(
    db: AsyncSession,
    docs: list[LedgerDocument],
    lines: dict[int, list[Line]],
    settings: LedgerSettings,
) -> list[Row]:
    ids = _source_ids(docs)
    invoices: dict[int, ClientSalesInvoice] = {}
    if ids:
        invoices = {
            item.id: item
            for item in (
                await db.scalars(
                    select(ClientSalesInvoice).where(ClientSalesInvoice.id.in_(ids))
                )
            ).all()
        }
    originals: dict[int, Optional[date]] = {}
    corrected = {
        item.corrects_invoice_id
        for item in invoices.values()
        if item.invoice_kind == "correction" and item.corrects_invoice_id
    }
    if corrected:
        originals = {
            item_id: day
            for item_id, day in (
                await db.execute(
                    select(
                        ClientSalesInvoice.id,
                        func.coalesce(
                            ClientSalesInvoice.sale_date, ClientSalesInvoice.issue_date
                        ),
                    ).where(ClientSalesInvoice.id.in_(corrected))
                )
            ).all()
        }
    rows = []
    for doc in docs:
        invoice = (
            invoices.get(int(doc.source_id))
            if (doc.source_id or "").isdigit()
            else None
        )
        net, vat = sales_amounts(
            lines[doc.id], output_account=settings.sales.vat_account
        )
        if invoice is None:
            amounts, problem = {}, "brak faktury źródłowej w KSeF"
        else:
            amounts, problem = split_sales(invoice.items or [], net, vat)
        if any(_matches(line[1], settings.vat.input_account) for line in lines[doc.id]):
            amounts, problem = {}, "FVS z VAT naliczonym w dekrecie — sprawdź dokument"
        tax_id, country = _tax_id(
            invoice.buyer_nip if invoice else None,
            invoice.buyer_foreign_id if invoice else None,
        )
        rows.append(
            Row(
                document_id=doc.id,
                number=doc.number,
                ksef_number=(doc.meta or {}).get("ksef_number"),
                issue_date=doc.doc_date,
                day=doc.op_date,
                counterparty=(invoice.buyer_name if invoice else None)
                or doc.description,
                tax_id=tax_id,
                country=country,
                net=net,
                vat=vat,
                amounts=amounts,
                correction=bool(invoice and invoice.invoice_kind == "correction"),
                problem=problem,
                counterparty_id=doc.counterparty_id,
                markers=settings.vat_markers.get(doc.counterparty_id or 0, ()),
                corrected_month=_corrected_month(invoice, originals),
            )
        )
    return rows


def _corrected_month(
    invoice: Optional[ClientSalesInvoice], originals: dict[int, Optional[date]]
) -> Optional[str]:
    if invoice is None or invoice.invoice_kind != "correction":
        return None
    day = originals.get(invoice.corrects_invoice_id or 0)
    return f"{day.year}-{day.month:02d}" if day else None


#: Wiersz sprzedaży z VAT należnym z FVZ z kolejki kosztów — import usług
#: i krajowe odwrotne obciążenie mają pola JPK tylko z formularza zakupu
#: zagranicznego (K5b-2), który zapisuje grupę w dokumencie.
SELF_ASSESSED = (
    "import usług / odwrotne obciążenie z kolejki kosztów (VAT należny w FVZ) — "
    "zaksięguj fakturę formularzem zakupu zagranicznego w zakładce VAT"
)


async def _purchase_rows(
    db: AsyncSession,
    docs: list[LedgerDocument],
    lines: dict[int, list[Line]],
    settings: LedgerSettings,
) -> tuple[list[Row], list[Row]]:
    """Wiersze zakupu i — dla FVZ z VAT należnym — wiersze sprzedaży (pole JPK
    tylko z formularza zakupu zagranicznego)."""

    party_ids = {doc.counterparty_id for doc in docs if doc.counterparty_id}
    parties: dict[int, FinanceCounterparty] = {}
    if party_ids:
        parties = {
            item.id: item
            for item in (
                await db.scalars(
                    select(FinanceCounterparty).where(
                        FinanceCounterparty.id.in_(party_ids)
                    )
                )
            ).all()
        }
    rows: list[Row] = []
    self_rows: list[Row] = []
    for doc in docs:
        meta = doc.meta or {}
        found = purchase_amounts(
            lines[doc.id],
            input_account=settings.vat.input_account,
            # Import usług z kolejki kosztów: konto VAT należnego z dekretu (226).
            output_account=meta.get("output_account") or settings.sales.vat_account,
            intake_account=settings.assets.intake_account,
        )
        if found is None:
            continue
        if meta.get("register_net") is not None:
            # Samochód (50% VAT): netto rejestru = połowa „Zakup” z opisu faktury.
            found = Purchase(
                found.key, int(meta["register_net"]), found.vat, found.output
            )
        party = parties.get(doc.counterparty_id or 0)
        issued = (doc.meta or {}).get("issue_date")
        issue_date = date.fromisoformat(issued) if issued else doc.doc_date
        received = (doc.meta or {}).get("received_date")
        tax_id, country = _party_tax_id(party)
        group = (doc.meta or {}).get("jpk_group")
        foreign = doc.source_type in PURCHASE_SOURCES and group in IMPORT_GROUPS
        common = {
            "document_id": doc.id,
            "number": doc.number,
            "ksef_number": (doc.meta or {}).get("ksef_number"),
            "issue_date": issue_date,
            "counterparty": party.name if party else doc.description,
            "tax_id": tax_id,
            "country": country,
            "correction": found.net < 0 or found.vat < 0 or found.output < 0,
            "payroll": doc.sensitivity is not None,
            "counterparty_id": doc.counterparty_id,
        }
        if found.vat or found.output == 0:
            rows.append(
                Row(
                    **common,
                    # Faktura zagraniczna: data otrzymania z formularza
                    # (DataWplywu w JPK, gdy inna niż wystawienia; dokumenty
                    # sprzed pola — data dowodu), okres = miesiąc usługi.
                    day=(date.fromisoformat(received) if received else issue_date)
                    if foreign
                    else doc.op_date,
                    net=found.net,
                    vat=found.vat,
                    amounts={found.key: (found.net, found.vat)},
                )
            )
        if found.output:
            self_rows.append(
                Row(
                    **common,
                    # Import usług: data wykonania usługi (DataSprzedazy w JPK).
                    day=doc.op_date,
                    net=found.net,
                    vat=found.output,
                    amounts={group: (found.net, found.output)} if foreign else {},
                    problem=None if foreign else SELF_ASSESSED,
                )
            )
    return rows, self_rows


async def _missing_sales(
    db: AsyncSession, start: date, end: date
) -> list[dict[str, Any]]:
    """Faktury sprzedaży z KSeF z okresem VAT w tym miesiącu bez FVS w księdze
    (w buforze albo zatwierdzonego) — np. zaliczka, kontrahent bez konta."""

    sale_day = func.coalesce(
        ClientSalesInvoice.sale_date, ClientSalesInvoice.issue_date
    )
    booked = select(LedgerDocument.source_id).where(
        LedgerDocument.source_type == SALES_SOURCE,
        LedgerDocument.reversed_by_id.is_(None),
        LedgerDocument.reverses_id.is_(None),
        LedgerDocument.source_id.is_not(None),
    )
    rows = (
        await db.scalars(
            select(ClientSalesInvoice)
            .where(
                or_(
                    and_(
                        ClientSalesInvoice.invoice_kind != "correction",
                        sale_day >= start,
                        sale_day < end,
                    ),
                    and_(
                        ClientSalesInvoice.invoice_kind == "correction",
                        ClientSalesInvoice.issue_date >= start,
                        ClientSalesInvoice.issue_date < end,
                    ),
                ),
                or_(
                    ClientSalesInvoice.gross_amount != 0,
                    func.coalesce(ClientSalesInvoice.vat_amount, 0) != 0,
                ),
                cast(ClientSalesInvoice.id, String).not_in(booked),
            )
            .order_by(ClientSalesInvoice.issue_date, ClientSalesInvoice.id)
        )
    ).all()
    return [
        {
            "number": item.invoice_number,
            "detail": (
                "zaliczka — bez dokumentu do czasu reguły zaliczek (K3)"
                if item.invoice_type in sources.ADVANCE_TYPES
                else "bez dokumentu FVS — zaksięguj miesiąc w Źródłach"
            ),
        }
        for item in rows
    ]


async def _missing_costs(
    db: AsyncSession, start: date, viewer: Viewer
) -> list[dict[str, Any]]:
    """Faktury kosztowe z wpływem w tym miesiącu bez FVZ (kolejka kosztów E2)."""

    bounds = local_month_bounds(start)
    booked = select(LedgerDocument.source_id).where(
        LedgerDocument.source_type == COST_SOURCE,
        LedgerDocument.reversed_by_id.is_(None),
        LedgerDocument.reverses_id.is_(None),
        LedgerDocument.source_id.is_not(None),
    )
    src = costs._sources()
    rows = (
        await db.execute(
            costs._select(src).where(
                FinanceCostEntry.received_at >= bounds.start_utc,
                FinanceCostEntry.received_at < bounds.end_utc,
                FinanceCostEntry.stage.not_in(COST_SKIPPED_STAGES),
                FinanceCostEntry.category.not_in(COST_SKIPPED_CATEGORIES),
                cast(FinanceCostEntry.id, String).not_in(booked),
                *costs._payroll_scope(viewer.payroll),
            )
        )
    ).all()
    return [
        {
            "number": row.invoice_number or row.ksef_number or "—",
            "detail": (
                "gotowa w kolejce kosztów — zaksięguj miesiąc w Źródłach"
                if row[0].stage in sources.COST_STAGES
                else "w kolejce kosztów (E2) — bez dekretu"
            ),
        }
        for row in rows
    ]


async def output_accounts(db: AsyncSession, settings: LedgerSettings) -> list[str]:
    """Konta VAT należnego: konto sprzedaży z ustawień, konto importu usług
    z kolejki kosztów (226 z arkusza) i konta z dekretów FVZ zapisane przez
    źródło w ``meta.output_account`` (rejestr liczy je jako VAT należny, więc
    rozliczenie VAT i „spoza rejestru” też — audyt 24.11.2026)."""

    found = [settings.sales.vat_account, posting_options.DEFAULT_OUTPUT_VAT_ACCOUNT]
    found += list(
        await db.scalars(
            select(LedgerDocument.meta["output_account"].astext)
            .where(LedgerDocument.meta.has_key("output_account"))
            .distinct()
        )
    )
    out: list[str] = []
    for item in found:
        if item and item not in out and item != settings.vat.input_account:
            out.append(item)
    return out


async def _outside(
    db: AsyncSession,
    start: date,
    end: date,
    settings: LedgerSettings,
    viewer: Viewer,
) -> list[dict[str, Any]]:
    """Zapisy na kontach VAT w zatwierdzonych dokumentach spoza rejestru."""

    accounts = [
        item
        for item in (
            *await output_accounts(db, settings),
            settings.vat.input_account,
        )
        if item
    ]
    if not accounts:
        return []
    on_vat = or_(
        *[
            or_(LedgerLine.account == item, LedgerLine.account.like(f"{item}-%"))
            for item in accounts
        ]
    )
    query = (
        select(
            LedgerDocument.id,
            LedgerDocument.number,
            LedgerDocument.doc_type,
            LedgerLine.account,
            LedgerLine.side,
            LedgerLine.amount,
        )
        .join(LedgerDocument, LedgerDocument.id == LedgerLine.document_id)
        .where(
            LedgerDocument.status == "approved",
            LedgerDocument.op_date >= start,
            LedgerDocument.op_date < end,
            on_vat,
            LedgerDocument.doc_type.not_in(OUTSIDE_OK),
            # NULL wprost: „NULL NOT IN (…)” to NULL (przegląd K4c-2).
            or_(
                LedgerDocument.source_type.is_(None),
                LedgerDocument.source_type.not_in(REGISTER_SOURCES),
            ),
            # Dokument ze stornem i samo storno się znoszą (przegląd K5a);
            # storno dokumentu z rejestru też tu nie należy.
            LedgerDocument.reversed_by_id.is_(None),
            LedgerDocument.reverses_id.is_(None),
        )
        .order_by(LedgerDocument.op_date, LedgerDocument.id)
    )
    if not viewer.payroll:
        query = query.where(LedgerDocument.sensitivity.is_(None))
    grouped: dict[int, dict[str, Any]] = {}
    for doc_id, number, doc_type, account, side, amount in (
        await db.execute(query)
    ).all():
        entry = grouped.setdefault(
            doc_id,
            {
                "id": doc_id,
                "number": number,
                "detail": doc_type,
                "amount": 0,
                "accounts": set(),
            },
        )
        entry["amount"] += int(amount) if side == "debit" else -int(amount)
        entry["accounts"].add(account)
    return [
        {
            "id": entry["id"],
            "number": entry["number"],
            "detail": f"{entry['detail']} · {', '.join(sorted(entry['accounts']))}",
            "amount": entry["amount"],
        }
        for entry in grouped.values()
    ]


def _row_payload(row: Row) -> dict[str, Any]:
    return {
        "document_id": row.document_id,
        "number": row.number,
        "ksef_number": row.ksef_number,
        "issue_date": row.issue_date.isoformat() if row.issue_date else None,
        "date": row.day.isoformat(),
        "counterparty": row.counterparty,
        "tax_id": row.tax_id,
        "country": row.country,
        "net": row.net,
        "vat": row.vat,
        "groups": [
            {"key": key, "net": net, "vat": vat}
            for key, (net, vat) in row.amounts.items()
        ],
        "correction": row.correction,
        "payroll": row.payroll,
        "problem": row.problem,
        "counterparty_id": row.counterparty_id,
        "markers": list(row.markers),
        "corrected_month": row.corrected_month,
    }


def _issue(kind: str, label: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "kind": kind,
        "label": label,
        "count": len(items),
        "items": items[:LISTED_MAX],
    }


async def registers(
    db: AsyncSession,
    viewer: Viewer,
    settings: LedgerSettings,
    *,
    year: int,
    month: int,
) -> dict[str, Any]:
    """Rejestry VAT miesiąca: wiersze, sumy grup (pola JPK), do sprawdzenia."""

    if not 1 <= month <= 12:
        raise LedgerError("Niepoprawny miesiąc.", status=422)
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    docs = await _documents(db, start, end, viewer, status="approved")
    lines = await _lines(db, [doc.id for doc in docs])
    sales_rows = await _sales_rows(
        db, [doc for doc in docs if doc.source_type == SALES_SOURCE], lines, settings
    )
    purchase_rows, self_rows = await _purchase_rows(
        db,
        [doc for doc in docs if doc.source_type in PURCHASE_SOURCES],
        lines,
        settings,
    )
    sales_rows += self_rows

    drafts = await _documents(db, start, end, viewer, status="draft")
    issues = [
        _issue(
            "rates",
            "Wiersze bez pola JPK — stawka albo odwrotne obciążenie do sprawdzenia",
            [
                {"id": row.document_id, "number": row.number, "detail": row.problem}
                for row in sales_rows
                if row.problem
            ],
        ),
        _issue(
            "missing_sales",
            "Faktury sprzedaży z KSeF bez dokumentu w księdze",
            await _missing_sales(db, start, end),
        ),
        _issue(
            "drafts",
            "FVS i FVZ w buforze — rejestr liczy tylko zatwierdzone",
            [
                {"id": doc.id, "number": doc.number, "detail": doc.doc_type}
                for doc in drafts
            ],
        ),
        _issue(
            "missing_costs",
            "Faktury kosztowe z wpływem w tym miesiącu bez FVZ",
            await _missing_costs(db, start, viewer),
        ),
        _issue(
            "outside",
            "Zapisy na kontach VAT spoza rejestru",
            await _outside(db, start, end, settings, viewer),
        ),
    ]
    hidden = False
    if not viewer.payroll:
        hidden = bool(
            await db.scalar(
                select(func.count())
                .select_from(LedgerDocument)
                .where(
                    LedgerDocument.source_type == COST_SOURCE,
                    LedgerDocument.sensitivity.is_not(None),
                    LedgerDocument.reversed_by_id.is_(None),
                    LedgerDocument.op_date >= start,
                    LedgerDocument.op_date < end,
                )
            )
        )
    return {
        "year": year,
        "month": month,
        "accounts": {
            "output_account": settings.sales.vat_account,
            "input_account": settings.vat.input_account,
            "intake_account": settings.assets.intake_account,
            "foreign_account": settings.vat.foreign_account,
            "rounding_gain_account": settings.vat.rounding_gain_account,
            "rounding_loss_account": settings.vat.rounding_loss_account,
        },
        "sales": [_row_payload(row) for row in sales_rows],
        "purchases": [_row_payload(row) for row in purchase_rows],
        "summary": summarize(sales_rows, purchase_rows),
        "issues": [item for item in issues if item["count"]],
        "payroll_hidden": hidden,
        "can_edit_accounts": viewer.admin,
    }


#: Znaczniki JPK_V7M per kontrahent (K5b-2) — opisy z broszury MF (skrót).
MARKER_LABELS: dict[str, str] = {
    "GTU_01": "Napoje alkoholowe",
    "GTU_02": "Paliwa (art. 103 ust. 5aa)",
    "GTU_03": "Oleje opałowe i smarowe",
    "GTU_04": "Wyroby tytoniowe",
    "GTU_05": "Odpady (zał. 15)",
    "GTU_06": "Urządzenia elektroniczne (zał. 15)",
    "GTU_07": "Pojazdy i części",
    "GTU_08": "Metale szlachetne i nieszlachetne",
    "GTU_09": "Leki i wyroby medyczne",
    "GTU_10": "Budynki, budowle i grunty",
    "GTU_11": "Uprawnienia do emisji gazów",
    "GTU_12": "Usługi niematerialne (doradcze, prawne, zarządcze, marketingowe…)",
    "GTU_13": "Usługi transportowe i magazynowe",
    "TP": "Powiązania nabywcy z dostawcą (art. 32 ust. 2 pkt 1)",
}
assert set(MARKER_LABELS) == set(MARKERS)


def _marked_payload(
    party: FinanceCounterparty, markers: tuple[str, ...]
) -> dict[str, Any]:
    tax_id, country = _party_tax_id(party)
    return {
        "counterparty_id": party.id,
        "name": party.name,
        "tax_id": tax_id,
        "country": country,
        "markers": list(markers),
    }


async def markers(
    db: AsyncSession, viewer: Viewer, settings: LedgerSettings
) -> dict[str, Any]:
    """Kontrahenci ze znacznikami GTU/TP (do faktur sprzedaży w JPK)."""

    ids = list(settings.vat_markers)
    parties = (
        list(
            (
                await db.scalars(
                    select(FinanceCounterparty).where(FinanceCounterparty.id.in_(ids))
                )
            ).all()
        )
        if ids
        else []
    )
    items = [
        _marked_payload(party, settings.vat_markers[party.id])
        for party in sorted(parties, key=lambda item: (item.name.lower(), item.id))
    ]
    return {
        "items": items,
        "labels": [{"key": key, "label": MARKER_LABELS[key]} for key in MARKERS],
        "can_edit": viewer.approver,
    }


async def marked_item(
    db: AsyncSession, settings: LedgerSettings, counterparty_id: int
) -> dict[str, Any]:
    party = await db.get(FinanceCounterparty, counterparty_id)
    if party is None:  # pragma: no cover — zapis sprawdza kontrahenta
        raise LedgerError("Nie ma takiego kontrahenta w kartotece.", status=404)
    return _marked_payload(party, settings.vat_markers.get(counterparty_id, ()))
