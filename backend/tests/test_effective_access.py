"""Resolver dostępu: uprawnienia z zależnościami i wyliczane sekcje."""

from __future__ import annotations

from types import SimpleNamespace

from app.models.user import UserRole
from app.services import permission_catalog as catalog
from app.services.action_permissions import (
    ActionAccess,
    ProductAction,
    has_permission,
    named_permissions_of,
)
from app.services.effective_access import effective_access_from_rows
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)

# Zapisane sekcje jak na produkcji (02.10.2026): TCM ma Delivery „zapis”.
SECTIONS: dict[str, dict[str, str]] = {
    "finance": {
        "sourcing": "write",
        "pipeline": "write",
        "delivery": "write",
        "insights": "read",
        "finance": "write",
    },
    "head_of_recruitment": {
        "sourcing": "write",
        "pipeline": "write",
        "insights": "write",
    },
    "delivery_lead": {
        "sourcing": "write",
        "pipeline": "write",
        "delivery": "write",
        "insights": "read",
    },
    "talent_community_manager": {
        "sourcing": "write",
        "pipeline": "write",
        "delivery": "write",
        "insights": "read",
    },
    "recruiter": {"sourcing": "write", "pipeline": "write", "insights": "read"},
}
SIGNATORIES = {"delivery_lead", "talent_community_manager"}


def _user(*roles: UserRole, user_id: int = 17):
    role_set = set(roles)
    return SimpleNamespace(
        id=user_id,
        get_all_roles=lambda: role_set,
        has_role=lambda role: role in role_set,
        has_any_role=lambda *required: bool(role_set.intersection(required)),
    )


def _section_rows() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(role=role, section=section, access=access)
        for role, sections in SECTIONS.items()
        for section, access in sections.items()
    ]


def _action_rows(*, seeded: bool = True) -> list[SimpleNamespace]:
    rows = []
    for role, sections in SECTIONS.items():
        rows.append(
            SimpleNamespace(role=role, action="b2b_contract_generator", access="manage")
        )
        rows.append(
            SimpleNamespace(
                role=role,
                action="b2b_signature_confirmation",
                access="manage" if role in SIGNATORIES else "none",
            )
        )
        if seeded:
            rows.extend(
                SimpleNamespace(role=role, action=key, access=access)
                for key, access in catalog.seed_rows_for_role(role, sections).items()
            )
    return rows


def _resolve(user, *, action_rows=None, action_overrides=(), section_overrides=()):
    return effective_access_from_rows(
        user,
        section_role_rows=_section_rows(),
        section_override_rows=list(section_overrides),
        action_role_rows=_action_rows() if action_rows is None else action_rows,
        action_override_rows=list(action_overrides),
    )


def test_finance_gets_contracts_and_the_finance_module() -> None:
    access = _resolve(_user(UserRole.finance))

    assert access.permissions == {
        "delivery_view",
        "contracts_orders_edit",
        "amounts_view",
        "amounts_edit",
        "finance_module",
    }
    assert access.sections[ProductSection.delivery] is SectionAccess.write
    assert access.sections[ProductSection.finance] is SectionAccess.write
    assert access.sections[ProductSection.insights] is SectionAccess.read
    assert access.sections[ProductSection.system_admin] is SectionAccess.none


def test_delivery_lead_and_talent_community_manager_keep_their_work() -> None:
    lead = _resolve(_user(UserRole.delivery_lead))
    assert lead.permissions == {
        "delivery_view",
        "clients_edit",
        "contracts_orders_edit",
        "contract_status",
        "b2b_signature_confirmation",
        "recruitment_manage",
        "amounts_view",
    }
    assert lead.sections[ProductSection.delivery] is SectionAccess.write
    assert lead.sections[ProductSection.finance] is SectionAccess.none

    tcm = _resolve(_user(UserRole.talent_community_manager))
    assert tcm.permissions == {
        "delivery_view",
        "contract_status",
        "b2b_signature_confirmation",
    }
    assert tcm.sections[ProductSection.delivery] is SectionAccess.write
    assert tcm.sections[ProductSection.finance] is SectionAccess.none


def test_roles_without_permissions_do_not_enter_delivery() -> None:
    for role in (UserRole.recruiter, UserRole.head_of_recruitment):
        access = _resolve(_user(role))
        assert access.permissions == frozenset()
        assert access.sections[ProductSection.delivery] is SectionAccess.none
        assert access.sections[ProductSection.finance] is SectionAccess.none
        assert access.sections[ProductSection.pipeline] is SectionAccess.write
        assert access.actions[ProductAction.b2b_contract_generator] is (
            ActionAccess.manage
        )


def test_admin_holds_everything() -> None:
    access = _resolve(_user(UserRole.admin), action_rows=[])
    assert access.permissions == set(catalog.KEYS)
    assert set(access.sections.values()) == {SectionAccess.write}


def test_multi_role_account_is_the_union_of_its_roles() -> None:
    access = _resolve(_user(UserRole.recruiter, UserRole.talent_community_manager))
    assert access.permissions == {
        "delivery_view",
        "contract_status",
        "b2b_signature_confirmation",
    }
    assert access.sections[ProductSection.delivery] is SectionAccess.write


def test_extra_permission_for_one_person_adds_to_the_role() -> None:
    """Konto TCM dostaje tworzenie kontraktów bez zmiany roli."""

    tcm = _user(UserRole.talent_community_manager, user_id=41)
    grant = [
        SimpleNamespace(user_id=41, action="contracts_orders_edit", access="manage")
    ]
    access = _resolve(tcm, action_overrides=grant)

    assert "contracts_orders_edit" in access.permissions
    assert "amounts_view" not in access.permissions
    assert access.sections[ProductSection.delivery] is SectionAccess.write

    # Wiersz innej osoby nie działa na to konto.
    other = [SimpleNamespace(user_id=42, action="clients_edit", access="manage")]
    assert "clients_edit" not in _resolve(tcm, action_overrides=other).permissions


def test_a_grant_stops_working_when_the_account_becomes_a_viewer() -> None:
    """Zmiana roli nie kasuje wierszy nadań — resolver przestaje je liczyć.

    Ekran odmawia nadania Viewerowi i Praktykantowi; konto zdegradowane do
    takiej roli nie może zachować tego, czego nie dałoby się mu nadać.
    """

    grant = [SimpleNamespace(user_id=17, action="clients_edit", access="manage")]
    for role in (UserRole.user, UserRole.trainee):
        access = _resolve(_user(role), action_overrides=grant)
        assert access.permissions == frozenset()
        assert access.sections[ProductSection.delivery] is SectionAccess.none

    # Rola, która przyjmuje nadania, obok roli Viewera — nadanie działa.
    mixed = _resolve(_user(UserRole.user, UserRole.recruiter), action_overrides=grant)
    assert "clients_edit" in mixed.permissions


def test_granting_an_edit_permission_brings_the_view_with_it() -> None:
    recruiter = _user(UserRole.recruiter)
    grant = [SimpleNamespace(user_id=17, action="clients_edit", access="manage")]
    access = _resolve(recruiter, action_overrides=grant)

    assert access.permissions == {"clients_edit", "delivery_view"}
    assert access.sections[ProductSection.delivery] is SectionAccess.write
    assert access.sections[ProductSection.finance] is SectionAccess.none


def test_view_cannot_be_taken_away_while_an_edit_permission_stays() -> None:
    lead = _user(UserRole.delivery_lead)
    restriction = [SimpleNamespace(user_id=17, action="delivery_view", access="none")]
    access = _resolve(lead, action_overrides=restriction)

    assert "delivery_view" in access.permissions


def test_person_restriction_takes_a_permission_away() -> None:
    lead = _user(UserRole.delivery_lead)
    restriction = [SimpleNamespace(user_id=17, action="clients_edit", access="none")]
    access = _resolve(lead, action_overrides=restriction)

    assert "clients_edit" not in access.permissions
    assert "contracts_orders_edit" in access.permissions


def test_named_permission_is_yes_or_no() -> None:
    """Poziomy generatora („view”, „generate”) nie nadają uprawnienia z ekranu."""

    rows = _action_rows()
    for row in rows:
        if row.role == "delivery_lead" and row.action == "clients_edit":
            row.access = "generate"
    access = _resolve(_user(UserRole.delivery_lead), action_rows=rows)

    assert "clients_edit" not in access.permissions
    assert access.actions[ProductAction.clients_edit] is ActionAccess.none


def test_role_without_seeded_rows_is_resolved_by_the_seed_rule() -> None:
    """Start bez migracji 0410 nie odbiera nikomu Delivery."""

    unseeded = _action_rows(seeded=False)
    for role in (
        UserRole.finance,
        UserRole.delivery_lead,
        UserRole.talent_community_manager,
        UserRole.recruiter,
    ):
        before = _resolve(_user(role))
        after = _resolve(_user(role), action_rows=unseeded)
        assert after.permissions == before.permissions, role
        assert after.sections == before.sections, role


def test_partially_seeded_role_stays_closed() -> None:
    rows = _action_rows(seeded=False)
    rows.append(
        SimpleNamespace(role="delivery_lead", action="delivery_view", access="manage")
    )
    access = _resolve(_user(UserRole.delivery_lead), action_rows=rows)

    assert access.permissions == {"delivery_view", "b2b_signature_confirmation"}
    assert access.sections[ProductSection.delivery] is SectionAccess.read


def test_legacy_section_override_only_restricts() -> None:
    lead = _user(UserRole.delivery_lead)
    capped = _resolve(
        lead,
        section_overrides=[
            SimpleNamespace(user_id=17, section="delivery", access="read")
        ],
    )
    assert capped.sections[ProductSection.delivery] is SectionAccess.read

    recruiter = _user(UserRole.recruiter)
    lifted = _resolve(
        recruiter,
        section_overrides=[
            SimpleNamespace(user_id=17, section="delivery", access="write"),
            SimpleNamespace(user_id=17, section="finance", access="write"),
        ],
    )
    assert lifted.sections[ProductSection.delivery] is SectionAccess.none
    assert lifted.sections[ProductSection.finance] is SectionAccess.none


def test_static_fallback_agrees_with_the_default_matrix() -> None:
    """Konto bez dołączonej polityki (zadania w tle, testy jednostkowe)."""

    finance = _user(UserRole.finance)
    assert has_permission(finance, ProductAction.contracts_orders_edit)
    assert not has_permission(finance, ProductAction.contract_status)
    assert section_access_for_user(finance, ProductSection.finance) is (
        SectionAccess.write
    )

    tac = _user(UserRole.tac)
    assert named_permissions_of(tac) == frozenset()
    assert section_access_for_user(tac, ProductSection.delivery) is SectionAccess.none


def test_request_snapshot_wins_over_the_static_matrix() -> None:
    recruiter = _user(UserRole.recruiter)
    recruiter.effective_action_access = {"clients_edit": "manage"}

    assert has_permission(recruiter, ProductAction.clients_edit)
    assert has_permission(recruiter, "clients_edit")
    assert not has_permission(recruiter, ProductAction.delivery_view)
