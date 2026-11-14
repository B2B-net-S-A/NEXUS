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

from dataclasses import dataclass, field, replace
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.effective_access import resolve_effective_access
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
#: ``payroll`` — K7a (lista płac, parametry, dane osób; 14.11.2026).
BUILT: frozenset[str] = frozenset(
    {"ledger", "automations", "bank", "assets", "payroll"}
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
