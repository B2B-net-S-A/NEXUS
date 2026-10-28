"""„Ludzie w NEXUSIE” — kontrakt łańcucha migracji modułów i lustra entrypointu.

Moduły kadrowe mają po jednej migracji (0457–0465), a SQL każdej żyje
w ``app/services/<moduł>_schema.py``. Entrypoint bierze go przez agregator
``hr_schema_bundle`` — test pilnuje, że żaden moduł nie wypadł z agregatora
i że wartości enumów stoją literalnie w ``_ENUM_STATEMENTS``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.models.notification import NotificationType
from app.services import hr_notification_schema, hr_schema_bundle
from app.services.notification_access import (
    ALWAYS_VISIBLE_NOTIFICATION_TYPES,
    NOTIFICATION_SECTION_BY_TYPE,
)
from app.services.notification_categories import (
    CATEGORY_BY_TYPE,
    NotificationCategory,
)
from app.services.section_permissions import ProductSection

_BACKEND = Path(__file__).resolve().parent.parent
_VERSIONS = _BACKEND / "alembic" / "versions"

CHAIN = (
    ("0457_hr_notifications", "0456_hr_access", "hr_notification_schema"),
    ("0458_hr_leave", "0457_hr_notifications", "hr_leave_schema"),
    ("0459_hr_time", "0458_hr_leave", "hr_time_schema"),
    ("0460_hr_payroll", "0459_hr_time", "hr_payroll_schema"),
    ("0461_hr_lifecycle", "0460_hr_payroll", "hr_lifecycle_schema"),
    ("0462_contract_care", "0461_hr_lifecycle", "contract_care_schema"),
    ("0463_admin_cases", "0462_contract_care", "admin_cases_schema"),
    ("0464_equipment", "0463_admin_cases", "equipment_schema"),
    ("0465_equipment_extras", "0464_equipment", "equipment_extras_schema"),
    ("0466_care_announcements", "0465_equipment_extras", "care_announcements_schema"),
    # Rozliczenia (etap 4) idą za migracją statystyk z maina (0467).
    (
        "0468_hr_settlements",
        "0467_kpi_milestones_history_only_dr",
        "hr_settlement_schema",
    ),
    ("0469_hr_documents", "0468_hr_settlements", "hr_documents_schema"),
    ("0470_hr_agreements", "0469_hr_documents", "hr_agreements_schema"),
    (
        "0471_client_sales_invoices",
        "0470_hr_agreements",
        "client_sales_invoices_schema",
    ),
    # Załącznik do wniosku urlopowego idzie za ręcznym uzupełnieniem statystyk (0472).
    (
        "0473_hr_leave_proofs",
        "0472_kpi_milestones_manual_fill",
        "hr_leave_proofs_schema",
    ),
    # Imię i nazwisko konsultanta na karcie z Compassa (18.10.2026).
    ("0474_tech_card_person", "0473_hr_leave_proofs", "contract_care_schema"),
    (
        "0475_client_structure_proposals",
        "0474_tech_card_person",
        "client_structure_schema",
    ),
    # Kartoteka idzie za kontem (19.10.2026).
    (
        "0476_hr_profile_follows_account",
        "0475_client_structure_proposals",
        "hr_account_profile_schema",
    ),
    # Zgody na wydatki i premie poza umową (20.10.2026) — za Prepem 2 z maina.
    ("0483_hr_approvals", "0482_prep2_skips", "hr_approvals_schema"),
    # Podstawa w umowie przy premii poza umową (21.10.2026) — za rolą Rady (0490).
    (
        "0491_approval_contract_basis",
        "0490_board_role",
        "hr_approval_basis_schema",
    ),
    # Tablica opieki i popyt dla DL (22.10.2026).
    (
        "0509_care_board",
        "0508_candidate_data_access_alert",
        "care_board_schema",
    ),
    # Poprawka i anulowanie protokołu sprzętu (28.10.2026).
    (
        "0609_equipment_protocol_cancel",
        "0608_linkedin_extension",  # down_revision — przepina rechain_migration.py
        "equipment_protocol_cancel_schema",
    ),
)


def _load_migration(revision: str):
    # Po synchronizacji z main numer może się przesunąć — szukamy po sufiksie.
    suffix = revision.split("_", 1)[1]
    matches = sorted(_VERSIONS.glob(f"*_{suffix}.py"))
    assert len(matches) == 1, f"migracja *_{suffix}.py: {matches}"
    spec = importlib.util.spec_from_file_location(matches[0].stem, matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("revision", "down", "schema_module"), CHAIN)
def test_migrations_form_one_line_and_read_their_schema_module(
    revision: str, down: str, schema_module: str
) -> None:
    migration = _load_migration(revision)
    assert migration.down_revision.split("_", 1)[1] == down.split("_", 1)[1]
    assert migration.schema.__name__ == f"app.services.{schema_module}"


@pytest.mark.parametrize("module", hr_schema_bundle.MODULES, ids=lambda m: m.__name__)
def test_bundle_carries_every_statement_of_every_module(module) -> None:
    for stmt in (*module.TABLE_DDL, *module.COLUMN_DDL, *module.INDEX_DDL):
        assert stmt in hr_schema_bundle.COLUMN_DDL
    for stmt in module.CONSTRAINT_DDL:
        assert stmt in hr_schema_bundle.CONSTRAINT_DDL
    for stmt in module.DATA_DDL:
        assert stmt in hr_schema_bundle.DATA_DDL
    assert module.ALL_DDL == (
        *module.TABLE_DDL,
        *module.COLUMN_DDL,
        *module.INDEX_DDL,
        *module.CONSTRAINT_DDL,
        *module.DATA_DDL,
    )


def test_module_statements_are_idempotent() -> None:
    """Entrypoint wykonuje SQL przy każdym starcie — tylko formy „IF NOT EXISTS”."""
    for module in hr_schema_bundle.MODULES:
        for stmt in module.TABLE_DDL:
            assert "CREATE TABLE IF NOT EXISTS" in stmt, stmt[:80]
        for stmt in module.INDEX_DDL:
            assert "INDEX IF NOT EXISTS" in stmt, stmt[:80]
        for stmt in module.COLUMN_DDL:
            assert "IF NOT EXISTS" in stmt or stmt.lstrip().startswith("DO"), stmt[:80]


def test_entrypoint_lists_every_hr_enum_value_literally() -> None:
    entrypoint = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    enum_block = entrypoint.split("_ENUM_STATEMENTS = [", 1)[1].split("\n]", 1)[0]
    for stmt in hr_schema_bundle.ENUM_DDL:
        assert f'"{stmt}"' in enum_block, stmt


def test_hr_notification_types_are_personal_or_delivery() -> None:
    for value in hr_notification_schema.PERSONAL_TYPES:
        ntype = NotificationType(value)
        assert ntype in ALWAYS_VISIBLE_NOTIFICATION_TYPES
        assert ntype not in NOTIFICATION_SECTION_BY_TYPE
        assert CATEGORY_BY_TYPE[ntype] is NotificationCategory.people
    for value in hr_notification_schema.DELIVERY_TYPES:
        ntype = NotificationType(value)
        assert NOTIFICATION_SECTION_BY_TYPE[ntype] is ProductSection.delivery
        assert ntype not in ALWAYS_VISIBLE_NOTIFICATION_TYPES
