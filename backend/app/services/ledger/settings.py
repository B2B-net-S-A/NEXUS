"""Przełączniki modułów Księgowości i lista „Księgowi” (``app_settings['ledger']``).

Decyzje Artura z 13.11.2026: każdy moduł (księga, bank, VAT i JPK, środki
trwałe, płace, podatki i polisy, sprawozdania) wchodzi wyłączony — kod jest
gotowy, a wyłączony moduł widzi tylko administrator. Podgląd księgi ma
„Moduł Finanse”; zatwierdzanie bufora, storno i zamknięcie okresu — osoby
z listy „Księgowi”, którą ustawia administrator (bez nowego uprawnienia
w katalogu dziewięciu).

Moduły bez ekranów (``BUILT``) mają przełącznik, ale włączyć ich się nie da,
dopóki nie wejdzie ich etap — inaczej włączenie pokazałoby pustą zakładkę.
Wyłączony program „Ludzi w NEXUSIE” zamyka Księgowość dla wszystkich, jak
moduł „Księgowość” z E1 (trasy Finansów stoją za tym samym wyłącznikiem).

Konta dekretu faktur sprzedaży (K2, ``sales``) ustawia administrator: konto
rozrachunków z odbiorcami ze słownikiem kontrahentów, konto przychodów i VAT
należnego. Kontrahent z własnym kontem rozrachunkowym sprzedaży z kartoteki
(„konto przychodowe” z eBI24) ma pierwszeństwo — tak jak „konto kosztowe”
w dekrecie kosztów E2.

Konta rozliczenia kosztów na „5” (``allocation``, K2) też ustawia administrator:
konto przeciwstawne (490), konto kosztów klientów (MPK = klient z kontraktu),
konta pionów (front office, back office — z kartoteki osoby) i konto kosztów
ogólnych (faktura bez klienta i pionu, biuro do czasu klucza podziału) oraz
jedno konto kosztów zespołu na PK płacowe.

Rachunki firmy i konta wyciągów (K4a, ``bank``) ustawia administrator: każdy
rachunek (26 cyfr NRB) ma konto w planie (130-x), a konta opłat banku, ZUS
i urzędu skarbowego (VAT, PIT, CIT) mówią, gdzie trafiają operacje rozpoznane
regułą. Puste konto = brak reguły (operacja czeka na przypisanie).

Konta listy płac z Enovy (K3c, ``payroll``) też ustawia administrator: koszty
wynagrodzeń i składek pracodawcy, rozrachunki z tytułu wynagrodzeń, z ZUS
i z urzędem skarbowym (PIT-4) oraz — gdy lista je ma — PPK i inne potrącenia.

Konta środków trwałych (``assets``, K6) ustawia administrator: konto kosztu
amortyzacji (401) w dokumencie AM, konto przeciwstawne przyjęcia i ulepszenia
(080 — zakup z faktury idzie na 080, OT przenosi go na 010) i konto pozostałych
kosztów operacyjnych na wartość netto likwidowanego albo sprzedanego środka.
Podział AM na „5” bierze konta z ``allocation``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.effective_access import resolve_effective_access
from app.models.finance_ledger import FinanceCounterparty
from app.models.finance_posting import FinanceAccount
from app.services.finance_ledger.costs import LedgerError
from app.services.finance_ledger.posting import clean_account
from app.services.hr.bank import accounts as bank_accounts
from app.services.hr.program import program_enabled

SETTING_KEY = "ledger"
#: Moduły Księgowości w kolejności zakładek i etap planu, który je buduje.
MODULES: dict[str, str] = {
    "ledger": "K1–K2",
    "automations": "K3",
    "bank": "K4",
    "vat": "K5",
    "assets": "K6",
    "payroll": "K7",
    "reports": "K8",
}
MODULE_LABELS: dict[str, str] = {
    "ledger": "Księga — dokumenty, obroty i salda, plan kont",
    "automations": "Podatki, polisy i PK cykliczne",
    "bank": "Bank — wyciągi, dopasowanie i rozrachunki",
    "vat": "VAT i JPK",
    "assets": "Środki trwałe",
    "payroll": "Płace — lista, ZUS, PIT",
    "reports": "Sprawozdania i CIT",
}
MODULE_REPLACES: dict[str, str] = {
    "ledger": "Symfonia FK",
    "automations": "ręczne PK w Symfonii",
    "bank": "import XML i rozrachunki w Symfonii",
    "vat": "rejestry i JPK w Symfonii",
    "assets": "Symfonia Środki Trwałe",
    "payroll": "Enova 365 Kadry i Płace",
    "reports": "Symfonia FK",
}
#: Moduły z gotowymi ekranami (kolejne etapy dopisują tu swój klucz).
#: ``payroll`` — K7a (lista płac, parametry, dane osób; 14.11.2026);
#: ``vat`` — K5a (rejestry VAT; 15.11.2026); ``reports`` — K8a (bilans i RZiS;
#: 16.11.2026).
BUILT: frozenset[str] = frozenset(
    {"ledger", "automations", "bank", "vat", "assets", "payroll", "reports"}
)
MODULE_DISABLED_DETAIL = "Moduł Księgowości jest wyłączony."
ACCOUNTANTS_MAX = 20


#: Konta sprzedaży: klucz → (domyślne konto, etykieta w komunikatach).
SALES_ACCOUNT_FIELDS: dict[str, tuple[str, str]] = {
    "receivable_account": ("200", "Rozrachunki z odbiorcami"),
    "revenue_account": ("", "Przychody ze sprzedaży"),
    "vat_account": ("222", "VAT należny"),
}


@dataclass(frozen=True)
class SalesAccounts:
    receivable_account: str = SALES_ACCOUNT_FIELDS["receivable_account"][0]
    revenue_account: str = SALES_ACCOUNT_FIELDS["revenue_account"][0]
    vat_account: str = SALES_ACCOUNT_FIELDS["vat_account"][0]


#: Konta rozliczenia kosztów na „5”: klucz → (domyślne konto, etykieta).
ALLOCATION_ACCOUNT_FIELDS: dict[str, tuple[str, str]] = {
    "settlement_account": ("490", "Rozliczenie kosztów"),
    "client_account": ("", "Koszty klientów (MPK = klient)"),
    "front_office_account": ("", "Koszty pionu Front office"),
    "back_office_account": ("", "Koszty pionu Back office"),
    "overhead_account": ("", "Koszty ogólne"),
    "team_account": ("", "Koszty zespołu (faktury osób zespołu)"),
}


@dataclass(frozen=True)
class AllocationAccounts:
    settlement_account: str = ALLOCATION_ACCOUNT_FIELDS["settlement_account"][0]
    client_account: str = ""
    front_office_account: str = ""
    back_office_account: str = ""
    overhead_account: str = ""
    #: Jedno konto kosztów z faktur osób zespołu dla wszystkich pionów — pion
    #: tylko w MPK pozycji, żeby obroty nie pokazywały sumy pionu (D2).
    team_account: str = ""

    def complete(self) -> bool:
        return all(getattr(self, key) for key in ALLOCATION_ACCOUNT_FIELDS)


#: Konta listy płac (K3c): klucz → (domyślne konto, etykieta). PPK i potrącenia
#: mogą zostać puste — wtedy lista z takimi kwotami czeka z problemem.
PAYROLL_ACCOUNT_FIELDS: dict[str, tuple[str, str]] = {
    "wages_account": ("", "Wynagrodzenia (koszt)"),
    "insurance_account": ("", "Składki i PPK pracodawcy (koszt)"),
    "settlement_account": ("231", "Rozrachunki z tytułu wynagrodzeń"),
    "zus_account": ("229", "Rozrachunki z ZUS"),
    "pit_account": ("225", "Rozrachunki z urzędem skarbowym (PIT-4)"),
    "ppk_account": ("", "Rozrachunki PPK"),
    "deductions_account": ("", "Inne potrącenia z wynagrodzeń"),
}
PAYROLL_OPTIONAL: frozenset[str] = frozenset({"ppk_account", "deductions_account"})


@dataclass(frozen=True)
class PayrollAccounts:
    wages_account: str = ""
    insurance_account: str = ""
    settlement_account: str = PAYROLL_ACCOUNT_FIELDS["settlement_account"][0]
    zus_account: str = PAYROLL_ACCOUNT_FIELDS["zus_account"][0]
    pit_account: str = PAYROLL_ACCOUNT_FIELDS["pit_account"][0]
    ppk_account: str = ""
    deductions_account: str = ""

    def missing(self) -> list[str]:
        """Etykiety wymaganych kont, których brakuje."""

        return [
            label
            for key, (_, label) in PAYROLL_ACCOUNT_FIELDS.items()
            if key not in PAYROLL_OPTIONAL and not getattr(self, key)
        ]


#: Konta środków trwałych (K6): klucz → (domyślne konto, etykieta).
ASSETS_ACCOUNT_FIELDS: dict[str, tuple[str, str]] = {
    "cost_account": ("401", "Amortyzacja"),
    "intake_account": ("080", "Przyjęcie i ulepszenie — konto przeciwstawne"),
    "disposal_account": ("761", "Likwidacja i sprzedaż — wartość netto"),
}


@dataclass(frozen=True)
class AssetsAccounts:
    cost_account: str = ASSETS_ACCOUNT_FIELDS["cost_account"][0]
    intake_account: str = ASSETS_ACCOUNT_FIELDS["intake_account"][0]
    disposal_account: str = ASSETS_ACCOUNT_FIELDS["disposal_account"][0]


#: Konta rejestrów VAT (K5a): klucz → (domyślne konto, etykieta). VAT należny
#: jest w kontach sprzedaży (``SALES_ACCOUNT_FIELDS["vat_account"]``).
#: ``foreign_account`` (K5b-2) — konto ze słownikiem kontrahentów, pod którym
#: formularz zakupu zagranicznego zakłada rozrachunek nowego dostawcy (``202-1``
#: → ``202-1-NNN``); puste = formularz nie zakłada dostawców.
#: ``rounding_*`` (K5b-3c) — różnica groszy w rozliczeniu VAT (deklaracja
#: w pełnych złotych, konta w groszach), np. 760 / 761; puste = dokument
#: rozliczenia VAT nie powstaje.
VAT_ACCOUNT_FIELDS: dict[str, tuple[str, str]] = {
    "input_account": ("221", "VAT naliczony"),
    "foreign_account": ("", "Rozrachunki z dostawcami zagranicznymi"),
    "rounding_gain_account": (
        "",
        "Różnice z zaokrągleń VAT (pozostałe przychody operacyjne)",
    ),
    "rounding_loss_account": (
        "",
        "Różnice z zaokrągleń VAT (pozostałe koszty operacyjne)",
    ),
}
VAT_OPTIONAL = frozenset(
    {"foreign_account", "rounding_gain_account", "rounding_loss_account"}
)


@dataclass(frozen=True)
class VatAccounts:
    input_account: str = VAT_ACCOUNT_FIELDS["input_account"][0]
    foreign_account: str = ""
    rounding_gain_account: str = ""
    rounding_loss_account: str = ""


#: Znaczniki JPK_V7M per kontrahent (K5b-2, decyzja Artura z 15.11.2026): GTU
#: i TP w kolejności z XSD, na wszystkich fakturach sprzedaży kontrahenta.
MARKERS: tuple[str, ...] = tuple(f"GTU_{n:02d}" for n in range(1, 14)) + ("TP",)
MARKED_MAX = 500


#: Kontakt w JPK_V7M (Podmiot1): e-mail obowiązkowy, telefon opcjonalny (K5b).
JPK_EMAIL_MAX = 255
JPK_PHONE_MAX = 16
_JPK_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class JpkContact:
    email: str = ""
    phone: str = ""


#: Konta wyciągów (K4a): klucz → (domyślne konto, etykieta). Puste = bez reguły.
BANK_ACCOUNT_FIELDS: dict[str, tuple[str, str]] = {
    "fees_account": ("", "Opłaty i prowizje bankowe"),
    "zus_account": ("229", "Rozrachunki z ZUS"),
    "vat_account": ("", "VAT do zapłaty (urząd skarbowy)"),
    "pit_account": ("225", "PIT-4 (urząd skarbowy)"),
    "cit_account": ("", "CIT (urząd skarbowy)"),
    # K4c-1: różnice kursowe zrealizowane przy rozliczeniu pozycji w walucie.
    "fx_gain_account": ("", "Dodatnie różnice kursowe (przychody finansowe)"),
    "fx_loss_account": ("", "Ujemne różnice kursowe (koszty finansowe)"),
}
#: Waluty rachunków firmy (K4c-1) — jak wyciągi w księdze, E8 i R9.
BANK_CURRENCIES: tuple[str, ...] = ("PLN", "EUR", "USD")
BANK_ACCOUNTS_MAX = 20
BANK_NAME_MAX = 80


@dataclass(frozen=True)
class CompanyAccount:
    """Rachunek firmy: 26 cyfr NRB, konto w planie (130-x), nazwa i waluta."""

    number: str
    account: str
    name: str = ""
    currency: str = "PLN"


def nrb(raw: Optional[str]) -> str:
    """Numer rachunku → 26 cyfr NRB (bez „PL”, spacji i kresek); inaczej ``""``."""

    text = "".join(ch for ch in (raw or "").upper() if ch.isalnum())
    if text.startswith("PL"):
        text = text[2:]
    return text if len(text) == 26 and text.isdigit() else ""


@dataclass(frozen=True)
class BankSettings:
    accounts: tuple[CompanyAccount, ...] = ()
    fees_account: str = ""
    zus_account: str = BANK_ACCOUNT_FIELDS["zus_account"][0]
    vat_account: str = ""
    pit_account: str = BANK_ACCOUNT_FIELDS["pit_account"][0]
    cit_account: str = ""
    fx_gain_account: str = ""
    fx_loss_account: str = ""

    def by_number(self, number: Optional[str]) -> Optional[CompanyAccount]:
        clean = nrb(number)
        return next((item for item in self.accounts if item.number == clean), None)


@dataclass(frozen=True)
class LedgerSettings:
    modules: dict[str, bool]
    accountants: tuple[int, ...]
    sales: SalesAccounts = field(default_factory=SalesAccounts)
    allocation: AllocationAccounts = field(default_factory=AllocationAccounts)
    payroll: PayrollAccounts = field(default_factory=PayrollAccounts)
    assets: AssetsAccounts = field(default_factory=AssetsAccounts)
    bank: BankSettings = field(default_factory=BankSettings)
    vat: VatAccounts = field(default_factory=VatAccounts)
    jpk: JpkContact = field(default_factory=JpkContact)
    #: Kontrahent (``finance_counterparties.id``) → znaczniki z ``MARKERS``.
    vat_markers: dict[int, tuple[str, ...]] = field(default_factory=dict)


def _accounts(raw: object, fields: dict[str, tuple[str, str]]) -> dict[str, str]:
    data = raw if isinstance(raw, dict) else {}
    values: dict[str, str] = {}
    for key, (default, label) in fields.items():
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            values[key] = default
            continue
        try:
            values[key] = clean_account(value, label)
        except LedgerError:
            values[key] = default
    return values


def _sales(raw: object) -> SalesAccounts:
    return SalesAccounts(**_accounts(raw, SALES_ACCOUNT_FIELDS))


def _allocation(raw: object) -> AllocationAccounts:
    return AllocationAccounts(**_accounts(raw, ALLOCATION_ACCOUNT_FIELDS))


def _payroll(raw: object) -> PayrollAccounts:
    return PayrollAccounts(**_accounts(raw, PAYROLL_ACCOUNT_FIELDS))


def _assets(raw: object) -> AssetsAccounts:
    return AssetsAccounts(**_accounts(raw, ASSETS_ACCOUNT_FIELDS))


def _vat(raw: object) -> VatAccounts:
    return VatAccounts(**_accounts(raw, VAT_ACCOUNT_FIELDS))


def _markers(raw: object) -> dict[int, tuple[str, ...]]:
    data = raw if isinstance(raw, dict) else {}
    found: dict[int, tuple[str, ...]] = {}
    for key, value in data.items():
        if not (isinstance(key, str) and key.isdigit()) or not isinstance(value, list):
            continue
        items = tuple(item for item in MARKERS if item in value)
        if items and int(key) > 0:
            found[int(key)] = items
    return dict(sorted(found.items())[:MARKED_MAX])


def _jpk(raw: object) -> JpkContact:
    data = raw if isinstance(raw, dict) else {}

    def text(key: str) -> str:
        value = data.get(key)
        return " ".join(value.split()) if isinstance(value, str) else ""

    return JpkContact(email=text("email"), phone=text("phone"))


def _bank(raw: object) -> BankSettings:
    data = raw if isinstance(raw, dict) else {}
    items: list[CompanyAccount] = []
    seen: set[str] = set()
    raw_accounts = data.get("accounts")
    for item in raw_accounts if isinstance(raw_accounts, list) else []:
        if not isinstance(item, dict):
            continue
        number = nrb(item.get("number"))
        account = item.get("account")
        if not number or number in seen or not isinstance(account, str):
            continue
        try:
            account = clean_account(account, "Konto rachunku")
        except LedgerError:
            continue
        name = item.get("name") if isinstance(item.get("name"), str) else ""
        currency = item.get("currency")
        seen.add(number)
        items.append(
            CompanyAccount(
                number,
                account,
                " ".join(name.split())[:BANK_NAME_MAX],
                currency if currency in BANK_CURRENCIES else "PLN",
            )
        )
    return BankSettings(
        accounts=tuple(items[:BANK_ACCOUNTS_MAX]),
        **_accounts(data, BANK_ACCOUNT_FIELDS),
    )


def normalize(raw: object) -> LedgerSettings:
    data = raw if isinstance(raw, dict) else {}
    modules_raw = data.get("modules") if isinstance(data.get("modules"), dict) else {}
    modules = {key: modules_raw.get(key) is True and key in BUILT for key in MODULES}
    accountants_raw = data.get("accountants")
    accountants = tuple(
        sorted(
            {
                item
                for item in (
                    accountants_raw if isinstance(accountants_raw, list) else []
                )
                if isinstance(item, int) and not isinstance(item, bool) and item > 0
            }
        )
    )
    return LedgerSettings(
        modules=modules,
        accountants=accountants,
        sales=_sales(data.get("sales")),
        allocation=_allocation(data.get("allocation")),
        payroll=_payroll(data.get("payroll")),
        assets=_assets(data.get("assets")),
        bank=_bank(data.get("bank")),
        vat=_vat(data.get("vat")),
        jpk=_jpk(data.get("jpk")),
        vat_markers=_markers(data.get("vat_markers")),
    )


def to_json(settings: LedgerSettings) -> dict[str, Any]:
    return {
        "modules": dict(settings.modules),
        "accountants": list(settings.accountants),
        "sales": {
            "receivable_account": settings.sales.receivable_account,
            "revenue_account": settings.sales.revenue_account,
            "vat_account": settings.sales.vat_account,
        },
        "allocation": {
            key: getattr(settings.allocation, key) for key in ALLOCATION_ACCOUNT_FIELDS
        },
        "payroll": {
            key: getattr(settings.payroll, key) for key in PAYROLL_ACCOUNT_FIELDS
        },
        "assets": {key: getattr(settings.assets, key) for key in ASSETS_ACCOUNT_FIELDS},
        "vat": {key: getattr(settings.vat, key) for key in VAT_ACCOUNT_FIELDS},
        "jpk": {"email": settings.jpk.email, "phone": settings.jpk.phone},
        "vat_markers": {
            str(key): list(value) for key, value in sorted(settings.vat_markers.items())
        },
        "bank": {
            "accounts": [
                {
                    "number": item.number,
                    "account": item.account,
                    "name": item.name,
                    "currency": item.currency,
                }
                for item in settings.bank.accounts
            ],
            **{key: getattr(settings.bank, key) for key in BANK_ACCOUNT_FIELDS},
        },
    }


async def load(db: AsyncSession) -> LedgerSettings:
    if not program_enabled():
        return normalize(None)
    raw = await db.scalar(select(AppSetting.value).where(AppSetting.key == SETTING_KEY))
    return normalize(raw)


def is_admin(user: User) -> bool:
    return user.has_role(UserRole.admin)


def module_open(user: User, settings: LedgerSettings, module: str = "ledger") -> bool:
    """Czy ekrany modułu działają dla tej osoby (admin widzi zawsze)."""

    if not program_enabled():
        return False
    return settings.modules.get(module, False) or is_admin(user)


def can_approve(user: User, settings: LedgerSettings) -> bool:
    """Zatwierdzanie bufora, storno, zamknięcie okresu: admin albo „Księgowi”."""

    return is_admin(user) or user.id in settings.accountants


async def _save(db: AsyncSession, settings: LedgerSettings, *, actor: User) -> None:
    value = to_json(settings)
    statement = insert(AppSetting).values(
        key=SETTING_KEY, value=value, updated_by=actor.id
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value, "updated_by": actor.id},
        )
    )


async def set_module(
    db: AsyncSession, module: str, enabled: bool, *, actor: User
) -> LedgerSettings:
    """Zapis przełącznika (bez commita). Moduł bez ekranów = 409."""

    if module not in MODULES:
        raise LedgerError("Nie ma takiego modułu Księgowości.", status=404)
    if enabled and module not in BUILT:
        raise LedgerError(
            f"Moduł „{MODULE_LABELS[module]}” jeszcze nie ma ekranów (etap "
            f"{MODULES[module]}) — przełącznik zadziała po jego wdrożeniu.",
            status=409,
        )
    current = await load(db)
    settings = replace(current, modules={**current.modules, module: bool(enabled)})
    await _save(db, settings, actor=actor)
    return settings


async def set_accountants(
    db: AsyncSession, user_ids: list[int], *, actor: User
) -> LedgerSettings:
    """Lista „Księgowi” (bez commita): aktywne konta z „Modułem Finanse”."""

    unique = sorted(set(user_ids))
    if len(unique) > ACCOUNTANTS_MAX:
        raise LedgerError(
            f"Lista „Księgowi” ma najwyżej {ACCOUNTANTS_MAX} osób.", status=422
        )
    users = list(
        (await db.scalars(select(User).where(User.id.in_(unique or [0])))).all()
    )
    # Nadania osoby z „Osoby i role” — ta sama polityka co bramki tras.
    await resolve_effective_access(db, users)
    found = {user.id: user for user in users}
    for user_id in unique:
        user = found.get(user_id)
        if user is None or not user.is_active:
            raise LedgerError(
                "Na liście „Księgowi” może być tylko aktywne konto.", status=422
            )
        if not (is_admin(user) or has_permission(user, ProductAction.finance_module)):
            raise LedgerError(
                f"{user.name or 'Ta osoba'} nie ma „Modułu Finanse” — najpierw nadaj "
                "uprawnienie w „Osoby i role”.",
                status=422,
            )
    current = await load(db)
    settings = replace(current, accountants=tuple(unique))
    await _save(db, settings, actor=actor)
    return settings


async def _plan_accounts(
    db: AsyncSession,
    values: dict[str, str],
    fields: dict[str, tuple[str, str]],
    optional: frozenset[str] = frozenset(),
) -> dict[str, str]:
    """Każde konto z formularza musi być aktywne w planie kont (puste — tylko opcjonalne)."""

    cleaned: dict[str, str] = {}
    for key, (_, label) in fields.items():
        if key in optional and not (values.get(key) or "").strip():
            cleaned[key] = ""
            continue
        number = clean_account(values.get(key), label)
        account = await db.scalar(
            select(FinanceAccount).where(FinanceAccount.number == number)
        )
        if account is None or not account.active:
            raise LedgerError(
                f"{label}: konta {number} nie ma w planie kont albo jest wyłączone.",
                status=422,
            )
        cleaned[key] = number
    return cleaned


async def set_sales_accounts(
    db: AsyncSession, values: dict[str, str], *, actor: User
) -> LedgerSettings:
    """Konta dekretu sprzedaży (bez commita, admin): każde z planu kont."""

    cleaned = await _plan_accounts(db, values, SALES_ACCOUNT_FIELDS)
    current = await load(db)
    settings = replace(current, sales=SalesAccounts(**cleaned))
    await _save(db, settings, actor=actor)
    return settings


async def set_allocation_accounts(
    db: AsyncSession, values: dict[str, str], *, actor: User
) -> LedgerSettings:
    """Konta rozliczenia kosztów na „5” (bez commita, admin): każde z planu kont."""

    cleaned = await _plan_accounts(db, values, ALLOCATION_ACCOUNT_FIELDS)
    current = await load(db)
    settings = replace(current, allocation=AllocationAccounts(**cleaned))
    await _save(db, settings, actor=actor)
    return settings


async def set_payroll_accounts(
    db: AsyncSession, values: dict[str, str], *, actor: User
) -> LedgerSettings:
    """Konta listy płac (bez commita, admin): wymagane z planu kont, PPK i potrącenia opcjonalnie."""

    cleaned = await _plan_accounts(
        db, values, PAYROLL_ACCOUNT_FIELDS, optional=PAYROLL_OPTIONAL
    )
    current = await load(db)
    settings = replace(current, payroll=PayrollAccounts(**cleaned))
    await _save(db, settings, actor=actor)
    return settings


async def set_assets_accounts(
    db: AsyncSession, values: dict[str, str], *, actor: User
) -> LedgerSettings:
    """Konta środków trwałych (bez commita, admin): każde z planu kont."""

    cleaned = await _plan_accounts(db, values, ASSETS_ACCOUNT_FIELDS)
    current = await load(db)
    settings = replace(current, assets=AssetsAccounts(**cleaned))
    await _save(db, settings, actor=actor)
    return settings


async def set_vat_accounts(
    db: AsyncSession, values: dict[str, Optional[str]], *, actor: User
) -> LedgerSettings:
    """Konta rejestrów VAT (bez commita, admin): każde z planu kont.

    ``None`` = bez zmiany (formularz bez pola nie kasuje konta). Konto
    dostawców zagranicznych musi prowadzić słownik kontrahentów — formularz
    zakupu zakłada pod nim analitykę dostawcy."""

    current = await load(db)
    merged = {
        key: getattr(current.vat, key) if values.get(key) is None else values[key]
        for key in VAT_ACCOUNT_FIELDS
    }
    cleaned = await _plan_accounts(
        db, merged, VAT_ACCOUNT_FIELDS, optional=VAT_OPTIONAL
    )
    if cleaned["foreign_account"]:
        dictionary = await db.scalar(
            select(FinanceAccount.dictionary).where(
                FinanceAccount.number == cleaned["foreign_account"]
            )
        )
        if dictionary != "counterparty":
            raise LedgerError(
                f"{VAT_ACCOUNT_FIELDS['foreign_account'][1]}: konto "
                f"{cleaned['foreign_account']} musi mieć w planie kont słownik "
                "analityki „kontrahenci” (dostawca dostaje konto "
                f"{cleaned['foreign_account']}-NNN).",
                status=422,
            )
    settings = replace(current, vat=VatAccounts(**cleaned))
    await _save(db, settings, actor=actor)
    return settings


async def set_vat_markers(
    db: AsyncSession,
    counterparty_id: int,
    markers: list[str],
    *,
    actor: User,
) -> LedgerSettings:
    """Znaczniki GTU/TP kontrahenta (bez commita; lista „Księgowi” albo admin
    — sprawdza trasa). Pusta lista zdejmuje kontrahenta z listy."""

    unknown = sorted({item for item in markers if item not in MARKERS})
    if unknown:
        raise LedgerError(
            f"Nieznane oznaczenie JPK: {', '.join(unknown[:5])}.", status=422
        )
    exists = await db.scalar(
        select(FinanceCounterparty.id).where(FinanceCounterparty.id == counterparty_id)
    )
    if exists is None:
        raise LedgerError("Nie ma takiego kontrahenta w kartotece.", status=404)
    current = await load(db)
    updated = dict(current.vat_markers)
    cleaned = tuple(item for item in MARKERS if item in set(markers))
    if cleaned:
        updated[counterparty_id] = cleaned
    else:
        updated.pop(counterparty_id, None)
    if len(updated) > MARKED_MAX:
        raise LedgerError(
            f"Znaczniki ma najwyżej {MARKED_MAX} kontrahentów.", status=422
        )
    settings = replace(current, vat_markers=dict(sorted(updated.items())))
    await _save(db, settings, actor=actor)
    return settings


async def set_jpk_contact(
    db: AsyncSession, values: dict[str, Any], *, actor: User
) -> LedgerSettings:
    """Kontakt w JPK_V7M (bez commita, admin): e-mail i opcjonalny telefon."""

    email = " ".join(str(values.get("email") or "").split())
    phone = " ".join(str(values.get("phone") or "").split())
    if len(email) > JPK_EMAIL_MAX or not _JPK_EMAIL.match(email):
        raise LedgerError("E-mail do JPK: podaj adres e-mail.", status=422)
    if len(phone) > JPK_PHONE_MAX:
        raise LedgerError(
            f"Telefon do JPK: najwyżej {JPK_PHONE_MAX} znaków.", status=422
        )
    current = await load(db)
    settings = replace(current, jpk=JpkContact(email=email, phone=phone))
    await _save(db, settings, actor=actor)
    return settings


async def set_bank_settings(
    db: AsyncSession, values: dict[str, Any], *, actor: User
) -> LedgerSettings:
    """Rachunki firmy i konta wyciągów (bez commita, admin): konta z planu kont."""

    raw_accounts = values.get("accounts") or []
    if len(raw_accounts) > BANK_ACCOUNTS_MAX:
        raise LedgerError(f"Najwyżej {BANK_ACCOUNTS_MAX} rachunków firmy.", status=422)
    accounts: list[CompanyAccount] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_accounts, start=1):
        try:
            number = bank_accounts.normalize_nrb(item.get("number"))
        except bank_accounts.AccountError as exc:
            raise LedgerError(f"Rachunek {index}: {exc}", status=422) from exc
        if number in seen:
            raise LedgerError(f"Rachunek {index} jest na liście dwa razy.", status=422)
        seen.add(number)
        cleaned = await _plan_accounts(
            db,
            {"account": item.get("account")},
            {"account": ("", f"Rachunek {index}")},
        )
        name = " ".join(str(item.get("name") or "").split())[:BANK_NAME_MAX]
        currency = str(item.get("currency") or "PLN").upper()
        if currency not in BANK_CURRENCIES:
            raise LedgerError(
                f"Rachunek {index}: waluta {currency} — rachunki są w "
                f"{', '.join(BANK_CURRENCIES)}.",
                status=422,
            )
        accounts.append(CompanyAccount(number, cleaned["account"], name, currency))
    fields = await _plan_accounts(
        db, values, BANK_ACCOUNT_FIELDS, optional=frozenset(BANK_ACCOUNT_FIELDS)
    )
    current = await load(db)
    settings = replace(current, bank=BankSettings(accounts=tuple(accounts), **fields))
    await _save(db, settings, actor=actor)
    return settings
