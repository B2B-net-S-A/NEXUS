"""Zakup zagraniczny bez KSeF (K5b-2): import usług z formularza w zakładce VAT.

Decyzje Artura z 15.11.2026 (``docs/claude/finanse-insights/ksiega-nexusa-k5-vat.md``):
faktury LinkedIn, Google, Microsoft, Cognism i podobne wpisuje się ręcznie
w Księgowości, a nowego dostawcę formularz zakłada w kartotece kontrahentów.

* **Dostawca** z kartoteki (VAT UE, numer zagraniczny albo sam ID Symfonii) z
  kontem rozrachunkowym (``cost_account`` — jak w dekrecie kosztów E2). Nowy:
  nazwa, kraj, numer VAT UE albo zagraniczny numer podatkowy, opcjonalnie ID
  Symfonii; konto ``<konto z ustawień VAT>-NNN`` (pierwszy wolny numer, można
  wpisać inny — np. ten z Symfonii). Wiersz bez ``imported_at`` to dostawca
  z formularza; import kartoteki z eBI24 pilnuje, żeby go nie zdublować.
* **Kwoty**: netto w walucie × kurs średni NBP z ostatniego dnia roboczego
  przed obowiązkiem podatkowym (art. 31a ust. 1) — z ``fx_rates``, bez sieci;
  brak kursu z tego dnia = odmowa. VAT = netto w PLN × stawka, do grosza.
* **Okres** = miesiąc wykonania usługi (obowiązek podatkowy, art. 19a) — data
  operacji dokumentu; data wystawienia faktury idzie do JPK jako data dowodu.
* **Dokument FVZ w buforze** (zatwierdza lista „Księgowi”), korekta (netto
  < 0) odwraca strony:

  - Wn konto kosztu — netto (bez odliczenia: netto + VAT),
  - Wn VAT naliczony — VAT (przy odliczeniu),
  - Ma VAT należny — VAT,
  - Ma rozrachunek z dostawcą — netto, w walucie faktury.

* **Grupa JPK** z dostawcy: numer VAT UE (bez XI — Irlandia Północna to VAT UE
  tylko dla towarów; także numer z prefiksem kraju UE zapisany w kartotece jako
  „inny”) = usługa od podatnika VAT z UE, art. 28b → K_29/K_30; reszta →
  K_27/K_28. Zapisana w dokumencie (``meta.jpk_group``).
* **Kraj** nowego dostawcy ze słownika krajów MF (``KodyKrajow`` z XSD JPK; „UK”
  = GB, „EL” = GR) — kod spoza słownika blokował plik JPK, a kraju w kartotece
  się nie edytuje (przegląd K5b-2).
* **Rozliczenie na „5”**: koszt z dokumentu idzie na koszty ogólne (OG) —
  ``allocation.py``.
* Jedna faktura dostawcy = jeden dokument: źródło ``foreign_purchase``
  z identyfikatorem dostawcy i skrótem numeru faktury.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import lru_cache
from typing import Any, Optional

from lxml import etree
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance_ledger import FinanceCounterparty
from app.models.fx_rate import FxRate
from app.models.ledger import LedgerDocument, LedgerLine
from app.services.finance_ledger import identifiers, posting
from app.services.finance_ledger.costs import LedgerError
from app.services.finance_ledger_schema import NAME_MAX, SYMFONIA_ID_MAX
from app.services.ledger import documents, engine, jpk
from app.services.ledger.documents import DocumentSpec, Viewer
from app.services.ledger.engine import LineIn
from app.services.ledger.settings import LedgerSettings
from app.services.ledger.vat import FOREIGN_SOURCE
from app.services.ledger_schema import DESCRIPTION_MAX, LINE_TEXT_MAX, NUMBER_MAX

VAT_RATES: dict[str, Decimal] = {
    "23": Decimal("0.23"),
    "8": Decimal("0.08"),
    "5": Decimal("0.05"),
}
DEDUCTIONS: tuple[str, ...] = ("full", "none")
#: Netto faktury w walucie (grosze): do 10 mld.
NET_MAX = 10**12
#: Prefiksy VAT UE tylko dla towarów (usługa = jak spoza UE).
GOODS_ONLY_PREFIXES: tuple[str, ...] = ("XI",)
SUPPLIERS_MAX = 500
LISTED_MAX = 200
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
#: Kody spoza słownika MF wpisywane z przyzwyczajenia (Wielka Brytania, Grecja).
COUNTRY_ALIASES = {"UK": "GB", "EL": "GR"}
_XSD = "{http://www.w3.org/2001/XMLSchema}"
#: Kraj ISO → prefiks numeru VAT UE (Grecja: GR → EL).
_VAT_PREFIX = {"GR": "EL"}
STATUS_LABELS = {"draft": "w buforze", "approved": "zatwierdzony"}

NO_FOREIGN_ACCOUNT = (
    "konto rozrachunków z dostawcami zagranicznymi (zakładka VAT → Konta, "
    "administrator) — bez niego formularz nie założy nowego dostawcy"
)


# ── Reguły bez bazy ──────────────────────────────────────────────────────────


def jpk_group(id_type: Optional[str], id_value: Optional[str]) -> str:
    """K_29/K_30 (``imp_28b``) dla podatnika VAT z UE, reszta K_27/K_28.

    Numer z prefiksem kraju UE zapisany jako „inny” (import z eBI24 bywa z takim
    typem) to też numer VAT UE."""

    value = (id_value or "").upper()
    prefix = value[:2]
    eu_number = (
        prefix in identifiers.EU_PREFIXES
        and prefix not in GOODS_ONLY_PREFIXES
        and len(value) > 4
    )
    if id_type in ("vat_eu", "other") and eu_number:
        return "imp_28b"
    return "imp_other"


@lru_cache(maxsize=1)
def mf_countries() -> frozenset[str]:
    """Kody krajów ze słownika MF (``KodyKrajow`` obok schematu JPK)."""

    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    tree = etree.parse(str(jpk.SCHEMA.with_name("KodyKrajow_v13-0E.xsd")), parser)
    return frozenset(
        node.get("value")
        for node in tree.iter(f"{_XSD}enumeration")
        if node.get("value")
    )


def clean_country(raw: object) -> str:
    """Kraj dostawcy: kod ISO ze słownika MF; Polska — odmowa (faktura w KSeF)."""

    code = _text(raw, 4).upper()
    code = COUNTRY_ALIASES.get(code, code)
    if not _COUNTRY.fullmatch(code) or code not in mf_countries():
        raise LedgerError(
            f"Kraj dostawcy: „{code[:4]}” nie ma w słowniku krajów MF — podaj kod "
            "ISO, np. IE, DE, GB, US.",
            status=422,
        )
    if code == "PL":
        raise LedgerError(
            "Dostawca z Polski wystawia fakturę w KSeF — zaksięgujesz ją "
            "z kolejki kosztów.",
            status=422,
        )
    return code


def source_key(supplier_id: int, number: str) -> str:
    """Źródło dokumentu: dostawca + skrót numeru faktury (wielkość liter
    i spacje bez znaczenia) — mieści się w ``source_id``."""

    folded = "".join(number.split()).upper()
    return f"{supplier_id}:{hashlib.sha256(folded.encode()).hexdigest()[:32]}"


@dataclass(frozen=True)
class Figures:
    """Kwoty dokumentu w groszach: PLN (netto, VAT) i netto w walucie."""

    net: int
    vat: int
    net_cur: int


def figures(net_cur: Decimal, *, rate: Optional[Decimal], vat_rate: str) -> Figures:
    cur = posting.grosze(net_cur)
    net = posting.grosze(net_cur * rate) if rate is not None else cur
    vat = int(
        (Decimal(net) * VAT_RATES[vat_rate]).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    return Figures(net, vat, cur)


def decree(
    amounts: Figures,
    *,
    currency: str,
    deduction: str,
    cost_account: str,
    input_account: str,
    output_account: str,
    supplier_account: str,
    supplier_id: int,
    text: str,
) -> list[LineIn]:
    """Pozycje FVZ importu usług (kwoty dodatnie; korekta = strony odwrócone)."""

    debit, credit = ("debit", "credit") if amounts.net > 0 else ("credit", "debit")
    net, vat = abs(amounts.net), abs(amounts.vat)
    full = deduction == "full"
    label = text[:LINE_TEXT_MAX]
    lines = [LineIn(debit, cost_account, net if full else net + vat, label)]
    if vat and full:
        lines.append(LineIn(debit, input_account, vat, label))
    if vat:
        lines.append(LineIn(credit, output_account, vat, label))
    foreign = currency != "PLN"
    lines.append(
        LineIn(
            credit,
            supplier_account,
            net,
            label,
            counterparty_id=supplier_id,
            currency=currency if foreign else "PLN",
            amount_cur=abs(amounts.net_cur) if foreign else None,
        )
    )
    return lines


def _text(raw: object, limit: int) -> str:
    return " ".join(str(raw or "").split())[:limit]


def _date(raw: object, label: str, today: date) -> date:
    if isinstance(raw, date):
        value = raw
    else:
        try:
            value = date.fromisoformat(str(raw or ""))
        except ValueError:
            raise LedgerError(f"{label}: podaj datę.", status=422) from None
    if value > today:
        raise LedgerError(f"{label} nie może być z przyszłości.", status=422)
    return value


def _net(raw: object) -> Decimal:
    try:
        value = Decimal(str(raw).replace(",", ".").replace(" ", ""))
    except (InvalidOperation, ValueError):
        raise LedgerError(
            "Kwota netto: podaj liczbę, np. 1234.56.", status=422
        ) from None
    if not value.is_finite() or value != value.quantize(Decimal("0.01")):
        raise LedgerError("Kwota netto: najwyżej dwa miejsca po przecinku.", status=422)
    if value == 0:
        raise LedgerError(
            "Kwota netto nie może być zerem (korekta — kwota ujemna).", status=422
        )
    if abs(posting.grosze(value)) > NET_MAX:
        raise LedgerError("Kwota netto jest za duża.", status=422)
    return value


@dataclass(frozen=True)
class Invoice:
    number: str
    issue_date: date
    service_date: date
    currency: str
    net: Decimal
    vat_rate: str
    deduction: str
    cost_account: str
    description: str


def clean_invoice(raw: dict[str, Any], *, today: date) -> Invoice:
    """Pola faktury z formularza (zdania błędów po polsku, 422)."""

    number = _text(raw.get("number"), NUMBER_MAX + 1)
    if not number:
        raise LedgerError("Podaj numer faktury dostawcy.", status=422)
    if len(number) > NUMBER_MAX:
        raise LedgerError(f"Numer faktury: najwyżej {NUMBER_MAX} znaków.", status=422)
    currency = _text(raw.get("currency"), 8).upper()
    if not _CURRENCY.fullmatch(currency):
        raise LedgerError("Waluta: kod z trzech liter, np. EUR.", status=422)
    vat_rate = str(raw.get("vat_rate") or "")
    if vat_rate not in VAT_RATES:
        raise LedgerError("Stawka VAT: 23, 8 albo 5%.", status=422)
    deduction = str(raw.get("deduction") or "")
    if deduction not in DEDUCTIONS:
        raise LedgerError(
            "Odliczenie: pełne albo bez odliczenia VAT naliczonego.", status=422
        )
    return Invoice(
        number=number,
        issue_date=_date(raw.get("issue_date"), "Data wystawienia", today),
        service_date=_date(raw.get("service_date"), "Data wykonania usługi", today),
        currency=currency,
        net=_net(raw.get("net")),
        vat_rate=vat_rate,
        deduction=deduction,
        cost_account=posting.clean_account(raw.get("cost_account"), "Konto kosztu"),
        description=_text(raw.get("description"), DESCRIPTION_MAX),
    )


def clean_tax_id(raw: Optional[str], country: str) -> Optional[identifiers.Identifier]:
    """Numer dostawcy: z kraju UE = VAT UE (prefiks kraju dopisany, gdy go
    nie ma), spoza UE = numer zagraniczny; polski NIP i PESEL — odmowa."""

    compact = "".join(ch for ch in (raw or "").upper() if ch.isalnum())
    if not compact:
        return None
    prefix = _VAT_PREFIX.get(country, country)
    if prefix in identifiers.EU_PREFIXES:
        value = compact if compact.startswith(prefix) else prefix + compact
        kind = "VAT UE"  # słowo typu jak w pliku kartoteki
    else:
        value, kind = compact, None
    try:
        found = identifiers.normalize(value, kind)
    except identifiers.IdentifierError as exc:
        raise LedgerError(f"Numer dostawcy: {exc}", status=422) from exc
    if found is not None and found.type in ("nip", "pesel"):
        raise LedgerError(
            "To polski numer — faktura dostawcy z Polski przychodzi przez KSeF "
            "(kolejka kosztów).",
            status=422,
        )
    return found


# ── Kartoteka ────────────────────────────────────────────────────────────────


def _foreign_party():
    """Kontrahent, który może być dostawcą zagranicznym (bez NIP-u i PESEL-u)."""

    return or_(
        FinanceCounterparty.id_type.in_(("vat_eu", "other")),
        and_(
            FinanceCounterparty.id_type.is_(None),
            FinanceCounterparty.country.is_not(None),
            FinanceCounterparty.country != "PL",
        ),
    )


def _supplier_payload(row: FinanceCounterparty) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "country": row.country,
        "tax_id": row.id_value,
        "symfonia_partner_id": row.symfonia_partner_id,
        "account": row.cost_account,
        "group": jpk_group(row.id_type, row.id_value),
        "from_form": row.imported_at is None,
    }


async def suppliers(db: AsyncSession) -> list[dict[str, Any]]:
    rows = await db.scalars(
        select(FinanceCounterparty)
        .where(_foreign_party())
        .order_by(func.lower(FinanceCounterparty.name), FinanceCounterparty.id)
        .limit(SUPPLIERS_MAX)
    )
    return [_supplier_payload(row) for row in rows.all()]


async def next_account(db: AsyncSession, parent: str) -> str:
    """Pierwszy wolny numer analityki pod kontem dostawców zagranicznych
    (kartoteka i zapisy księgi) — największy + 1."""

    prefix = f"{parent}-"
    taken = [
        *(
            await db.scalars(
                select(FinanceCounterparty.cost_account).where(
                    FinanceCounterparty.cost_account.like(f"{prefix}%")
                )
            )
        ).all(),
        *(
            await db.scalars(
                select(LedgerLine.account)
                .where(LedgerLine.account.like(f"{prefix}%"))
                .distinct()
            )
        ).all(),
    ]
    numbers = [
        int(tail)
        for account in taken
        if account and (tail := account[len(prefix) :]).isdigit()
    ]
    return f"{prefix}{max(numbers, default=0) + 1}"


async def _supplier_account(
    db: AsyncSession, settings: LedgerSettings, raw: Optional[str]
) -> str:
    parent = settings.vat.foreign_account
    if not parent:
        raise LedgerError(f"Ustaw {NO_FOREIGN_ACCOUNT}.", status=422)
    if not (raw or "").strip():
        return await next_account(db, parent)
    account = posting.clean_account(raw, "Konto rozrachunkowe dostawcy")
    resolved, _ = engine.resolve(account, await documents.load_plan(db))
    if (
        not account.startswith(f"{parent}-")
        or resolved is None
        or not resolved.analytic
        or resolved.plan.number != parent
    ):
        raise LedgerError(
            f"Konto rozrachunkowe dostawcy to analityka konta {parent} "
            f"(np. {parent}-1).",
            status=422,
        )
    return account


async def create_supplier(
    db: AsyncSession,
    settings: LedgerSettings,
    raw: dict[str, Any],
    *,
    actor_id: int,
) -> FinanceCounterparty:
    """Nowy dostawca zagraniczny w kartotece (bez commita)."""

    name = _text(raw.get("name"), NAME_MAX + 1)
    if len(name) < 2:
        raise LedgerError("Podaj nazwę dostawcy.", status=422)
    if len(name) > NAME_MAX:
        raise LedgerError(f"Nazwa dostawcy: najwyżej {NAME_MAX} znaków.", status=422)
    country = clean_country(raw.get("country"))
    tax_id = clean_tax_id(raw.get("tax_id"), country)
    symfonia = _text(raw.get("symfonia_partner_id"), SYMFONIA_ID_MAX + 1) or None
    if symfonia and len(symfonia) > SYMFONIA_ID_MAX:
        raise LedgerError(
            f"ID Symfonii: najwyżej {SYMFONIA_ID_MAX} znaków.", status=422
        )
    if tax_id is None and symfonia is None:
        raise LedgerError(
            "Podaj numer VAT (podatkowy) dostawcy albo ID partnera w Symfonii.",
            status=422,
        )
    if tax_id is not None:
        same = await db.scalar(
            select(FinanceCounterparty).where(
                FinanceCounterparty.id_type == tax_id.type,
                FinanceCounterparty.id_value == tax_id.value,
            )
        )
        if same is not None:
            raise LedgerError(
                f"Dostawca z numerem {tax_id.value} jest już w kartotece "
                f"(„{same.name}”) — wybierz go z listy.",
                status=409,
            )
    if symfonia is not None:
        owner = await db.scalar(
            select(FinanceCounterparty.name).where(
                FinanceCounterparty.symfonia_partner_id == symfonia
            )
        )
        if owner is not None:
            raise LedgerError(
                f"ID Symfonii {symfonia} ma już kontrahent „{owner}”.", status=409
            )
    folded = identifiers.fold(name)
    for other_id, other_name in (
        await db.execute(select(FinanceCounterparty.id, FinanceCounterparty.name))
    ).all():
        if identifiers.fold(other_name) == folded:
            raise LedgerError(
                f"W kartotece jest już kontrahent „{other_name}” — wybierz go "
                "z listy albo popraw nazwę.",
                status=409,
            )
    account = await _supplier_account(db, settings, raw.get("account"))
    used = await db.scalar(
        select(FinanceCounterparty.name).where(
            FinanceCounterparty.cost_account == account
        )
    )
    if used is not None:
        raise LedgerError(f"Konto {account} ma już kontrahent „{used}”.", status=409)
    row = FinanceCounterparty(
        id_type=tax_id.type if tax_id else None,
        id_value=tax_id.value if tax_id else None,
        name=name,
        country=country,
        symfonia_partner_id=symfonia,
        cost_account=account,
        updated_by=actor_id,
    )
    db.add(row)
    await db.flush()
    return row


async def _existing_supplier(db: AsyncSession, supplier_id: int) -> FinanceCounterparty:
    row = await db.get(FinanceCounterparty, supplier_id)
    if row is None:
        raise LedgerError("Nie ma takiego kontrahenta w kartotece.", status=422)
    if row.id_type in ("nip", "pesel"):
        raise LedgerError(
            f"„{row.name}” to kontrahent z Polski — jego faktury przychodzą "
            "przez KSeF (kolejka kosztów).",
            status=422,
        )
    if not row.cost_account:
        raise LedgerError(
            f"„{row.name}” nie ma konta rozrachunkowego — uzupełnij konto "
            "w Finanse → Kontrahenci.",
            status=422,
        )
    return row


# ── Kurs i dokument ──────────────────────────────────────────────────────────


async def nbp_rate(db: AsyncSession, currency: str, day: date) -> Optional[Decimal]:
    value = await db.scalar(
        select(FxRate.rate_to_pln).where(
            FxRate.currency == currency, FxRate.effective_date == day
        )
    )
    return Decimal(value) if value is not None else None


def _item(doc: LedgerDocument, supplier: Optional[str]) -> dict[str, Any]:
    meta = doc.meta or {}
    return {
        "id": doc.id,
        "number": doc.number,
        "status": doc.status,
        "status_label": STATUS_LABELS.get(doc.status, doc.status),
        "supplier_id": doc.counterparty_id,
        "supplier": supplier,
        "issue_date": meta.get("issue_date"),
        "service_date": doc.op_date.isoformat(),
        "currency": doc.currency,
        "rate": str(doc.fx_rate) if doc.fx_rate is not None else None,
        "rate_day": doc.fx_date.isoformat() if doc.fx_date else None,
        "net_cur": meta.get("net_cur"),
        "net": meta.get("net"),
        "vat": meta.get("vat"),
        "vat_rate": meta.get("vat_rate"),
        "deduction": meta.get("deduction"),
        "group": meta.get("jpk_group"),
    }


async def create(
    db: AsyncSession,
    viewer: Viewer,
    settings: LedgerSettings,
    raw: dict[str, Any],
    *,
    today: date,
) -> dict[str, Any]:
    """FVZ importu usług w buforze (bez commita); nowy dostawca — do kartoteki."""

    invoice = clean_invoice(raw, today=today)
    if raw.get("supplier_id") is not None and raw.get("new_supplier"):
        raise LedgerError(
            "Wybierz dostawcę z listy albo dodaj nowego — nie oba naraz.", status=422
        )
    if raw.get("supplier_id") is not None:
        supplier = await _existing_supplier(db, int(raw["supplier_id"]))
    elif isinstance(raw.get("new_supplier"), dict):
        supplier = await create_supplier(
            db, settings, raw["new_supplier"], actor_id=viewer.user_id
        )
    else:
        raise LedgerError("Wybierz dostawcę z listy albo dodaj nowego.", status=422)
    source_id = source_key(supplier.id, invoice.number)
    existing = await db.scalar(
        select(LedgerDocument).where(
            LedgerDocument.source_type == FOREIGN_SOURCE,
            LedgerDocument.source_id == source_id,
            LedgerDocument.reversed_by_id.is_(None),
        )
    )
    if existing is not None:
        raise LedgerError(
            f"Faktura {invoice.number} od „{supplier.name}” jest już w księdze "
            f"({existing.number}, {STATUS_LABELS.get(existing.status, existing.status)}).",
            status=409,
        )
    rate: Optional[Decimal] = None
    rate_day: Optional[date] = None
    if invoice.currency != "PLN":
        rate_day = posting.rate_day(invoice.service_date)
        rate = await nbp_rate(db, invoice.currency, rate_day)
        if rate is None:
            raise LedgerError(
                f"Brak kursu NBP {invoice.currency} z {rate_day:%d.%m.%Y} (ostatni "
                "dzień roboczy przed wykonaniem usługi) — NEXUS pobiera tabelę NBP "
                "w dni robocze; spróbuj, gdy kurs będzie w NEXUSIE.",
                status=422,
            )
    amounts = figures(invoice.net, rate=rate, vat_rate=invoice.vat_rate)
    group = jpk_group(supplier.id_type, supplier.id_value)
    text = invoice.description or f"{supplier.name} {invoice.number}"
    lines = decree(
        amounts,
        currency=invoice.currency,
        deduction=invoice.deduction,
        cost_account=invoice.cost_account,
        input_account=settings.vat.input_account,
        output_account=settings.sales.vat_account,
        supplier_account=supplier.cost_account or "",
        supplier_id=supplier.id,
        text=text,
    )
    doc = await documents.create_draft(
        db,
        DocumentSpec(
            doc_type="FVZ",
            op_date=invoice.service_date,
            doc_date=invoice.issue_date,
            lines=lines,
            number=invoice.number,
            description=text[:DESCRIPTION_MAX],
            counterparty_id=supplier.id,
            currency=invoice.currency,
            fx_rate=rate,
            fx_date=rate_day,
            source_type=FOREIGN_SOURCE,
            source_id=source_id,
            meta={
                "source": "foreign",
                "issue_date": invoice.issue_date.isoformat(),
                "service_date": invoice.service_date.isoformat(),
                "jpk_group": group,
                "vat_rate": invoice.vat_rate,
                "deduction": invoice.deduction,
                "net_cur": amounts.net_cur,
                "net": amounts.net,
                "vat": amounts.vat,
            },
        ),
        actor_id=viewer.user_id,
    )
    return {
        "document": _item(doc, supplier.name),
        "supplier": _supplier_payload(supplier),
    }


async def _currencies(db: AsyncSession) -> list[str]:
    """Waluty z kursami NBP w NEXUSIE (lista w formularzu) i PLN."""

    found = (
        await db.scalars(select(FxRate.currency).distinct().order_by(FxRate.currency))
    ).all()
    return ["PLN", *[item for item in found if item != "PLN"]]


async def overview(
    db: AsyncSession,
    viewer: Viewer,
    settings: LedgerSettings,
    *,
    year: int,
    month: int,
) -> dict[str, Any]:
    """Zakupy zagraniczne miesiąca (dokumenty FVZ z formularza) i dane formularza."""

    if not 1 <= month <= 12:
        raise LedgerError("Niepoprawny miesiąc.", status=422)
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    rows = (
        await db.execute(
            select(LedgerDocument, FinanceCounterparty.name)
            .outerjoin(
                FinanceCounterparty,
                FinanceCounterparty.id == LedgerDocument.counterparty_id,
            )
            .where(
                LedgerDocument.source_type == FOREIGN_SOURCE,
                LedgerDocument.reversed_by_id.is_(None),
                LedgerDocument.reverses_id.is_(None),
                LedgerDocument.op_date >= start,
                LedgerDocument.op_date < end,
            )
            .order_by(LedgerDocument.op_date, LedgerDocument.id)
            .limit(LISTED_MAX)
        )
    ).all()
    parent = settings.vat.foreign_account
    return {
        "year": year,
        "month": month,
        "items": [_item(doc, name) for doc, name in rows],
        "suppliers": await suppliers(db),
        "foreign_account": parent,
        "next_account": await next_account(db, parent) if parent else None,
        "currencies": await _currencies(db),
        "vat_rates": list(VAT_RATES),
        "missing": [] if parent else [NO_FOREIGN_ACCOUNT],
    }
