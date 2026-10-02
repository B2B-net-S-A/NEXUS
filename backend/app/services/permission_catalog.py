"""Katalog dziewięciu uprawnień z ekranu Ustawienia → Osoby i role.

Jedyne miejsce, w którym stoi: jak uprawnienie się nazywa, do której grupy
należy, co za sobą pociąga i która rola ma je domyślnie. Moduł jest czysty —
bez modeli i bez bazy — bo czytają go migracja, zasiew przy starcie, resolver
uprawnień, API panelu i (przez wspólny plik JSON) frontend.

Zasady:

* uprawnienie jest tak/nie; zapisujemy je mechanizmem akcji jako
  ``manage`` / ``none``,
* **zależności** liczą się przy odczycie: kto ma edycję, ten ma podgląd,
* **sekcje** Delivery i Finanse nie są już ustawiane ręcznie — wynikają
  z uprawnień (``derive_sections``),
* zakres klientów zostaje przy personie: konto z rolą Delivery Leada działa
  u swoich klientów, pozostali posiadacze — u wszystkich.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

DELIVERY_VIEW = "delivery_view"
CLIENTS_EDIT = "clients_edit"
CONTRACTS_ORDERS_EDIT = "contracts_orders_edit"
CONTRACT_STATUS = "contract_status"
SIGNATURE = "b2b_signature_confirmation"
RECRUITMENT_MANAGE = "recruitment_manage"
AMOUNTS_VIEW = "amounts_view"
AMOUNTS_EDIT = "amounts_edit"
FINANCE_MODULE = "finance_module"

#: Poziomowa akcja sprzed katalogu — nie jest jednym z dziewięciu uprawnień.
GENERATOR = "b2b_contract_generator"

ADMIN = "admin"
#: Role w kolejności ekranu. CHECK ``ck_rbac_role_*_permissions_role`` jest
#: szerszy: zna też wycofane w 0411 ``tac`` i ``sourcer`` (rollback obrazu).
#: Zasiew przy starcie dopełnia wiersze TYLKO dla ról z tej listy — wycofana
#: rola tutaj oznaczałaby odtwarzanie skasowanych wierszy przy każdym starcie.
ROLES: tuple[str, ...] = (
    "admin",
    "finance",
    "head_of_recruitment",
    "delivery_lead",
    "talent_community_manager",
    "recruiter",
    "user",
    "trainee",
)

_LEVELS = {"none": 0, "read": 1, "write": 2}


@dataclass(frozen=True)
class Holder:
    """Rola, która ma uprawnienie domyślnie, i warunek zasiewu.

    ``needs`` to minimalne poziomy ZAPISANYCH sekcji roli. Admin mógł wcześniej
    odebrać roli sekcję w starym panelu — zasiew tego nie cofa.
    """

    role: str
    needs: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Permission:
    key: str
    label: str
    group: str
    requires: tuple[str, ...] = ()
    holders: tuple[Holder, ...] = ()
    #: ``False`` = wiersze już istnieją w bazie (podpis B2B, migracja 0282).
    seeded: bool = True

    @property
    def default_roles(self) -> tuple[str, ...]:
        return tuple(holder.role for holder in self.holders)


@dataclass(frozen=True)
class Group:
    key: str
    label: str
    permissions: tuple[str, ...] = field(default_factory=tuple)


def _needs(**sections: str) -> tuple[tuple[str, str], ...]:
    return tuple(sections.items())


PERMISSIONS: tuple[Permission, ...] = (
    Permission(
        DELIVERY_VIEW,
        "Klienci, kontrakty i zamówienia: podgląd",
        "clients_contracts",
        holders=(
            Holder("finance", _needs(delivery="read")),
            Holder("delivery_lead", _needs(delivery="read")),
            Holder("talent_community_manager", _needs(delivery="read")),
        ),
    ),
    Permission(
        CLIENTS_EDIT,
        "Klienci: dodawanie i edycja",
        "clients_contracts",
        requires=(DELIVERY_VIEW,),
        holders=(Holder("delivery_lead", _needs(delivery="write")),),
    ),
    Permission(
        CONTRACTS_ORDERS_EDIT,
        "Kontrakty i zamówienia: tworzenie i edycja",
        "clients_contracts",
        requires=(DELIVERY_VIEW,),
        holders=(
            Holder("delivery_lead", _needs(delivery="write")),
            # Decyzja Artura 02.10.2026: Finanse zakładają kontrakty i zamówienia.
            Holder("finance", _needs(delivery="write")),
        ),
    ),
    Permission(
        CONTRACT_STATUS,
        "Zakończenie współpracy, zmiana statusu kontraktu",
        "clients_contracts",
        requires=(DELIVERY_VIEW,),
        holders=(
            Holder("delivery_lead", _needs(delivery="write")),
            # TCM zmieniał status już przy samym odczycie Delivery (wyjątek
            # w bramce sekcji) — stąd niższy próg niż u Delivery Leada.
            Holder("talent_community_manager", _needs(delivery="read")),
        ),
    ),
    Permission(
        SIGNATURE,
        "Umowy B2B: oznaczanie jako podpisane",
        "clients_contracts",
        holders=(Holder("delivery_lead"), Holder("talent_community_manager")),
        seeded=False,
    ),
    Permission(
        RECRUITMENT_MANAGE,
        "Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta",
        "recruitment",
        holders=(Holder("delivery_lead", _needs(pipeline="write")),),
    ),
    Permission(
        AMOUNTS_VIEW,
        "Stawki i kwoty: podgląd",
        "money",
        requires=(DELIVERY_VIEW,),
        holders=(
            Holder("finance", _needs(delivery="read", finance="read")),
            Holder("delivery_lead", _needs(delivery="read")),
        ),
    ),
    Permission(
        AMOUNTS_EDIT,
        "Stawki i kwoty: zmiana",
        "money",
        requires=(AMOUNTS_VIEW,),
        holders=(Holder("finance", _needs(finance="write")),),
    ),
    Permission(
        FINANCE_MODULE,
        "Moduł Finanse",
        "money",
        requires=(AMOUNTS_VIEW,),
        holders=(Holder("finance", _needs(finance="write")),),
    ),
)

GROUPS: tuple[Group, ...] = tuple(
    Group(
        key,
        label,
        tuple(permission.key for permission in PERMISSIONS if permission.group == key),
    )
    for key, label in (
        ("clients_contracts", "Klienci i kontrakty"),
        ("recruitment", "Rekrutacje"),
        ("money", "Pieniądze"),
    )
)

BY_KEY: dict[str, Permission] = {
    permission.key: permission for permission in PERMISSIONS
}
KEYS: tuple[str, ...] = tuple(BY_KEY)
#: Klucze, których wiersze zakłada migracja 0410 (wszystko poza podpisem B2B).
SEEDED_KEYS: tuple[str, ...] = tuple(
    permission.key for permission in PERMISSIONS if permission.seeded
)

#: Uprawnienia, z których wynika ZAPIS w sekcji Delivery (trasy mutujące
#: klientów, kontrakty i zamówienia stoją za tą sekcją).
_DELIVERY_WRITE = (CLIENTS_EDIT, CONTRACTS_ORDERS_EDIT, CONTRACT_STATUS, AMOUNTS_EDIT)


def label(key: str) -> str:
    return BY_KEY[key].label


def close(granted: Iterable[str]) -> frozenset[str]:
    """Nadane uprawnienia razem z tymi, które z nich wynikają."""

    effective: set[str] = set()
    pending = [key for key in granted if key in BY_KEY]
    while pending:
        key = pending.pop()
        if key in effective:
            continue
        effective.add(key)
        pending.extend(BY_KEY[key].requires)
    return frozenset(effective)


def implied_by(key: str, granted: Iterable[str]) -> tuple[str, ...]:
    """Które z nadanych uprawnień wymuszają ``key`` (do opisu na ekranie)."""

    return tuple(
        other
        for other in KEYS
        if other != key and other in set(granted) and key in close((other,))
    )


def derive_sections(effective: Iterable[str]) -> dict[str, str]:
    """Poziom sekcji Delivery i Finanse wynikający z uprawnień."""

    held = set(effective)
    if held.intersection(_DELIVERY_WRITE):
        delivery = "write"
    elif DELIVERY_VIEW in held:
        delivery = "read"
    else:
        delivery = "none"
    return {
        "delivery": delivery,
        "finance": "write" if FINANCE_MODULE in held else "none",
    }


def default_permissions_for_role(role: str) -> frozenset[str]:
    """Domyślny zestaw roli z ekranu (bez progów zasiewu), z zależnościami."""

    if role == ADMIN:
        return frozenset(KEYS)
    return close(
        permission.key for permission in PERMISSIONS if role in permission.default_roles
    )


def seed_rows_for_role(role: str, section_levels: Mapping[str, str]) -> dict[str, str]:
    """Wiersze zasiewu jednej roli: ``{klucz: "manage" | "none"}``.

    ``section_levels`` to ZAPISANE poziomy sekcji roli. Ta sama reguła jest
    zapisana w SQL-u (``permission_schema.SEED_SQL``); zgodność obu pilnuje
    test migracji.
    """

    rows: dict[str, str] = {}
    for permission in PERMISSIONS:
        if not permission.seeded:
            continue
        if role == ADMIN:
            rows[permission.key] = "manage"
            continue
        holder = next((h for h in permission.holders if h.role == role), None)
        granted = holder is not None and all(
            _LEVELS.get(section_levels.get(section, "none"), 0) >= _LEVELS[minimum]
            for section, minimum in holder.needs
        )
        rows[permission.key] = "manage" if granted else "none"
    return rows


def as_fixture() -> dict[str, object]:
    """Kształt wspólnego pliku ``frontend/src/lib/permission-catalog.json``."""

    return {
        "groups": [
            {
                "key": group.key,
                "label": group.label,
                "permissions": list(group.permissions),
            }
            for group in GROUPS
        ],
        "permissions": [
            {
                "key": permission.key,
                "label": permission.label,
                "group": permission.group,
                "requires": list(permission.requires),
                "default_roles": list(permission.default_roles),
            }
            for permission in PERMISSIONS
        ],
    }
