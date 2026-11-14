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
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

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
    "bank": "Bank — wyciągi i dopasowanie",
    "vat": "VAT i JPK",
    "assets": "Środki trwałe",
    "payroll": "Płace — lista, ZUS, PIT",
    "reports": "Sprawozdania i CIT",
}
MODULE_REPLACES: dict[str, str] = {
    "ledger": "Symfonia FK",
    "automations": "ręczne PK w Symfonii",
    "bank": "import XML w Symfonii",
    "vat": "rejestry i JPK w Symfonii",
    "assets": "Symfonia Środki Trwałe",
    "payroll": "Enova 365 Kadry i Płace",
    "reports": "Symfonia FK",
}
#: Moduły z gotowymi ekranami (kolejne etapy dopisują tu swój klucz).
BUILT: frozenset[str] = frozenset({"ledger", "automations"})
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


@dataclass(frozen=True)
class LedgerSettings:
    modules: dict[str, bool]
    accountants: tuple[int, ...]
    sales: SalesAccounts = field(default_factory=SalesAccounts)
    allocation: AllocationAccounts = field(default_factory=AllocationAccounts)


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
    db: AsyncSession, values: dict[str, str], fields: dict[str, tuple[str, str]]
) -> dict[str, str]:
    """Każde konto z formularza musi być aktywne w planie kont."""

    cleaned: dict[str, str] = {}
    for key, (_, label) in fields.items():
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
