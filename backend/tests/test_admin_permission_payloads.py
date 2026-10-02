"""API panelu „Osoby i role”: kształt odpowiedzi liczony bez bazy.

Kontrakt: ``docs/permissions-nine-switches-contract.md`` §7. Ekran pokazuje
przełącznik jako włączony, zablokowany albo zmieniony wyłącznie na podstawie
tych pól, więc pilnujemy ich tu, a zapis i audyt w teście HTTP
(``test_admin_section_permissions.py``).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.admin_section_permissions import (
    RoleActionPermissionChange,
    UserActionPermissionChange,
    _account_grantable,
    _role_payload,
    _role_summary,
    _user_permission_payload,
    _user_summary,
)
from app.models.user import UserRole
from app.services import permission_catalog as catalog
from app.services.effective_access import granted_beyond_roles

# Zapisane sekcje jak na produkcji (02.10.2026): TCM ma Delivery „zapis”.
SECTIONS: dict[str, dict[str, str]] = {
    "finance": {
        "sourcing": "write",
        "pipeline": "write",
        "delivery": "write",
        "insights": "read",
        "finance": "write",
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
    "user": {"sourcing": "read", "pipeline": "read", "insights": "read"},
}
SIGNATORIES = {"delivery_lead", "talent_community_manager"}


def _user(*roles: UserRole, user_id: int = 17) -> SimpleNamespace:
    role_set = set(roles)
    return SimpleNamespace(
        id=user_id,
        name="Konto testowe",
        role=roles[0],
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


def _action_rows(*, unseeded: frozenset[str] = frozenset()) -> list[SimpleNamespace]:
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
        if role not in unseeded:
            rows.extend(
                SimpleNamespace(role=role, action=key, access=access)
                for key, access in catalog.seed_rows_for_role(role, sections).items()
            )
    return rows


def _grant(user_id: int, action: str, access: str = "manage") -> SimpleNamespace:
    return SimpleNamespace(user_id=user_id, action=action, access=access)


# ── Rola ─────────────────────────────────────────────────────────────────────


def test_finance_role_shows_granted_effective_and_what_forces_the_view() -> None:
    payload = _role_payload(
        UserRole.finance, _section_rows(), _action_rows(), users_count=3
    )

    assert payload["users_count"] == 3
    assert payload["grantable"] is True
    assert payload["locked"] is False
    named = payload["named"]
    assert list(named) == list(catalog.KEYS)
    # Decyzja 02.10.2026: Finanse zakładają kontrakty i zamówienia.
    assert named["contracts_orders_edit"] == {
        "granted": True,
        "effective": True,
        "implied_by": [],
    }
    # Podgląd jest włączony i zablokowany, dopóki cokolwiek go wymaga.
    assert named["delivery_view"]["granted"] is True
    assert named["delivery_view"]["effective"] is True
    assert named["delivery_view"]["implied_by"] == [
        "contracts_orders_edit",
        "amounts_view",
        "amounts_edit",
        "finance_module",
    ]
    assert named["clients_edit"] == {
        "granted": False,
        "effective": False,
        "implied_by": [],
    }
    # Sekcje Delivery i Finanse są WYLICZONE, nie przepisane z wierszy.
    assert payload["permissions"]["delivery"] == "write"
    assert payload["permissions"]["finance"] == "write"
    assert payload["permissions"]["system_admin"] == "none"
    assert payload["action_permissions"]["finance_module"] == "manage"
    assert payload["action_permissions"]["b2b_contract_generator"] == "manage"


def test_view_forced_by_an_edit_is_effective_but_not_granted() -> None:
    """Sam wiersz „edycja” wystarcza — ekran pokazuje podgląd jako wymuszony."""

    action_rows = [
        row
        for row in _action_rows()
        if not (row.role == "recruiter" and row.action == "clients_edit")
    ]
    action_rows.append(
        SimpleNamespace(role="recruiter", action="clients_edit", access="manage")
    )

    payload = _role_payload(UserRole.recruiter, _section_rows(), action_rows)

    assert payload["named"]["clients_edit"]["granted"] is True
    assert payload["named"]["delivery_view"] == {
        "granted": False,
        "effective": True,
        "implied_by": ["clients_edit"],
    }
    assert payload["permissions"]["delivery"] == "write"
    assert payload["action_permissions"]["delivery_view"] == "manage"


def test_role_without_seeded_rows_is_shown_through_the_seed_rule() -> None:
    """Baza sprzed zasiewu: ekran ma pokazać to samo, co policzy resolver."""

    payload = _role_payload(
        UserRole.talent_community_manager,
        _section_rows(),
        _action_rows(unseeded=frozenset({"talent_community_manager"})),
    )

    granted = [key for key, cell in payload["named"].items() if cell["granted"]]
    assert granted == [
        "delivery_view",
        "contract_status",
        "b2b_signature_confirmation",
    ]
    assert payload["permissions"]["delivery"] == "write"
    assert payload["permissions"]["finance"] == "none"


def test_admin_and_roles_that_cannot_be_granted() -> None:
    rows = (_section_rows(), _action_rows())

    admin = _role_payload(UserRole.admin, *rows)
    assert admin["locked"] is True
    assert admin["grantable"] is False
    assert all(cell["effective"] for cell in admin["named"].values())
    assert admin["permissions"]["system_admin"] == "write"

    for role in (UserRole.user, UserRole.trainee):
        payload = _role_payload(role, *rows)
        assert payload["grantable"] is False
        assert not any(cell["effective"] for cell in payload["named"].values())
        assert payload["permissions"]["delivery"] == "none"


# ── Osoba ────────────────────────────────────────────────────────────────────


def test_person_payload_separates_role_permissions_from_personal_grants() -> None:
    user = _user(UserRole.talent_community_manager, user_id=90)

    payload = _user_permission_payload(
        user,
        section_role_rows=_section_rows(),
        section_override_rows=[],
        action_role_rows=_action_rows(),
        action_override_rows=[_grant(90, "contracts_orders_edit")],
    )

    assert payload["user_id"] == 90
    assert payload["role"] == "talent_community_manager"
    assert payload["roles"] == ["talent_community_manager"]
    assert payload["locked"] is False
    assert payload["grantable"] is True
    assert payload["role_permissions"] == [
        "delivery_view",
        "contract_status",
        "b2b_signature_confirmation",
    ]
    assert payload["grants"] == ["contracts_orders_edit"]
    assert payload["restrictions"] == []
    assert payload["effective"] == [
        "delivery_view",
        "contracts_orders_edit",
        "contract_status",
        "b2b_signature_confirmation",
    ]
    assert payload["legacy_section_caps"] == {}


def test_person_payload_lists_legacy_restrictions_and_section_caps() -> None:
    user = _user(UserRole.delivery_lead, user_id=5)

    payload = _user_permission_payload(
        user,
        section_role_rows=_section_rows(),
        section_override_rows=[
            SimpleNamespace(user_id=5, section="delivery", access="read"),
            # Sekcja spoza wyliczanych nie jest „ograniczeniem Delivery”.
            SimpleNamespace(user_id=5, section="insights", access="none"),
        ],
        action_role_rows=_action_rows(),
        action_override_rows=[
            _grant(5, "b2b_signature_confirmation", "none"),
            # Poziom Generatora B2B nie jest jednym z dziewięciu uprawnień.
            _grant(5, "b2b_contract_generator", "view"),
        ],
    )

    assert payload["grants"] == []
    assert payload["restrictions"] == ["b2b_signature_confirmation"]
    assert "b2b_signature_confirmation" not in payload["effective"]
    assert payload["legacy_section_caps"] == {"delivery": "read"}


def test_admin_is_locked_and_legacy_viewer_cannot_be_granted() -> None:
    rows = {
        "section_role_rows": _section_rows(),
        "section_override_rows": [],
        "action_role_rows": _action_rows(),
        "action_override_rows": [],
    }

    admin = _user_permission_payload(_user(UserRole.admin), **rows)
    assert admin["locked"] is True
    assert admin["grantable"] is False
    assert admin["effective"] == list(catalog.KEYS)

    viewer = _user_permission_payload(_user(UserRole.user), **rows)
    assert viewer["locked"] is False
    assert viewer["grantable"] is False
    assert viewer["effective"] == []

    assert _account_grantable(_user(UserRole.recruiter)) is True
    assert _account_grantable(_user(UserRole.trainee)) is False


def test_badge_counts_only_what_the_person_was_ticked_beyond_the_roles() -> None:
    rows = {"section_role_rows": _section_rows(), "action_role_rows": _action_rows()}
    tcm = _user(UserRole.talent_community_manager, user_id=90)

    # Nadana edycja pociąga podgląd, ale plakietka liczy to, co zaznaczono.
    assert granted_beyond_roles(
        tcm, action_override_rows=[_grant(90, "contracts_orders_edit")], **rows
    ) == ("contracts_orders_edit",)
    # Rola już to daje — nadanie niczego nie dodaje.
    assert (
        granted_beyond_roles(
            tcm, action_override_rows=[_grant(90, "delivery_view")], **rows
        )
        == ()
    )
    # Cudze nadanie i stare ograniczenie nie są dodatkowym uprawnieniem.
    assert (
        granted_beyond_roles(
            tcm,
            action_override_rows=[
                _grant(91, "clients_edit"),
                _grant(90, "clients_edit", "none"),
            ],
            **rows,
        )
        == ()
    )
    # Kolejność katalogu, nie kolejność wierszy.
    assert granted_beyond_roles(
        _user(UserRole.recruiter, user_id=7),
        action_override_rows=[_grant(7, "amounts_view"), _grant(7, "clients_edit")],
        **rows,
    ) == ("clients_edit", "amounts_view")
    assert (
        granted_beyond_roles(
            _user(UserRole.admin, user_id=1),
            action_override_rows=[_grant(1, "clients_edit")],
            **rows,
        )
        == ()
    )


# ── Walidacja i opis w Historii zdarzeń ──────────────────────────────────────


@pytest.mark.parametrize("access", ["view", "generate"])
@pytest.mark.parametrize("action", list(catalog.KEYS))
def test_a_permission_is_yes_or_no_never_a_level(action: str, access: str) -> None:
    with pytest.raises(ValidationError) as role_error:
        RoleActionPermissionChange(role="recruiter", action=action, access=access)
    assert catalog.label(action) in str(role_error.value)
    with pytest.raises(ValidationError):
        UserActionPermissionChange(action=action, access=access)


def test_generator_keeps_its_levels() -> None:
    assert (
        RoleActionPermissionChange(
            role="recruiter", action="b2b_contract_generator", access="generate"
        ).access
        == "generate"
    )
    assert (
        UserActionPermissionChange(
            action="b2b_contract_generator", access="view"
        ).access
        == "view"
    )


def test_role_history_sentence_names_permissions_not_keys() -> None:
    sentence = _role_summary(
        {
            "contracts_orders_edit": {"from": "none", "to": "manage"},
            "finance_module": {"from": "manage", "to": "none"},
            "clients_edit": {"from": "missing", "to": "none"},
            "section:insights": {"from": "read", "to": "write"},
        }
    )

    assert sentence == (
        "Włączono: „Kontrakty i zamówienia: tworzenie i edycja”. "
        "Wyłączono: „Moduł Finanse”. "
        "Zapisano brakujący wpis bez zmiany dostępu: „Klienci: dodawanie i edycja”. "
        "Inne: section:insights: read → write."
    )


def test_person_history_sentence_tells_a_grant_from_a_lifted_restriction() -> None:
    sentence = _user_summary(
        {
            "contracts_orders_edit": {"from": "inherit", "to": "manage"},
            "clients_edit": {"from": "manage", "to": "inherit"},
            "b2b_signature_confirmation": {"from": "none", "to": "inherit"},
            "action:b2b_contract_generator": {"from": "inherit", "to": "view"},
        }
    )

    assert sentence == (
        "Nadano: „Kontrakty i zamówienia: tworzenie i edycja”. "
        "Zdjęto nadanie: „Klienci: dodawanie i edycja”. "
        "Usunięto ograniczenie: „Umowy B2B: oznaczanie jako podpisane”. "
        "Inne: action:b2b_contract_generator: inherit → view."
    )
