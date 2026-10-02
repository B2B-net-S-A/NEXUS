"""Katalog dziewięciu uprawnień: nazwy, zależności, zasiew i lustra."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.section_permission import RoleActionPermission, UserActionOverride
from app.models.user import UserRole
from app.services import permission_catalog as catalog
from app.services import permission_schema as schema
from app.services.action_permissions import (
    DEFAULT_ROLE_ACTION_ACCESS,
    NAMED_PERMISSIONS,
    ActionAccess,
    ProductAction,
)

BACKEND = Path(__file__).resolve().parents[1]
FRONTEND_CATALOG = BACKEND.parent / "frontend/src/lib/permission-catalog.json"

# Macierz z planu (decyzje Artura 02.10.2026): kto ma co domyślnie.
EXPECTED_DEFAULTS: dict[str, set[str]] = {
    "admin": set(catalog.KEYS),
    "finance": {
        "delivery_view",
        "contracts_orders_edit",
        "amounts_view",
        "amounts_edit",
        "finance_module",
    },
    "head_of_recruitment": set(),
    "delivery_lead": {
        "delivery_view",
        "clients_edit",
        "contracts_orders_edit",
        "contract_status",
        "b2b_signature_confirmation",
        "recruitment_manage",
        "amounts_view",
    },
    "talent_community_manager": {
        "delivery_view",
        "contract_status",
        "b2b_signature_confirmation",
    },
    "recruiter": set(),
    "user": set(),
    "trainee": set(),
}

PRODUCTION_SECTIONS: dict[str, dict[str, str]] = {
    "finance": {"delivery": "write", "finance": "write", "pipeline": "write"},
    "delivery_lead": {"delivery": "write", "finance": "none", "pipeline": "write"},
    "talent_community_manager": {"delivery": "write", "pipeline": "write"},
    "recruiter": {"delivery": "none", "pipeline": "write"},
}


def test_screen_shows_nine_permissions_in_three_groups() -> None:
    assert [permission.label for permission in catalog.PERMISSIONS] == [
        "Klienci, kontrakty i zamówienia: podgląd",
        "Klienci: dodawanie i edycja",
        "Kontrakty i zamówienia: tworzenie i edycja",
        "Zakończenie współpracy, zmiana statusu kontraktu",
        "Umowy B2B: oznaczanie jako podpisane",
        "Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta",
        "Stawki i kwoty: podgląd",
        "Stawki i kwoty: zmiana",
        "Moduł Finanse",
    ]
    assert [(group.label, len(group.permissions)) for group in catalog.GROUPS] == [
        ("Klienci i kontrakty", 5),
        ("Rekrutacje", 1),
        ("Pieniądze", 3),
    ]
    assert sum(len(group.permissions) for group in catalog.GROUPS) == 9


def test_catalog_roles_are_exactly_the_application_roles() -> None:
    assert set(catalog.ROLES) == {role.value for role in UserRole}


@pytest.mark.parametrize("role", sorted(EXPECTED_DEFAULTS))
def test_default_permissions_match_the_agreed_matrix(role: str) -> None:
    assert catalog.default_permissions_for_role(role) == EXPECTED_DEFAULTS[role]
    held = {
        action.value
        for action in NAMED_PERMISSIONS
        if DEFAULT_ROLE_ACTION_ACCESS[UserRole(role)][action] is ActionAccess.manage
    }
    assert held == EXPECTED_DEFAULTS[role]


def test_named_permissions_are_binary_in_the_static_matrix() -> None:
    for policy in DEFAULT_ROLE_ACTION_ACCESS.values():
        for action in NAMED_PERMISSIONS:
            assert policy[action] in {ActionAccess.none, ActionAccess.manage}


def test_edit_permissions_pull_in_what_they_need() -> None:
    assert catalog.close(["clients_edit"]) == {"clients_edit", "delivery_view"}
    assert catalog.close(["amounts_edit"]) == {
        "amounts_edit",
        "amounts_view",
        "delivery_view",
    }
    assert catalog.close(["finance_module"]) == {
        "finance_module",
        "amounts_view",
        "delivery_view",
    }
    # Podpis B2B i rekrutacje nie otwierają Delivery.
    assert catalog.close(["b2b_signature_confirmation", "recruitment_manage"]) == {
        "b2b_signature_confirmation",
        "recruitment_manage",
    }
    assert catalog.close(["unknown"]) == frozenset()
    assert catalog.implied_by("delivery_view", ["clients_edit", "amounts_edit"]) == (
        "clients_edit",
        "amounts_edit",
    )
    assert catalog.implied_by("clients_edit", ["delivery_view"]) == ()


@pytest.mark.parametrize(
    "held,delivery,finance",
    [
        ([], "none", "none"),
        (["delivery_view"], "read", "none"),
        (["delivery_view", "amounts_view"], "read", "none"),
        (["delivery_view", "clients_edit"], "write", "none"),
        (["delivery_view", "contract_status"], "write", "none"),
        (["delivery_view", "contracts_orders_edit"], "write", "none"),
        (["delivery_view", "amounts_view", "amounts_edit"], "write", "none"),
        (["delivery_view", "amounts_view", "finance_module"], "read", "write"),
        (["recruitment_manage", "b2b_signature_confirmation"], "none", "none"),
    ],
)
def test_sections_follow_from_permissions(held, delivery, finance) -> None:
    assert catalog.derive_sections(held) == {"delivery": delivery, "finance": finance}


def test_seed_reproduces_production_for_default_roles() -> None:
    for role, sections in PRODUCTION_SECTIONS.items():
        rows = catalog.seed_rows_for_role(role, sections)
        assert set(rows) == set(catalog.SEEDED_KEYS)
        granted = {key for key, access in rows.items() if access == "manage"}
        assert granted == EXPECTED_DEFAULTS[role] - {catalog.SIGNATURE}, role
    assert set(catalog.seed_rows_for_role("admin", {}).values()) == {"manage"}


def test_seed_respects_a_section_the_admin_took_away() -> None:
    """Zasiew nie cofa wcześniejszej decyzji z panelu sekcji."""

    read_only_lead = catalog.seed_rows_for_role(
        "delivery_lead", {"delivery": "read", "pipeline": "write"}
    )
    assert read_only_lead["delivery_view"] == "manage"
    assert read_only_lead["amounts_view"] == "manage"
    assert read_only_lead["clients_edit"] == "none"
    assert read_only_lead["contracts_orders_edit"] == "none"
    assert read_only_lead["contract_status"] == "none"

    no_pipeline = catalog.seed_rows_for_role("delivery_lead", {"delivery": "write"})
    assert no_pipeline["recruitment_manage"] == "none"

    finance_without_module = catalog.seed_rows_for_role(
        "finance", {"delivery": "write", "finance": "none"}
    )
    assert finance_without_module["finance_module"] == "none"
    assert finance_without_module["amounts_edit"] == "none"
    assert finance_without_module["amounts_view"] == "none"
    assert finance_without_module["contracts_orders_edit"] == "manage"

    # Świeża baza: TCM ma w zasiewie 0269 sam odczyt Delivery, a status
    # kontraktu zmieniał już wtedy (wyjątek w bramce sekcji).
    fresh_tcm = catalog.seed_rows_for_role(
        "talent_community_manager", {"delivery": "read"}
    )
    assert fresh_tcm["contract_status"] == "manage"
    assert (
        catalog.seed_rows_for_role("talent_community_manager", {})["contract_status"]
        == "none"
    )


def test_action_enum_is_the_generator_plus_the_catalog() -> None:
    assert {action.value for action in ProductAction} == set(schema.ACTIONS)
    assert [action.value for action in NAMED_PERMISSIONS] == list(catalog.KEYS)
    assert ProductAction.b2b_contract_generator not in NAMED_PERMISSIONS


def test_one_check_definition_everywhere() -> None:
    for action in ProductAction:
        assert f"'{action.value}'" in schema.ACTION_CHECK_SQL
    for model in (RoleActionPermission, UserActionOverride):
        checks = [
            str(constraint.sqltext)
            for constraint in model.__table__.constraints
            if str(getattr(constraint, "name", None) or "").endswith("_action")
        ]
        assert checks == [schema.ACTION_CHECK_SQL]

    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert entrypoint.count(schema.ACTION_CHECK_SQL) == len(schema.ACTION_TABLES)
    lines = [line.strip() for line in entrypoint.splitlines()]
    signature = lines.index("python -m app.services.signature_policy_bootstrap")
    named = lines.index("python -m app.services.named_permissions_bootstrap")
    assert (
        signature
        < named
        < lines.index("exec uvicorn app.main:app --host 0.0.0.0 --port 8000")
    )

    # Ponowne uruchomienie 0282 przy starcie nie może zwęzić CHECK-a.
    migration_0282 = (
        BACKEND / "alembic/versions/0282_b2b_signature_permission.py"
    ).read_text(encoding="utf-8")
    assert "ACTION_CHECK_SQL" in migration_0282
    upgrade = migration_0282.split("def downgrade()")[0]
    assert "action IN (" not in upgrade


def test_seed_sql_never_overwrites_a_decision_from_the_panel() -> None:
    assert "ON CONFLICT (role, action) DO NOTHING" in schema.SEED_SQL
    assert "DO UPDATE" not in schema.SEED_SQL
    assert "updated_by IS NULL" in schema.TAC_SIGNATURE_SQL
    # ``op.execute`` zamienia „:słowo” na parametr — w SQL-u ich nie ma.
    for statement in schema.apply_statements():
        assert ":" not in statement


def test_frontend_reads_the_same_catalog() -> None:
    assert json.loads(FRONTEND_CATALOG.read_text(encoding="utf-8")) == (
        catalog.as_fixture()
    ), (
        "frontend/src/lib/permission-catalog.json rozjechał się z katalogiem — "
        "wygeneruj go z permission_catalog.as_fixture()"
    )
