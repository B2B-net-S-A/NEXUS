"""Dekret faktury kosztowej do Symfonii FK (E2): reguła, wyliczenie, korekta, kontrola.

Reguła dekretu (``finance_posting_rules``) dobiera się po kategorii wpisu
i opcjonalnie kontrahencie — reguła kontrahenta wygrywa z ogólną dla tej samej
kategorii. Wynik reguły: konto kosztu, konto VAT, odliczenie (100% / brak),
rejestr, typ dokumentu i wzór opisu. Rozrachunek bierzemy zawsze z kartoteki
kontrahenta (``finance_counterparties.cost_account``): brak kontrahenta albo
konta = dekret niekompletny.

Pozycje jak w eBI24 (kwoty w groszach, faktura ma jedną sumę netto i VAT —
źródła nie niosą rozbicia na stawki):

* Wn konto kosztu: netto (odliczenie 100%) albo brutto (bez odliczenia),
* Wn konto VAT: VAT (tylko przy odliczeniu 100% i VAT ≠ 0),
* Ma rozrachunek z kontrahentem: brutto.

Korekta (brutto < 0) odwraca strony. Faktura w walucie obcej: kwoty w PLN po
kursie NBP z ostatniego dnia roboczego przed datą wystawienia (kalendarz
``core/scheduling.is_business_day``, kurs z tabeli ``fx_rates`` bez wywołań
sieci) — brutto i VAT × kurs, netto jako różnica, żeby dekret się bilansował;
brak kursu z tego dnia = wada dekretu. Dekret pamięta walutę, kurs i dzień
kursu. Rozrachunek różny od brutto źródła (× kurs z dekretu) = wada „Kwoty
faktury zmieniły się po dekrecie”: źródło potrafi zmienić kwoty po dekrecie
(bliźniak z KSeF dla PDF-a, ``hr/ksef/sync._bind_twin``). Dekret powstaje przy przejściu do
„Zweryfikowane” i na żądanie („Przelicz”); przy „Gotowa do księgowania”
dekret wyliczany liczy się od nowa, a ręczny zostaje. Niekompletny dekret
blokuje „Gotowa do księgowania”. Po „Gotowa” i po zaksięgowaniu dekretu się
nie zmienia (najpierw „Cofnij”).

Opis faktury wg „Ogólnych założeń” głównej księgowej (18.11.2026,
``posting_options``): wybory z karty (typ, rejestr, konta netto / VAT / „5”,
procedura JPK, kurs i tabela NBP, data usługi) leżą w ``decree["choices"]``
i wygrywają z regułą. Samochód („Paliwo i leasingi”): koszt = netto + 1/2 VAT,
VAT = 1/2, rejestr w dwóch połowach (Zakup i „Rejestr NP VAT”), opcjonalnie
Wn 999 / Ma 902–903 na 1/2 brutto. Import usług i WNT: VAT liczony od netto
w PLN (Wn VAT naliczony / Ma VAT należny), rozrachunek = netto, dwa rejestry.
„5” to zapis równoległy na dokumencie (Wn 5xx / Ma 490); PK rozliczenia
kosztów (``ledger/allocation.py``) pomija takie faktury.
"""

from __future__ import annotations

import re
from zoneinfo import ZoneInfo
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ, business_date, is_business_day
from app.models.fx_rate import FxRate
from app.models.client_settlement import ClientContractorInvoice
from app.models.finance_ledger import FinanceCostEntry, FinanceCounterparty
from app.models.finance_posting import (
    FinanceAccount,
    FinancePostingBatch,
    FinancePostingRule,
)
from app.models.hr_approval import ApprovalDocument
from app.models.hr_payroll import PayrollPeriod
from app.models.hr_settlement import PayrollInvoice, PayrollSettlement
from app.services.finance_ledger.costs import (
    BOOKED_DETAIL,
    CATEGORY_LABELS,
    OWN_INVOICE_DETAIL,
    LedgerError,
    _event,
    _own_entry_ids,
    _payroll_scope,
)
from app.services.finance_ledger import posting_options as options
from app.services.finance_posting_schema import (
    ACCOUNT_MAX,
    DOC_TYPE_MAX,
    REGISTERS,
)

REGISTER_LABELS = {"purchase": "Zakup", "sale": "Sprzedaż"}
DEDUCTION_LABELS = {"full": "100%", "none": "brak", "partial": "50% (samochód)"}
KIND_LABELS = {
    "cost": "Koszt",
    "vat": "VAT",
    "counterparty": "Rozrachunek z kontrahentem",
    "vat_due": "VAT należny",
    "allocation": "Konto „5”",
    "allocation_offset": "Rozliczenie kosztów (490)",
    "offbalance": "Pozabilansowo (999)",
    "offbalance_offset": "Pozabilansowo (902–903)",
}
#: Zapis równoległy (``ZapisRownolegly`` w szablonie 4 Symfonii): Wn „5”, Ma 490.
PARALLEL_KINDS: tuple[str, ...] = ("allocation", "allocation_offset")
ACCOUNT_KIND_LABELS = {
    "cost": "koszt",
    "vat": "VAT",
    "settlement": "rozrachunek",
    "revenue": "przychód",
    # 0700 (K1): konta księgi spoza dekretu faktur (0xx, 1xx, 8xx…).
    "other": "inne",
}
SIDE_LABELS = {"debit": "Wn", "credit": "Ma"}
POSITION_KINDS: tuple[str, ...] = tuple(KIND_LABELS)
#: Rodzaje pozycji, których konto sprawdzamy w planie (rozrachunek to analityka).
PLAN_KINDS: tuple[str, ...] = tuple(
    kind for kind in KIND_LABELS if kind != "counterparty"
)
SIDES: tuple[str, ...] = ("debit", "credit")
PLACEHOLDERS: tuple[str, ...] = ("usługa", "MM", "RRRR", "numer", "kontrahent")
STANDARD_RATES: tuple[int, ...] = (23, 8, 5, 0)
POSITIONS_MAX = 30
DESCRIPTION_MAX = 255
#: Dekret zmienia się tylko przed „Gotowa do księgowania”.
EDITABLE_STAGES: tuple[str, ...] = ("new", "verified")

ACCOUNT_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z\-./]*")
DOC_TYPE_RE = re.compile(r"[0-9A-Z]{1,%d}" % DOC_TYPE_MAX)
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_CENT = Decimal("0.01")

NOT_COMPUTED = (
    "Dekret jeszcze nie powstał — powstaje przy weryfikacji albo po „Przelicz”."
)
NO_COUNTERPARTY = (
    "Sprzedawcy nie ma w kartotece kontrahentów — zaimportuj kartotekę z eBI24."
)
NO_AMOUNTS = "Faktura nie ma kwoty netto ani VAT — popraw dekret ręcznie."
AMOUNTS_CHANGED = "Kwoty faktury zmieniły się po dekrecie — Cofnij i przelicz."
NOT_EDITABLE = (
    "Dekret zmieniasz przed „Gotowa do księgowania” — najpierw cofnij fakturę o krok."
)


# ── Wartości (bez bazy) ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class AccountView:
    number: str
    name: str
    kind: str
    active: bool


@dataclass(frozen=True)
class RuleView:
    id: int
    category: str
    counterparty_id: Optional[int]
    cost_account: str
    vat_account: Optional[str]
    deduction: str
    register: str
    doc_type: str
    service_label: str
    description_template: str
    active: bool = True


@dataclass(frozen=True)
class DecreeInput:
    category: str
    counterparty_id: Optional[int]
    counterparty_name: Optional[str]
    counterparty_account: Optional[str]
    currency: str
    net: Optional[Decimal]
    vat: Optional[Decimal]
    gross: Optional[Decimal]
    invoice_number: Optional[str]
    #: Pierwszy dzień miesiąca usługi (źródło, potem data wystawienia, wpływu).
    period: Optional[date]
    issue_date: Optional[date] = None
    #: Kurs NBP waluty z dnia ``rate_day(issue_date)`` albo z dnia wybranego
    #: na karcie; kurs wpisany na karcie wygrywa (``None`` = brak w tabeli).
    fx_rate: Optional[Decimal] = None
    fx_date: Optional[date] = None
    #: Numer kontrahenta w kartotece Symfonii (końcówka konta 201-2-<nr>).
    counterparty_symfonia_id: Optional[str] = None
    #: Kontrahent zagraniczny (VAT UE, numer zagraniczny albo kraj ≠ PL).
    counterparty_foreign: bool = False
    counterparty_eu: bool = False
    #: Faktura z KSeF z adnotacją „metoda kasowa” (``Adnotacje/P_16``).
    cash_method: bool = False
    #: Data zakończenia dostawy/usługi (XML ``P_6``, koniec miesiąca usługi).
    service_date: Optional[date] = None
    #: Wybory z karty faktury (``posting_options.clean_choices``).
    choices: Optional[dict[str, Any]] = None


def rate_day(issued: date) -> date:
    """Ostatni dzień roboczy przed dniem wystawienia (dzień kursu NBP)."""

    day = issued - timedelta(days=1)
    zone = ZoneInfo(DEFAULT_TZ)
    while not is_business_day(datetime(day.year, day.month, day.day, 12, tzinfo=zone)):
        day -= timedelta(days=1)
    return day


def _rate_text(rate: Decimal) -> str:
    return format(Decimal(rate).normalize(), "f")


def grosze(value: Decimal) -> int:
    return int((Decimal(value) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money(amount: int) -> str:
    """Grosze → ``"1234.56"`` (API i pliki)."""

    sign = "-" if amount < 0 else ""
    return f"{sign}{abs(amount) // 100}.{abs(amount) % 100:02d}"


def money_pl(amount: int) -> str:
    """Grosze → ``"1 234,56 zł"`` (komunikaty)."""

    sign = "-" if amount < 0 else ""
    whole = f"{abs(amount) // 100:,}".replace(",", " ")
    return f"{sign}{whole},{abs(amount) % 100:02d} zł"


def vat_rate(net: Optional[Decimal], vat: Optional[Decimal]) -> Optional[str]:
    """Stawka z sumy netto i VAT, gdy pasuje do stawki ustawowej (±0,5 pp)."""

    if net is None or vat is None or net == 0:
        return None
    if vat == 0:
        return "0"
    ratio = abs(Decimal(vat) / Decimal(net) * 100)
    for rate in STANDARD_RATES:
        if abs(ratio - rate) <= Decimal("0.5"):
            return str(rate)
    return None


def clean_account(raw: Optional[str], label: str = "Konto") -> str:
    value = (raw or "").replace(" ", "")
    if not value:
        raise LedgerError(f"{label}: podaj numer konta.", status=422)
    if len(value) > ACCOUNT_MAX or not ACCOUNT_RE.fullmatch(value):
        raise LedgerError(
            f"{label}: niepoprawny numer konta „{(raw or '')[:40]}”.", status=422
        )
    return value


def clean_doc_type(raw: Optional[str]) -> str:
    value = (raw or "").strip().upper()
    if not DOC_TYPE_RE.fullmatch(value):
        raise LedgerError(
            f"Typ dokumentu: od 1 do {DOC_TYPE_MAX} liter albo cyfr (np. FVZ).",
            status=422,
        )
    return value


def validate_template(template: str) -> str:
    value = " ".join((template or "").split())
    if not value:
        raise LedgerError("Podaj wzór opisu (np. {usługa} {MM}/{RRRR}).", status=422)
    unknown = [name for name in _PLACEHOLDER.findall(value) if name not in PLACEHOLDERS]
    if unknown:
        allowed = ", ".join(f"{{{name}}}" for name in PLACEHOLDERS)
        raise LedgerError(
            f"Nieznane pole we wzorze: {{{unknown[0]}}}. Dozwolone: {allowed}.",
            status=422,
        )
    return value


def render_description(
    template: str,
    *,
    service: str,
    period: Optional[date],
    number: Optional[str],
    counterparty: Optional[str],
) -> str:
    """Opis z wzoru (``{usługa} {MM}/{RRRR}`` → „Usługi IT 10/2026”)."""

    values = {
        "usługa": service,
        "MM": f"{period.month:02d}" if period else "",
        "RRRR": f"{period.year}" if period else "",
        "numer": number or "",
        "kontrahent": counterparty or "",
    }
    text_ = _PLACEHOLDER.sub(
        lambda match: values.get(match.group(1), match.group(0)), template
    )
    return " ".join(text_.split())[:DESCRIPTION_MAX]


def match_rule(
    rules: Iterable[RuleView], category: str, counterparty_id: Optional[int]
) -> Optional[RuleView]:
    """Reguła kontrahenta wygrywa z ogólną tej samej kategorii; tylko aktywne."""

    general: Optional[RuleView] = None
    for rule in rules:
        if not rule.active or rule.category != category:
            continue
        if counterparty_id is not None and rule.counterparty_id == counterparty_id:
            return rule
        if rule.counterparty_id is None:
            general = rule
    return general


def _amounts(inp: DecreeInput) -> Optional[tuple[Decimal, Decimal, Decimal]]:
    net, vat, gross = inp.net, inp.vat, inp.gross
    if net is None and vat is None:
        return None
    if gross is None:
        if net is None or vat is None:
            return None
        gross = net + vat
    if net is None:
        net = gross - vat
    if vat is None:
        vat = gross - net
    return Decimal(net), Decimal(vat), Decimal(gross)


def _plan_problem(
    number: Optional[str], plan: dict[str, AccountView], label: str, ok: Any
) -> Optional[str]:
    if not number:
        return f"{label}: brak konta."
    account = plan.get(number)
    if account is None or not account.active:
        return f"Konta {number} ({label}) nie ma w planie kont albo jest wyłączone."
    if ok is not None and not ok(account.number, account.kind):
        return (
            f"Konto {number} ma w planie rodzaj "
            f"„{ACCOUNT_KIND_LABELS[account.kind]}” — nie pasuje do pola „{label}”."
        )
    return None


def account_fits(kind: str, account: AccountView, *, car: bool = False) -> bool:
    """Czy konto z planu pasuje do rodzaju pozycji dekretu."""

    if kind == "cost":
        return options.net_account_ok(account.number, account.kind, car=car)
    if kind in ("vat", "vat_due"):
        return options.vat_account_ok(account.number, account.kind)
    if kind == "allocation":
        return options.allocation_account_ok(account.number, account.kind)
    if kind == "offbalance_offset":
        return options.offbalance_account_ok(account.number)
    return True


def _rule_problems(rule: RuleView, plan: dict[str, AccountView]) -> list[str]:
    problems = []
    wanted = [("cost", rule.cost_account)]
    if rule.deduction == "full" and rule.vat_account:
        wanted.append(("vat", rule.vat_account))
    for kind, number in wanted:
        account = plan.get(number)
        if account is None or not account.active:
            problems.append(
                f"Konta {number} z reguły nie ma w planie kont albo jest wyłączone."
            )
        elif not account_fits(kind, account):
            problems.append(
                f"Konto {number} z reguły ma w planie rodzaj "
                f"„{ACCOUNT_KIND_LABELS[account.kind]}”, a reguła używa go jako "
                f"„{ACCOUNT_KIND_LABELS[kind]}”."
            )
    return problems


#: Konta rozrachunkowe z arkusza księgowej (``<prefiks>-2-<nr kontrahenta>``).
DOMESTIC_PLN = "201"
FOREIGN_SUPPLIER = "203"
DOMESTIC_CURRENCY = "205"
SETTLEMENT_PREFIXES: tuple[str, ...] = (
    DOMESTIC_PLN,
    FOREIGN_SUPPLIER,
    DOMESTIC_CURRENCY,
)


def settlement_account(
    stored: Optional[str],
    symfonia_id: Optional[str],
    *,
    foreign: bool,
    currency: str,
) -> Optional[str]:
    """Konto brutto (rozrachunek) z kartoteki kontrahenta.

    Arkusz księgowej: 201-2-<nr> dostawcy krajowi w PLN, 203-2-<nr> zagraniczni,
    205-2-<nr> krajowi w walucie; <nr> = numer kontrahenta w kartotece Symfonii
    (``symfonia_partner_id``). Konto z kartoteki spoza tych trzech (np. leasing
    244-1, dostawca z formularza K5b-2 pod 202-1) wygrywa — to świadome konto
    z Symfonii.
    """

    prefix = (
        FOREIGN_SUPPLIER
        if foreign
        else DOMESTIC_CURRENCY
        if currency != "PLN"
        else DOMESTIC_PLN
    )
    parts = (stored or "").split("-")
    if stored and parts[0] not in SETTLEMENT_PREFIXES:
        return stored
    number = (symfonia_id or "").strip()
    if number.isdigit():
        return f"{prefix}-2-{number}"
    if stored and len(parts) >= 3:
        return "-".join([prefix, *parts[1:]])
    return stored or None


def _half(value: int) -> tuple[int, int]:
    """Kwota na dwie połowy: pierwsza w dół (jak eBI24 przy 1/2 VAT)."""

    first = value // 2
    return first, value - first


def _position(
    kind: str,
    account: Optional[str],
    side: str,
    amount: int,
    *,
    amount_cur: Optional[int] = None,
    vat_rate: Optional[str] = None,
    deduction: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "account": account,
        "side": side,
        "amount": amount,
        "amount_cur": amount_cur,
        "vat_rate": vat_rate,
        "deduction": deduction,
        "parallel": kind in PARALLEL_KINDS,
    }


def _register(
    name: str,
    rate: Optional[str],
    net: int,
    vat: int,
    *,
    cur: Optional[tuple[int, int]] = None,
    output: bool = False,
    eu: bool = False,
    service: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "rate": rate,
        "net": net,
        "vat": vat,
        "gross": net + vat,
        "net_cur": cur[0] if cur else None,
        "vat_cur": cur[1] if cur else None,
        "gross_cur": cur[0] + cur[1] if cur else None,
        "output": output,
        "eu": eu,
        "service": service,
    }


def compute(
    inp: DecreeInput,
    rules: Iterable[RuleView],
    plan: dict[str, AccountView],
    *,
    now: datetime,
) -> dict[str, Any]:
    """Dekret z reguły i wyborów z karty; braki trafiają do ``problems``.

    Wybory (``inp.choices``, ``posting_options.clean_choices``) wygrywają
    z regułą. Bez reguły dekret powstaje, gdy Finanse wybrały konto netto.
    """

    choices = dict(inp.choices or {})
    base: dict[str, Any] = {
        "manual": False,
        "computed_at": now.isoformat(),
        "currency": inp.currency,
        "period": inp.period.isoformat() if inp.period else None,
        "choices": choices,
    }
    rule = match_rule(rules, inp.category, inp.counterparty_id)
    if rule is None and not choices.get("net_account"):
        label = CATEGORY_LABELS.get(inp.category, inp.category)
        return {
            **base,
            "rule_id": None,
            "register": "purchase",
            "doc_type": choices.get("doc_type") or "",
            "description": choices.get("description") or "",
            "positions": [],
            "registers": [],
            "problems": [
                f"Brak aktywnej reguły dekretu dla kategorii „{label}” — dodaj ją "
                "w „Plan kont” albo wybierz konto netto na karcie."
            ],
        }
    amounts = _amounts(inp)
    negative = bool(
        amounts and (amounts[2] < 0 or (amounts[2] == 0 and amounts[0] < 0))
    )
    rule_doc = rule.doc_type if rule else "FVZ"
    doc_type = choices.get("doc_type") or (
        "FKZ" if negative and rule_doc == "FVZ" else rule_doc
    )
    importing = doc_type in options.IMPORT_TYPES
    deduction = (
        "none"
        if doc_type in options.NO_DEDUCTION_TYPES
        else (rule.deduction if rule else "full")
    )
    car = bool(choices.get("car"))
    net_account = choices.get("net_account") or (rule.cost_account if rule else None)
    vat_account = choices.get("vat_account") or (
        rule.vat_account if rule and rule.vat_account else "221"
    )
    register = choices.get("register") or (
        options.DEFAULT_INPUT_REGISTER[doc_type]
        if importing
        else options.CORRECTION_REGISTER
        if negative
        else options.PURCHASE_REGISTER
    )
    output_register = choices.get("output_register") or (
        options.DEFAULT_OUTPUT_REGISTER[doc_type] if importing else None
    )
    output_vat_account = (
        choices.get("output_vat_account") or options.DEFAULT_OUTPUT_VAT_ACCOUNT
        if output_register
        else None
    )
    self_assessed = output_register is not None
    eu = choices.get("eu")
    eu = inp.counterparty_eu if eu is None else bool(eu)
    service = choices.get("service")
    service = (doc_type != "WNT") if service is None else bool(service)

    problems: list[str] = []
    if rule is not None and not choices.get("net_account"):
        problems += _rule_problems(rule, plan)
    elif choices.get("net_account"):
        if issue := _plan_problem(
            net_account,
            plan,
            "Konto netto",
            lambda number, kind: options.net_account_ok(number, kind, car=car),
        ):
            problems.append(issue)
    if deduction == "full" and (choices.get("vat_account") or rule is None):
        if issue := _plan_problem(
            vat_account, plan, "Konto VAT", options.vat_account_ok
        ):
            problems.append(issue)
    if self_assessed:
        if issue := _plan_problem(
            output_vat_account, plan, "Konto VAT należnego", options.vat_account_ok
        ):
            problems.append(issue)
    allocation = choices.get("allocation_account")
    if allocation:
        for number, label, ok in (
            (allocation, "Konto „5”", options.allocation_account_ok),
            (options.ALLOCATION_OFFSET, "Rozliczenie kosztów", None),
        ):
            if issue := _plan_problem(number, plan, label, ok):
                problems.append(issue)
    offbalance = choices.get("offbalance_account") if car else None
    if offbalance:
        for number, label in (
            (options.OFFBALANCE_DEBIT, "Pozabilansowo Wn"),
            (offbalance, "Pozabilansowo Ma"),
        ):
            if issue := _plan_problem(number, plan, label, None):
                problems.append(issue)
    if importing and not inp.counterparty_foreign and inp.counterparty_id is not None:
        problems.append(
            f"{doc_type} od kontrahenta z Polski — import usług i WNT są od "
            "kontrahentów zagranicznych; wybierz FVZ."
        )
    if car and self_assessed:
        problems.append("„Paliwo i leasingi” nie łączy się z importem usług ani WNT.")
    if car and deduction != "full":
        problems.append("„Paliwo i leasingi” wymaga odliczenia (50% VAT) — nie FZBO.")
    if amounts and self_assessed and amounts[1] != 0:
        problems.append(
            "Faktura ma VAT od sprzedawcy, a import usług i WNT liczą VAT po stronie "
            "nabywcy — sprawdź typ dokumentu."
        )
    counterparty_account = settlement_account(
        inp.counterparty_account,
        inp.counterparty_symfonia_id,
        foreign=inp.counterparty_foreign,
        currency=inp.currency,
    )
    if inp.counterparty_id is None:
        problems.append(NO_COUNTERPARTY)
    elif not counterparty_account:
        problems.append(
            f"Kontrahent „{inp.counterparty_name or '—'}” nie ma konta "
            "rozrachunkowego ani numeru Symfonii w kartotece — uzupełnij je "
            "w „Kontrahenci”."
        )
    fx: dict[str, Any] = {}
    multiplier: Optional[Decimal] = Decimal("1")
    foreign_currency = inp.currency != "PLN"
    if foreign_currency:
        multiplier = None
        if inp.issue_date is None and inp.fx_date is None:
            problems.append(
                f"Faktura w {inp.currency} bez daty wystawienia — wybierz datę kursu."
            )
        elif inp.fx_rate is None:
            day = inp.fx_date or rate_day(inp.issue_date)  # type: ignore[arg-type]
            problems.append(f"Brak kursu NBP {inp.currency} z dnia {day:%d.%m.%Y}")
        else:
            multiplier = Decimal(inp.fx_rate)
            fx = {
                "fx_rate": _rate_text(multiplier),
                "fx_date": inp.fx_date.isoformat() if inp.fx_date else None,
                "fx_table": choices.get("fx_table"),
            }
    positions: list[dict[str, Any]] = []
    registers: list[dict[str, Any]] = []
    rate: Optional[str] = None
    if amounts is None:
        problems.append(NO_AMOUNTS)
    elif multiplier is not None:
        net, vat, gross = amounts
        debit, credit = ("credit", "debit") if negative else ("debit", "credit")

        def cur(value: Decimal) -> Optional[int]:
            return grosze(abs(value)) if foreign_currency else None

        candidates: list[dict[str, Any]] = []
        if self_assessed:
            percent = int(choices.get("import_rate") or 23)
            rate = str(percent)
            net_g = grosze(abs(net) * multiplier)
            vat_g = grosze(Decimal(net_g) * percent / 100 / 100)
            net_cur = cur(net)
            vat_cur = grosze(abs(net) * percent / 100) if foreign_currency else None
            cost_g = net_g if deduction == "full" else net_g + vat_g
            cost_cur = (
                net_cur
                if deduction == "full" or net_cur is None
                else net_cur + (vat_cur or 0)
            )
            candidates.append(
                _position(
                    "cost",
                    net_account,
                    debit,
                    cost_g,
                    amount_cur=cost_cur,
                    vat_rate=rate,
                    deduction=deduction,
                )
            )
            candidates.append(
                _position(
                    "counterparty",
                    counterparty_account,
                    credit,
                    net_g,
                    amount_cur=net_cur,
                )
            )
            if deduction == "full":
                candidates.append(
                    _position(
                        "vat",
                        vat_account,
                        debit,
                        vat_g,
                        amount_cur=vat_cur,
                        vat_rate=rate,
                        deduction="full",
                    )
                )
            candidates.append(
                _position(
                    "vat_due",
                    output_vat_account,
                    credit,
                    vat_g,
                    amount_cur=vat_cur,
                    vat_rate=rate,
                )
            )
            pair = (net_cur, vat_cur) if foreign_currency else None
            if deduction == "full":
                registers.append(
                    _register(
                        register, rate, net_g, vat_g, cur=pair, eu=eu, service=service
                    )
                )
            registers.append(
                _register(
                    output_register,
                    rate,
                    net_g,
                    vat_g,
                    cur=pair,  # type: ignore[arg-type]
                    output=True,
                    eu=eu,
                )
            )
        else:
            rate = vat_rate(net, vat)
            # Brutto i VAT po kursie, netto jako różnica — dekret się bilansuje.
            gross_g = grosze(abs(gross) * multiplier)
            vat_g = grosze(abs(vat) * multiplier)
            net_g = gross_g - vat_g if multiplier != 1 else grosze(abs(net))
            gross_cur, vat_cur = cur(gross), cur(vat)
            net_cur = gross_cur - vat_cur if gross_cur is not None else None
            if car:
                vat_kept, vat_lost = _half(vat_g)
                net_a, net_b = _half(net_g)
                cost_g, vat_pos = net_g + vat_lost, vat_kept
                cost_cur = vat_pos_cur = None
                cur_a = cur_b = None
                if foreign_currency:
                    kept_cur, lost_cur = _half(vat_cur or 0)
                    net_a_cur, net_b_cur = _half(net_cur or 0)
                    cost_cur, vat_pos_cur = (net_cur or 0) + lost_cur, kept_cur
                    cur_a, cur_b = (net_a_cur, kept_cur), (net_b_cur, lost_cur)
                registers.append(_register(register, rate, net_a, vat_kept, cur=cur_a))
                registers.append(
                    _register(
                        options.CAR_SECOND_CORRECTION_REGISTER
                        if negative
                        else options.CAR_SECOND_REGISTER,
                        rate,
                        net_b,
                        vat_lost,
                        cur=cur_b,
                    )
                )
            elif deduction == "none":
                cost_g, vat_pos = gross_g, 0
                cost_cur, vat_pos_cur = gross_cur, None
            else:
                cost_g, vat_pos = net_g, vat_g
                cost_cur, vat_pos_cur = net_cur, vat_cur
                registers.append(
                    _register(
                        register,
                        rate,
                        net_g,
                        vat_g,
                        cur=(net_cur, vat_cur) if foreign_currency else None,  # type: ignore[arg-type]
                    )
                )
            candidates.append(
                _position(
                    "cost",
                    net_account,
                    debit,
                    cost_g,
                    amount_cur=cost_cur,
                    vat_rate=rate,
                    deduction="partial" if car else deduction,
                )
            )
            if deduction == "full":
                candidates.append(
                    _position(
                        "vat",
                        vat_account,
                        debit,
                        vat_pos,
                        amount_cur=vat_pos_cur,
                        vat_rate=rate,
                        deduction="partial" if car else "full",
                    )
                )
            candidates.append(
                _position(
                    "counterparty",
                    counterparty_account,
                    credit,
                    gross_g,
                    amount_cur=gross_cur,
                )
            )
            if offbalance:
                _, half_gross = _half(gross_g)
                candidates.append(
                    _position("offbalance", options.OFFBALANCE_DEBIT, debit, half_gross)
                )
                candidates.append(
                    _position("offbalance_offset", offbalance, credit, half_gross)
                )
        if allocation:
            cost = candidates[0]
            candidates.append(
                _position(
                    "allocation",
                    allocation,
                    debit,
                    cost["amount"],
                    amount_cur=cost["amount_cur"],
                )
            )
            candidates.append(
                _position(
                    "allocation_offset",
                    options.ALLOCATION_OFFSET,
                    credit,
                    cost["amount"],
                    amount_cur=cost["amount_cur"],
                )
            )
        positions = [item for item in candidates if item["amount"] != 0]
    description = choices.get("description") or (
        render_description(
            rule.description_template,
            service=rule.service_label,
            period=inp.period,
            number=inp.invoice_number,
            counterparty=inp.counterparty_name,
        )
        if rule
        else ""
    )
    if not description:
        problems.append("Wpisz opis księgowy faktury.")
    jpk = choices.get("jpk_procedure") or (
        options.IMPORT_JPK
        if importing
        else options.CASH_METHOD_JPK
        if inp.cash_method
        else None
    )
    service_date = choices.get("service_date") or (
        inp.service_date.isoformat() if inp.service_date else None
    )
    return {
        **base,
        **fx,
        "rule_id": rule.id if rule else None,
        "register": rule.register if rule else "purchase",
        "doc_type": doc_type,
        "description": description,
        "positions": positions,
        "registers": registers,
        "negative": negative,
        "self_assessed": self_assessed,
        **(
            {"source_gross": str(inp.gross)}
            if self_assessed and inp.gross is not None
            else {}
        ),
        "car": car,
        "jpk_procedure": jpk,
        "service_date": service_date,
        "vat_rate": rate,
        "problems": problems,
    }


def totals(positions: Iterable[dict[str, Any]]) -> tuple[int, int]:
    debit = credit = 0
    for item in positions:
        if item.get("side") == "debit":
            debit += int(item.get("amount") or 0)
        else:
            credit += int(item.get("amount") or 0)
    return debit, credit


def check(decree: Optional[dict[str, Any]], plan: dict[str, AccountView]) -> list[str]:
    """Co blokuje „Gotowa do księgowania” (pusta lista = dekret kompletny)."""

    if not decree:
        return [NOT_COMPUTED]
    stored = list(decree.get("problems") or [])
    issues = list(stored)
    positions = decree.get("positions") or []
    if not positions:
        return issues or ["Dekret nie ma pozycji."]
    for item in positions:
        number = item.get("account")
        kind = item.get("kind")
        if not number:
            if not stored:
                issues.append(f"Pozycja „{KIND_LABELS.get(kind, kind)}” nie ma konta.")
            continue
        if kind not in PLAN_KINDS:
            continue
        account = plan.get(number)
        if account is None or not account.active:
            issues.append(f"Konta {number} nie ma w planie kont albo jest wyłączone.")
        elif not account_fits(kind, account, car=bool(decree.get("car"))):
            issues.append(
                f"Konto {number} ma w planie rodzaj "
                f"„{ACCOUNT_KIND_LABELS[account.kind]}”, a pozycja to "
                f"„{KIND_LABELS[kind]}”."
            )
    debit, credit = totals(positions)
    if debit != credit:
        issues.append(
            f"Suma Wn ({money_pl(debit)}) różni się od sumy Ma ({money_pl(credit)})."
        )
    return list(dict.fromkeys(issues))


def amount_issue(
    decree: Optional[dict[str, Any]], gross: Optional[Decimal], currency: Optional[str]
) -> Optional[str]:
    """Rozrachunek dekretu ≠ brutto źródła (× kurs z dekretu) → wada."""

    if not decree or gross is None:
        return None
    if decree.get("self_assessed") and decree.get("source_gross") is not None:
        # Import usług: rozrachunek = netto (VAT liczy nabywca), więc porównujemy
        # brutto źródła z tym, z którego dekret powstał.
        same = Decimal(str(decree["source_gross"])) == Decimal(gross)
        return None if same else AMOUNTS_CHANGED
    positions = [
        item
        for item in decree.get("positions") or []
        if item.get("kind") == "counterparty"
    ]
    if not positions:
        return None
    if (currency or "PLN") != "PLN":
        rate = decree.get("fx_rate")
        if not rate:
            # Dekret ręczny bez kursu (np. kursu nie było) — nie ma z czym porównać.
            return None
        expected = grosze(abs(Decimal(gross)) * Decimal(rate))
    else:
        expected = grosze(abs(Decimal(gross)))
    actual = sum(int(item.get("amount") or 0) for item in positions)
    return None if actual == expected else AMOUNTS_CHANGED


def _amount_of(raw: Any) -> int:
    try:
        value = Decimal(str(raw).replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError) as exc:
        raise LedgerError(f"Niepoprawna kwota „{str(raw)[:20]}”.", status=422) from exc
    if not value.is_finite() or value <= 0:
        raise LedgerError("Kwota pozycji musi być większa od zera.", status=422)
    if value != value.quantize(_CENT):
        raise LedgerError(
            "Kwota pozycji ma najwyżej dwa miejsca po przecinku.", status=422
        )
    return grosze(value)


#: Ręczna korekta pozycji zostawia rejestry VAT i wybory z karty (plik Symfonii).
MANUAL_KEPT: tuple[str, ...] = (
    "choices",
    "registers",
    "negative",
    "self_assessed",
    "car",
    "jpk_procedure",
    "service_date",
    "vat_rate",
    "fx_table",
)


#: Pozycje, z których liczą się rejestry VAT (bez „5” i pozabilansowych).
_REGISTER_KINDS: tuple[str, ...] = ("cost", "vat", "vat_due", "counterparty")


def _amount_signature(positions: Any) -> list[tuple[str, str, int]]:
    return sorted(
        (str(item.get("kind")), str(item.get("side")), int(item.get("amount") or 0))
        for item in positions or []
        if item.get("kind") in _REGISTER_KINDS
    )


def manual_decree(
    body: dict[str, Any],
    plan: dict[str, AccountView],
    *,
    previous: Optional[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    """Dekret wpisany ręcznie; zły bilans albo konto = ``LedgerError`` 422."""

    register = body.get("register")
    if register not in REGISTERS:
        raise LedgerError("Wybierz rejestr (Zakup albo Sprzedaż).", status=422)
    raw_positions = body.get("positions") or []
    if not raw_positions:
        raise LedgerError("Dekret musi mieć co najmniej jedną pozycję.", status=422)
    if len(raw_positions) > POSITIONS_MAX:
        raise LedgerError(f"Dekret ma najwyżej {POSITIONS_MAX} pozycji.", status=422)
    earlier = {
        (
            item.get("kind"),
            item.get("account"),
            item.get("side"),
            item.get("amount"),
        ): item.get("amount_cur")
        for item in (previous or {}).get("positions") or []
    }
    positions = []
    for index, raw in enumerate(raw_positions, start=1):
        kind = raw.get("kind")
        side = raw.get("side")
        if kind not in POSITION_KINDS or side not in SIDES:
            raise LedgerError(
                f"Pozycja {index}: nieznany rodzaj albo strona.", status=422
            )
        number = clean_account(raw.get("account"), f"Pozycja {index}")
        if kind in PLAN_KINDS:
            account = plan.get(number)
            if account is None or not account.active:
                raise LedgerError(
                    f"Pozycja {index}: konta {number} nie ma w planie kont albo "
                    "jest wyłączone.",
                    status=422,
                )
            if not account_fits(kind, account, car=bool((previous or {}).get("car"))):
                raise LedgerError(
                    f"Pozycja {index}: konto {number} ma w planie rodzaj "
                    f"„{ACCOUNT_KIND_LABELS[account.kind]}”.",
                    status=422,
                )
        deduction = raw.get("deduction")
        rate = raw.get("vat_rate")
        amount = _amount_of(raw.get("amount"))
        positions.append(
            {
                "kind": kind,
                "account": number,
                "side": side,
                "amount": amount,
                # Kwota w walucie z wyliczonego dekretu, gdy pozycja się nie zmieniła.
                "amount_cur": earlier.get((kind, number, side, amount)),
                "vat_rate": str(rate)[:8] if rate not in (None, "") else None,
                "deduction": deduction if deduction in DEDUCTION_LABELS else None,
                "parallel": kind in PARALLEL_KINDS,
            }
        )
    debit, credit = totals(positions)
    if debit != credit:
        raise LedgerError(
            f"Suma Wn ({money_pl(debit)}) różni się od sumy Ma ({money_pl(credit)}).",
            status=422,
        )
    previous = previous or {}
    kept = {key: previous.get(key) for key in MANUAL_KEPT if key in previous}
    if _amount_signature(positions) != _amount_signature(previous.get("positions")):
        # Inne kwoty niż w wyliczonym dekrecie: rejestry VAT i połowy samochodu
        # z opisu już nie pasują — plik bierze wtedy jeden rejestr z kwot faktury.
        kept.pop("registers", None)
        kept.pop("car", None)
    return {
        **kept,
        "manual": True,
        "computed_at": now.isoformat(),
        "currency": previous.get("currency") or "PLN",
        "fx_rate": previous.get("fx_rate"),
        "fx_date": previous.get("fx_date"),
        "period": previous.get("period"),
        "rule_id": previous.get("rule_id"),
        "register": register,
        "doc_type": clean_doc_type(body.get("doc_type")),
        "description": " ".join((body.get("description") or "").split())[
            :DESCRIPTION_MAX
        ],
        "positions": positions,
        "problems": [],
    }


def first_issue(issues: list[str]) -> str:
    more = len(issues) - 1
    suffix = f" (i jeszcze {more})" if more > 0 else ""
    return f"Dekret niekompletny: {issues[0]}{suffix}"


# ── Baza ─────────────────────────────────────────────────────────────────────


@dataclass
class Context:
    plan: dict[str, AccountView]
    rules: list[RuleView]
    inputs: dict[int, DecreeInput]


async def load_plan(db: AsyncSession) -> dict[str, AccountView]:
    rows = await db.scalars(select(FinanceAccount))
    return {
        row.number: AccountView(row.number, row.name, row.kind, row.active)
        for row in rows
    }


async def load_rules(db: AsyncSession) -> list[RuleView]:
    rows = await db.scalars(
        select(FinancePostingRule).where(FinancePostingRule.active.is_(True))
    )
    return [
        RuleView(
            id=row.id,
            category=row.category,
            counterparty_id=row.counterparty_id,
            cost_account=row.cost_account,
            vat_account=row.vat_account,
            deduction=row.deduction,
            register=row.register,
            doc_type=row.doc_type,
            service_label=row.service_label,
            description_template=row.description_template,
            active=row.active,
        )
        for row in rows
    ]


def _month_start(value: Optional[date]) -> Optional[date]:
    return value.replace(day=1) if value else None


async def load_inputs(
    db: AsyncSession, entries: Iterable[FinanceCostEntry]
) -> dict[int, DecreeInput]:
    """Kwoty, numer i miesiąc usługi ze źródeł, kontrahent z kartoteki."""

    entries = list(entries)
    by_type: dict[str, dict[int, FinanceCostEntry]] = {}
    for entry in entries:
        by_type.setdefault(entry.source_type, {})[entry.source_id] = entry
    sources: dict[tuple[str, int], tuple[Any, ...]] = {}
    #: Z XML-a KSeF (tylko faktury kontraktorów): metoda kasowa, data P_6.
    xml_facts: dict[int, tuple[bool, Optional[date]]] = {}
    if ids := by_type.get("payroll_invoice"):
        rows = await db.execute(
            select(
                PayrollInvoice.id,
                PayrollInvoice.currency,
                PayrollInvoice.net_amount,
                PayrollInvoice.vat_amount,
                PayrollInvoice.gross_amount,
                PayrollInvoice.invoice_number,
                PayrollInvoice.issue_date,
                PayrollPeriod.year,
                PayrollPeriod.month,
            )
            .outerjoin(
                PayrollSettlement, PayrollSettlement.id == PayrollInvoice.settlement_id
            )
            .outerjoin(PayrollPeriod, PayrollPeriod.id == PayrollSettlement.period_id)
            .where(PayrollInvoice.id.in_(list(ids)))
        )
        for row in rows.all():
            period = date(int(row.year), int(row.month), 1) if row.year else None
            sources[("payroll_invoice", row.id)] = (
                row.currency,
                row.net_amount,
                row.vat_amount,
                row.gross_amount,
                row.invoice_number,
                period or _month_start(row.issue_date),
                row.issue_date,
            )
    if ids := by_type.get("contractor_invoice"):
        rows = await db.execute(
            select(
                ClientContractorInvoice.id,
                ClientContractorInvoice.currency,
                ClientContractorInvoice.net_amount,
                ClientContractorInvoice.vat_amount,
                ClientContractorInvoice.gross_amount,
                ClientContractorInvoice.invoice_number,
                ClientContractorInvoice.issue_date,
                ClientContractorInvoice.period_month,
                ClientContractorInvoice.details,
            ).where(ClientContractorInvoice.id.in_(list(ids)))
        )
        for row in rows.all():
            period = None
            if row.period_month and len(row.period_month) == 7:
                period = date(int(row.period_month[:4]), int(row.period_month[5:7]), 1)
            details = row.details or {}
            xml_facts[row.id] = (
                details.get("cash_method") is True,
                _iso_day(details.get("sale_date")),
            )
            sources[("contractor_invoice", row.id)] = (
                row.currency,
                row.net_amount,
                row.vat_amount,
                row.gross_amount,
                row.invoice_number,
                period or _month_start(row.issue_date),
                row.issue_date,
            )
    if ids := by_type.get("approval_document"):
        rows = await db.execute(
            select(
                ApprovalDocument.id,
                ApprovalDocument.currency,
                ApprovalDocument.net_amount,
                ApprovalDocument.vat_amount,
                ApprovalDocument.gross_amount,
                ApprovalDocument.invoice_number,
                ApprovalDocument.issue_date,
            ).where(ApprovalDocument.id.in_(list(ids)))
        )
        for row in rows.all():
            sources[("approval_document", row.id)] = (
                row.currency,
                row.net_amount,
                row.vat_amount,
                row.gross_amount,
                row.invoice_number,
                _month_start(row.issue_date),
                row.issue_date,
            )
    party_ids = {e.counterparty_id for e in entries if e.counterparty_id is not None}
    parties: dict[int, tuple[str, Optional[str]]] = {}
    if party_ids:
        rows = await db.execute(
            select(
                FinanceCounterparty.id,
                FinanceCounterparty.name,
                FinanceCounterparty.cost_account,
                FinanceCounterparty.symfonia_partner_id,
                FinanceCounterparty.id_type,
                FinanceCounterparty.country,
            ).where(FinanceCounterparty.id.in_(party_ids))
        )
        parties = {row.id: tuple(row)[1:] for row in rows.all()}
    wanted: dict[int, tuple[str, date]] = {}
    for entry in entries:
        source = sources.get((entry.source_type, entry.source_id))
        if source is None:
            continue
        currency, issued = (source[0] or "PLN").upper(), source[6]
        chosen = _iso_day(_choices(entry).get("fx_date"))
        if currency != "PLN" and (chosen or issued):
            wanted[entry.id] = (currency, chosen or rate_day(issued))
    rates = await _rates(db, set(wanted.values()))
    result: dict[int, DecreeInput] = {}
    for entry in entries:
        source = sources.get((entry.source_type, entry.source_id))
        currency, net, vat, gross, number, period, issued = source or (
            "PLN",
            None,
            None,
            None,
            None,
            None,
            None,
        )
        currency = (currency or "PLN").upper()
        choices = _choices(entry)
        fx_date = wanted[entry.id][1] if entry.id in wanted else None
        fx_rate = rates.get(wanted[entry.id]) if entry.id in wanted else None
        if choices.get("fx_rate") and currency != "PLN":
            fx_rate = Decimal(str(choices["fx_rate"]))
        name, account, symfonia_id, id_type, country = parties.get(
            entry.counterparty_id or 0, (None, None, None, None, None)
        )
        eu_party = id_type == "vat_eu"
        foreign_party = (
            eu_party
            or id_type == "other"
            or bool(country and country.strip().upper() not in ("", "PL"))
        )
        cash_method, sale_day = (
            xml_facts.get(entry.source_id, (False, None))
            if entry.source_type == "contractor_invoice"
            else (False, None)
        )
        result[entry.id] = DecreeInput(
            category=entry.category,
            counterparty_id=entry.counterparty_id if name is not None else None,
            counterparty_name=name,
            counterparty_account=account,
            currency=currency,
            net=net,
            vat=vat,
            gross=gross,
            invoice_number=number,
            period=period or _month_start(business_date(entry.received_at)),
            issue_date=issued,
            fx_rate=fx_rate,
            fx_date=fx_date,
            counterparty_symfonia_id=symfonia_id,
            counterparty_foreign=foreign_party,
            counterparty_eu=eu_party,
            cash_method=cash_method,
            service_date=sale_day or _service_day(entry.source_type, period, issued),
            choices=choices,
        )
    return result


def _choices(entry: FinanceCostEntry) -> dict[str, Any]:
    return dict((entry.decree or {}).get("choices") or {})


def _iso_day(raw: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None


def _service_day(
    source_type: str, period: Optional[date], issued: Optional[date]
) -> Optional[date]:
    """Data zakończenia usługi bez XML-a: koniec miesiąca usługi źródła
    (rozliczenie osoby, miesiąc kontraktora), inaczej data wystawienia."""

    if period is not None and source_type in ("payroll_invoice", "contractor_invoice"):
        following = (
            date(period.year + 1, 1, 1)
            if period.month == 12
            else date(period.year, period.month + 1, 1)
        )
        return following - timedelta(days=1)
    return issued


async def _rates(
    db: AsyncSession, wanted: set[tuple[str, date]]
) -> dict[tuple[str, date], Decimal]:
    """Kurs NBP dokładnie z wybranego dnia (bez szukania wstecz i bez sieci)."""

    if not wanted:
        return {}
    rows = await db.execute(
        select(FxRate.currency, FxRate.effective_date, FxRate.rate_to_pln).where(
            FxRate.currency.in_({currency for currency, _ in wanted}),
            FxRate.effective_date.in_({day for _, day in wanted}),
        )
    )
    return {
        (row.currency, row.effective_date): Decimal(row.rate_to_pln)
        for row in rows.all()
        if (row.currency, row.effective_date) in wanted
    }


def issues_for(
    decree: Optional[dict[str, Any]],
    plan: dict[str, AccountView],
    gross: Optional[Decimal],
    currency: Optional[str],
) -> list[str]:
    """Kontrola dekretu i zgodność rozrachunku z brutto źródła."""

    issues = check(decree, plan)
    drift = amount_issue(decree, gross, currency)
    if drift and drift not in issues:
        issues.append(drift)
    return issues


async def load_context(
    db: AsyncSession, entries: Iterable[FinanceCostEntry]
) -> Context:
    entries = list(entries)
    return Context(
        plan=await load_plan(db),
        rules=await load_rules(db),
        inputs=await load_inputs(db, entries),
    )


def refresh(entry: FinanceCostEntry, ctx: Context, *, now: datetime) -> None:
    """Dekret wyliczany liczy się od nowa; ręczny zostaje."""

    if entry.decree and entry.decree.get("manual"):
        return
    entry.decree = compute(ctx.inputs[entry.id], ctx.rules, ctx.plan, now=now)


def ensure_ready(entry: FinanceCostEntry, ctx: Context, *, now: datetime) -> None:
    """Przed „Gotowa do księgowania”: świeży dekret i kontrola (409 z powodem)."""

    refresh(entry, ctx, now=now)
    inp = ctx.inputs[entry.id]
    issues = issues_for(entry.decree, ctx.plan, inp.gross, inp.currency)
    if issues:
        raise LedgerError(first_issue(issues))


async def _editable_entry(
    db: AsyncSession, entry_id: int, *, actor_id: int, payroll: bool
) -> FinanceCostEntry:
    entry = await db.scalar(
        select(FinanceCostEntry)
        .where(FinanceCostEntry.id == entry_id, *_payroll_scope(payroll))
        .with_for_update()
    )
    if entry is None:
        raise LedgerError("Nie ma takiej faktury w kolejce.", status=404)
    if entry.id in await _own_entry_ids(db, [entry], actor_id):
        raise LedgerError(OWN_INVOICE_DETAIL, status=403)
    if entry.stage == "booked":
        raise LedgerError(BOOKED_DETAIL)
    if entry.stage not in EDITABLE_STAGES:
        raise LedgerError(NOT_EDITABLE)
    return entry


async def recalculate(
    db: AsyncSession, entry_id: int, *, actor_id: int, now: datetime, payroll: bool
) -> None:
    """„Przelicz”: dekret z reguły od nowa (także w miejsce ręcznego)."""

    entry = await _editable_entry(db, entry_id, actor_id=actor_id, payroll=payroll)
    ctx = await load_context(db, [entry])
    was_manual = bool(entry.decree and entry.decree.get("manual"))
    entry.decree = compute(ctx.inputs[entry.id], ctx.rules, ctx.plan, now=now)
    _event(
        db,
        entry,
        "decree",
        actor_id=actor_id,
        now=now,
        detail={"manual": False, "was_manual": was_manual},
    )
    await db.flush()


async def set_manual(
    db: AsyncSession,
    entry_id: int,
    body: dict[str, Any],
    *,
    actor_id: int,
    now: datetime,
    payroll: bool,
) -> None:
    entry = await _editable_entry(db, entry_id, actor_id=actor_id, payroll=payroll)
    plan = await load_plan(db)
    entry.decree = manual_decree(body, plan, previous=entry.decree, now=now)
    debit, _ = totals(entry.decree["positions"])
    _event(
        db,
        entry,
        "decree",
        actor_id=actor_id,
        now=now,
        detail={"manual": True, "total": money(debit)},
    )
    await db.flush()


async def set_choices(
    db: AsyncSession,
    entry_id: int,
    body: dict[str, Any],
    *,
    actor_id: int,
    now: datetime,
    payroll: bool,
) -> None:
    """Opis do księgowania z karty → dekret liczony od nowa z reguły i wyborów."""

    entry = await _editable_entry(db, entry_id, actor_id=actor_id, payroll=payroll)
    plan = await load_plan(db)
    try:
        choices = options.clean_choices(
            body,
            {
                number: options.PlanEntry(item.number, item.kind, item.active)
                for number, item in plan.items()
            },
        )
    except options.ChoiceError as exc:
        raise LedgerError(str(exc), status=422) from exc
    was_manual = bool(entry.decree and entry.decree.get("manual"))
    entry.decree = {**(entry.decree or {}), "choices": choices}
    ctx = await load_context(db, [entry])
    entry.decree = compute(ctx.inputs[entry.id], ctx.rules, ctx.plan, now=now)
    _event(
        db,
        entry,
        "decree",
        actor_id=actor_id,
        now=now,
        detail={"manual": False, "was_manual": was_manual, "choices": True},
    )
    await db.flush()


async def choice_lists(db: AsyncSession) -> dict[str, Any]:
    """Listy wyboru na karcie: konta z planu (zespół 4 i 7, „5”, 902–903)
    i listy stałe z arkusza księgowej."""

    rows = (
        await db.execute(
            select(FinanceAccount.number, FinanceAccount.name, FinanceAccount.kind)
            .where(FinanceAccount.active.is_(True))
            .order_by(FinanceAccount.number)
        )
    ).all()
    numbers = {row.number for row in rows}
    parents = {
        "-".join(number.split("-")[:cut])
        for number in numbers
        for cut in range(1, len(number.split("-")))
    }

    def pick(ok: Any) -> list[dict[str, str]]:
        return [
            {"value": row.number, "label": f"{row.number} {row.name}".strip()}
            for row in rows
            if row.number not in parents and ok(row.number, row.kind)
        ]

    lists = options.static_options()
    for key in ("vat_accounts", "output_vat_accounts"):
        lists[key] = [
            {**item, "in_plan": item["value"] in numbers} for item in lists[key]
        ]
    return {
        **lists,
        "net_accounts": pick(options.net_account_ok),
        "allocation_accounts": pick(options.allocation_account_ok),
        "offbalance_accounts": pick(
            lambda number, _kind: options.offbalance_account_ok(number)
        ),
        "allocation_offset": options.ALLOCATION_OFFSET,
        "offbalance_debit": options.OFFBALANCE_DEBIT,
    }


def _effective(decree: dict[str, Any]) -> dict[str, Any]:
    """Wartości pól opisu, jakie dekret dziś ma (wybór albo podpowiedź reguły)."""

    choices = decree.get("choices") or {}
    positions = decree.get("positions") or []

    def account_of(kind: str) -> Optional[str]:
        return next(
            (str(item["account"]) for item in positions if item.get("kind") == kind),
            None,
        )

    registers = decree.get("registers") or []
    inputs = [item for item in registers if not item.get("output")]
    outputs = [item for item in registers if item.get("output")]
    return {
        "description": decree.get("description") or "",
        "doc_type": decree.get("doc_type") or None,
        "register": inputs[0]["name"] if inputs else choices.get("register"),
        "net_account": account_of("cost") or choices.get("net_account"),
        "vat_account": account_of("vat") or choices.get("vat_account"),
        "output_register": outputs[0]["name"] if outputs else None,
        "output_vat_account": account_of("vat_due"),
        "eu": bool((inputs or outputs or [{}])[0].get("eu")),
        "service": bool((inputs or [{}])[0].get("service")),
        "import_rate": choices.get("import_rate"),
        "allocation_account": account_of("allocation"),
        "car": bool(decree.get("car")),
        "offbalance_account": account_of("offbalance_offset"),
        "jpk_procedure": decree.get("jpk_procedure"),
        "fx_date": decree.get("fx_date"),
        "fx_rate": decree.get("fx_rate"),
        "fx_table": decree.get("fx_table") or choices.get("fx_table"),
        "service_date": decree.get("service_date"),
    }


def registers_payload(registers: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    def opt(value: Any) -> Optional[str]:
        return money(int(value)) if value is not None else None

    return [
        {
            "name": item.get("name"),
            "rate": item.get("rate"),
            "net": money(int(item.get("net") or 0)),
            "vat": money(int(item.get("vat") or 0)),
            "gross": money(int(item.get("gross") or 0)),
            "net_cur": opt(item.get("net_cur")),
            "vat_cur": opt(item.get("vat_cur")),
            "gross_cur": opt(item.get("gross_cur")),
            "output": bool(item.get("output")),
            "eu": bool(item.get("eu")),
            "service": bool(item.get("service")),
        }
        for item in registers
    ]


def positions_payload(
    positions: Iterable[dict[str, Any]], plan: dict[str, AccountView]
) -> list[dict[str, Any]]:
    result = []
    for item in positions:
        account = plan.get(item.get("account") or "")
        result.append(
            {
                "kind": item.get("kind"),
                "kind_label": KIND_LABELS.get(item.get("kind"), item.get("kind")),
                "account": item.get("account"),
                "account_name": account.name if account else None,
                "side": item.get("side"),
                "side_label": SIDE_LABELS.get(item.get("side"), item.get("side")),
                "amount": money(int(item.get("amount") or 0)),
                "amount_cur": (
                    money(int(item["amount_cur"]))
                    if item.get("amount_cur") is not None
                    else None
                ),
                "parallel": bool(item.get("parallel")),
                "vat_rate": item.get("vat_rate"),
                "deduction": item.get("deduction"),
                "deduction_label": DEDUCTION_LABELS.get(item.get("deduction") or ""),
            }
        )
    return result


async def section(
    db: AsyncSession,
    entry: FinanceCostEntry,
    *,
    own: bool,
    gross: Optional[Decimal] = None,
    currency: Optional[str] = None,
) -> dict[str, Any]:
    """„Dekret do Symfonii FK” na karcie faktury (M2)."""

    plan = await load_plan(db)
    decree = entry.decree or {}
    positions = decree.get("positions") or []
    debit, credit = totals(positions)
    rule = None
    if decree.get("rule_id"):
        row = await db.get(FinancePostingRule, decree["rule_id"])
        if row is not None:
            name = None
            if row.counterparty_id:
                name = await db.scalar(
                    select(FinanceCounterparty.name).where(
                        FinanceCounterparty.id == row.counterparty_id
                    )
                )
            label = CATEGORY_LABELS.get(row.category, row.category)
            rule = {"id": row.id, "label": f"{label} · {name}" if name else label}
    batch = None
    if entry.batch_id:
        row = await db.get(FinancePostingBatch, entry.batch_id)
        if row is not None:
            batch = {"id": row.id, "number": row.number, "status": row.status}
    register = decree.get("register")
    return {
        "computed": bool(entry.decree),
        "manual": bool(decree.get("manual")),
        "computed_at": decree.get("computed_at"),
        "register": register,
        "register_label": REGISTER_LABELS.get(register or ""),
        "doc_type": decree.get("doc_type") or None,
        "description": decree.get("description") or None,
        "currency": decree.get("currency"),
        "rule": rule,
        "positions": positions_payload(positions, plan),
        "debit_total": money(debit),
        "credit_total": money(credit),
        "balanced": debit == credit and debit > 0,
        "issues": issues_for(entry.decree, plan, gross, currency),
        "fx_rate": decree.get("fx_rate"),
        "fx_date": decree.get("fx_date"),
        "fx_table": decree.get("fx_table"),
        "registers": registers_payload(decree.get("registers") or []),
        "jpk_procedure": decree.get("jpk_procedure"),
        "service_date": decree.get("service_date"),
        "car": bool(decree.get("car")),
        "self_assessed": bool(decree.get("self_assessed")),
        "choices": decree.get("choices") or {},
        "effective": _effective(decree) if entry.decree else None,
        "editable": entry.stage in EDITABLE_STAGES and not own,
        "batch": batch,
    }
