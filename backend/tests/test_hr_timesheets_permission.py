"""Uprawnienie „Raporty godzin” (0612, 28.10.2026): akceptacja timesheetów
całej firmy bez reszty „Kadr” — katalog, migracja, CHECK i reguły akceptującego."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from app.services import permission_catalog as catalog
from app.services import permission_schema
from app.services.hr.time_access import Actor

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic/versions/0612_timesheets_permission.py"

ME = 7
MY_REPORT = 8
CHARGE = 9
STRANGER = 10


def _migration():
    spec = importlib.util.spec_from_file_location("m0609", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _profile(user_id: int, manager_user_id: int | None = 99):
    return SimpleNamespace(user_id=user_id, manager_user_id=manager_user_id)


def _actor(**flags) -> Actor:
    values = {"is_admin": False, "people_admin": False, "payroll": False, **flags}
    return Actor(
        user=SimpleNamespace(id=ME),
        profile=None,
        charges=frozenset({CHARGE}),
        **values,
    )


def test_permission_sits_in_people_group_at_the_end_of_the_catalog() -> None:
    assert catalog.SEEDED_KEYS[-1] == catalog.TIMESHEETS
    assert catalog.BY_KEY[catalog.TIMESHEETS].group == "people"
    assert catalog.close((catalog.TIMESHEETS,)) == {catalog.TIMESHEETS}
    assert catalog.derive_sections({catalog.TIMESHEETS}) == {
        "delivery": "none",
        "finance": "none",
    }


def test_nobody_but_admin_holds_it_by_default() -> None:
    for role in catalog.ROLES:
        held = catalog.default_permissions_for_role(role)
        assert (catalog.TIMESHEETS in held) is (role == catalog.ADMIN)


def test_entrypoint_check_and_migration_know_the_permission() -> None:
    entry = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    assert entry.count(permission_schema.ACTION_CHECK_SQL) == len(
        permission_schema.ACTION_TABLES
    )
    assert f"'{catalog.TIMESHEETS}'" in permission_schema.ACTION_CHECK_SQL
    module = _migration()
    assert set(module.ROLES_AT_0609) <= set(catalog.ROLES)
    assert module.ROLES_AT_0609[0] == catalog.ADMIN


def test_holder_approves_everyone_but_not_self() -> None:
    actor = _actor(timesheets=True)
    assert actor.approves_everyone
    assert actor.is_approver
    assert actor.can_approve(_profile(STRANGER))
    assert actor.can_read(_profile(STRANGER))
    assert not actor.can_approve(_profile(ME))


def test_holder_does_not_see_leave_type_outside_own_team() -> None:
    """D6: rodzaj nieobecności widzą osoba, przełożony, head pionu, Kadry, admin."""

    actor = _actor(timesheets=True)
    assert not actor.sees_leave_type(_profile(STRANGER))
    assert actor.sees_leave_type(_profile(MY_REPORT, manager_user_id=ME))
    assert actor.sees_leave_type(_profile(CHARGE, manager_user_id=None))
    assert actor.sees_leave_type(_profile(ME))
    # Kadry i admin — bez zmian.
    assert _actor(timesheets=True, people_admin=True).sees_leave_type(
        _profile(STRANGER)
    )
    assert _actor(is_admin=True).sees_leave_type(_profile(STRANGER))


def test_holder_does_not_get_overtime_rights_of_people_admin() -> None:
    assert not _actor(timesheets=True).overtime_allowed
    assert _actor(people_admin=True).overtime_allowed


def test_payroll_alone_still_does_not_approve() -> None:
    actor = _actor(payroll=True)
    assert not actor.approves_everyone
    assert not actor.can_approve(_profile(STRANGER))
    assert actor.can_read(_profile(STRANGER))
