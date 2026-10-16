"""Jarvis i „Ludzie w NEXUSIE” — widoczność narzędzi i kształt wyniku (bez bazy).

* Narzędzie modułu HR trafia do modelu tylko przy module otwartym dla osoby
  (``hr_modules``) i z jednym z wymaganych uprawnień z ekranu — „Pracownik”
  widzi samoobsługę, recepcja sprzęt, Kadry sprzęt osoby, nikt bez „Sprzętu”
  nie dostaje wolnych egzemplarzy ani zadań recepcji.
* Wynik żadnego narzędzia HR nie niesie rodzaju nieobecności (D6, L4 to dane
  o zdrowiu), notatek, kwot płac, stawek ani wartości sprzętu — nawet gdy
  trasa je zwraca (krąg D6, własne wnioski, cennik).

Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import pytest

from app.models.user import User, UserRole
from app.services.action_permissions import named_permissions_of
from app.services.hr_foundation_schema import HR_MODULE_KEYS
from app.services.jarvis.tools import (
    HR_TOOLS,
    SCREENS,
    TOOLS_BY_NAME,
    build_screen_link,
    render_result,
    tools_for_user,
)
from app.services.section_permissions import ProductSection, section_access_for_user

ALL_MODULES = frozenset(HR_MODULE_KEYS)
HR_NAMES = {tool.name for tool in HR_TOOLS}
SELF_SERVICE = {
    "who_is_absent",
    "my_leave_balance",
    "my_leave_requests",
    "my_month",
    "my_equipment",
}


def _offered(sections=None, permissions=(), modules=ALL_MODULES) -> set[str]:
    sections = sections or {section: 0 for section in ProductSection}
    return {
        tool.name
        for tool in tools_for_user(
            sections, permissions=permissions, hr_modules=modules
        )
    }


def _persona(role: UserRole) -> tuple[dict, frozenset[str]]:
    """Sekcje i uprawnienia z domyślnej polityki roli (jak ``api/jarvis``)."""
    user = User(
        email="persona@example.com", name="Persona", role=role, roles=[role.value]
    )
    sections = {
        section: int(section_access_for_user(user, section))
        for section in ProductSection
    }
    return sections, named_permissions_of(user)


class TestVisibility:
    def test_employee_sees_only_self_service(self) -> None:
        sections, permissions = _persona(UserRole.employee)
        offered = _offered(sections, permissions)
        assert offered & HR_NAMES == SELF_SERVICE
        # „Pracownik” nie ma pracy rekrutacyjnej (D1).
        assert "search_candidates" not in offered

    def test_without_equipment_permission_no_register_or_reception(self) -> None:
        recruiter = _offered(permissions=())
        assert (
            not {
                "free_equipment",
                "reception_tasks",
                "person_equipment",
                "contract_equipment",
            }
            & recruiter
        )
        assert "my_equipment" in recruiter

        hr = _offered(permissions={"people_admin"})
        assert "person_equipment" in hr
        assert not {"free_equipment", "reception_tasks", "contract_equipment"} & hr

        delivery = _offered(permissions={"delivery_view"})
        assert "contract_equipment" in delivery
        assert not {"free_equipment", "reception_tasks", "person_equipment"} & delivery

    def test_reception_sees_the_register(self) -> None:
        reception = _offered(permissions={"equipment"})
        assert {
            "free_equipment",
            "reception_tasks",
            "person_equipment",
            "contract_equipment",
            "my_equipment",
        } <= reception

    def test_switched_off_module_hides_its_tools(self) -> None:
        offered = _offered(
            permissions={"equipment"}, modules=ALL_MODULES - {"equipment"}
        )
        assert not {name for name in offered if "equipment" in name}
        assert "who_is_absent" in offered
        no_leave = _offered(modules=ALL_MODULES - {"leave"})
        assert not {"who_is_absent", "my_leave_balance", "my_leave_requests"} & no_leave

    def test_unknown_module_state_hides_every_hr_tool(self) -> None:
        """Wywołanie bez stanu modułów (stary kod) nie podaje narzędzi HR."""
        none = {section: 2 for section in ProductSection}
        offered = {tool.name for tool in tools_for_user(none)}
        assert not offered & HR_NAMES
        assert "search_candidates" in offered and "open_screen" in offered

    def test_care_needs_delivery_section_permission_and_module(self) -> None:
        sections = {section: 0 for section in ProductSection}
        delivery = {**sections, ProductSection.delivery: 1}
        assert "my_care_consultants" in _offered(delivery, {"delivery_view"})
        assert "my_care_consultants" not in _offered(sections, {"delivery_view"})
        assert "my_care_consultants" not in _offered(delivery, ())
        assert "my_care_consultants" not in _offered(
            delivery, {"delivery_view"}, ALL_MODULES - {"care"}
        )

    def test_admin_sees_every_hr_tool(self) -> None:
        sections, permissions = _persona(UserRole.admin)
        assert HR_NAMES <= _offered(sections, permissions)


# ── Kształt wyniku ──────────────────────────────────────────────────────────

_SECRETS = (
    "sick_leave",
    "Zwolnienie lekarskie",
    "leave_type",
    "Wizyta u lekarza",
    "oof_",
    "paid_days",
    "4321",
    "price_pln",
    "unit_value",
    "TESTSN",
    "imei",
    "phone_number",
    "rate_",
    "salary",
    "childcare",
)

_CALENDAR = {
    "month": "2092-03",
    "people": [
        {
            "user_id": 5,
            "name": "Anna Przykładowa",
            "department": "Rekrutacja",
            "job_title": "Rekruterka",
            "type_visible": True,
            "absences": [
                {
                    "id": "req-1",
                    "start_date": "2092-03-03",
                    "end_date": "2092-03-05",
                    "half_day": None,
                    "status": "approved",
                    "label": "Zwolnienie lekarskie",
                    "leave_type": "sick_leave",
                    "substitute_name": "Jan Testowy",
                },
                {
                    "id": "req-2",
                    "start_date": "2092-03-20",
                    "end_date": "2092-03-21",
                    "status": "approved",
                    "label": "Urlop",
                    "leave_type": "vacation",
                },
            ],
        },
        {"user_id": 6, "name": "Ola Fikcyjna", "absences": []},
    ],
}

_SAMPLES = {
    "who_is_absent": (
        _CALENDAR,
        {"date_from": "2092-03-04", "date_to": "2092-03-06"},
    ),
    "my_leave_balance": (
        {
            "year": 2092,
            "entitlement_days": "26.0",
            "remaining_days": "20.0",
            "childcare_used": "1.0",
            "allowed_types": ["vacation", "sick_leave"],
        },
        {},
    ),
    "my_leave_requests": (
        {
            "items": [
                {
                    "id": "req-1",
                    "status": "approved",
                    "start_date": "2092-03-03",
                    "end_date": "2092-03-05",
                    "leave_type": "sick_leave",
                    "leave_type_label": "Zwolnienie lekarskie",
                    "note": "Wizyta u lekarza",
                    "decision_note": "Wizyta u lekarza",
                    "paid_days": "3.0",
                    "oof_internal_message": "Wracam w poniedziałek",
                    "days_total": "3.0",
                }
            ],
            "total": 1,
        },
        {},
    ),
    "my_month": (
        {
            "year": 2092,
            "month": 3,
            "deadline": "2092-04-05",
            "timesheet": {"status": "draft", "return_note": "Popraw piątek"},
            "days": [
                {
                    "date": "2092-03-03",
                    "working_day": True,
                    "leave": {"full": True, "label": "Zwolnienie lekarskie"},
                    "entries": [],
                    "attendance_note": "Wizyta u lekarza",
                }
            ],
            "totals": {"work_hours": 120.0, "days_missing": 2},
        },
        {},
    ),
    "free_equipment": (
        {
            "items": [
                {
                    "id": 9,
                    "category": "laptop",
                    "model": {"name": "Laptop 32 GB", "price_pln": "4321.00"},
                    "serial_number": "TESTSN01",
                    "imei": None,
                    "phone_number": "500100200",
                    "inventory_number": "L-001",
                    "notes": "Wizyta u lekarza",
                }
            ],
            "total": 1,
        },
        {"category": "laptop", "query": "32 GB"},
    ),
    "reception_tasks": (
        {
            "items": [
                {
                    "id": 3,
                    "kind": "zwrot",
                    "status": "otwarte",
                    "title": "Zwrot sprzętu",
                    "due_on": "2092-03-10",
                    "overdue_days": 0,
                    "holder": {"kind": "user", "id": 5, "name": "Anna Przykładowa"},
                    "protocol": {"id": 1, "number": "PZO/2092/03/001"},
                    "details": {"unit_value": "4321.00"},
                }
            ]
        },
        {},
    ),
    "my_care_consultants": (
        {
            "items": [
                {
                    "contract_id": 7,
                    "candidate_id": 8,
                    "candidate_name": "Jan Testowy",
                    "next_contact": {"due_on": "2092-03-10", "overdue": False},
                    "rate_client": "150.00",
                    "rate_candidate": "120.00",
                }
            ],
            "total": 1,
        },
        {},
    ),
}
_HOLDER = {
    "active": [
        {
            "assignment_id": 1,
            "item_id": 9,
            "category": "laptop",
            "model_name": "Laptop 32 GB",
            "inventory_number": "L-001",
            "serial_number": "TESTSN01",
            "imei": "350000000000000",
            "phone_number": "500100200",
            "unit_value": "4321.00",
            "return_notes": "Wizyta u lekarza",
        }
    ],
    "history": [],
    "protocols": [{"number": "PZO/2092/03/001", "kind": "wydanie"}],
}
for _name in ("my_equipment", "person_equipment", "contract_equipment"):
    _SAMPLES[_name] = (_HOLDER, {})


def test_every_hr_tool_has_a_shape_sample() -> None:
    assert set(_SAMPLES) == HR_NAMES


@pytest.mark.parametrize("name", sorted(_SAMPLES))
def test_shapes_drop_types_notes_amounts_and_identifiers(name: str) -> None:
    data, args = _SAMPLES[name]
    shaped = render_result(TOOLS_BY_NAME[name].shape(data, args))
    for secret in _SECRETS:
        assert secret not in shaped, (name, secret)


def test_absences_keep_who_and_when_within_the_range() -> None:
    data, args = _SAMPLES["who_is_absent"]
    shaped = TOOLS_BY_NAME["who_is_absent"].shape(data, args)
    assert shaped["total"] == 1
    person = shaped["absent"][0]
    assert person["name"] == "Anna Przykładowa"
    # Tylko okres zachodzący na zakres; zastępca zostaje.
    assert person["absences"] == [
        {
            "start_date": "2092-03-03",
            "end_date": "2092-03-05",
            "status": "approved",
            "substitute_name": "Jan Testowy",
        }
    ]


def test_absence_range_is_clipped_to_one_month() -> None:
    tool = TOOLS_BY_NAME["who_is_absent"]
    args = {"date_from": "2092-03-30", "date_to": "2092-04-10"}
    assert tool.build(args).params == {"month": "2092-03"}
    shaped = tool.shape({"people": []}, args)
    assert shaped["to"] == "2092-03-31"
    assert "przycięty" in shaped["note"]
    with pytest.raises(ValueError):
        tool.build({"date_from": "2092-03-10", "date_to": "2092-03-01"})
    with pytest.raises(ValueError):
        tool.build({"date_from": "jutro"})


def test_my_month_lists_missing_days_and_return_note() -> None:
    shaped = TOOLS_BY_NAME["my_month"].shape(
        {
            "year": 2020,
            "month": 1,
            "timesheet": None,
            "days": [
                {"date": "2020-01-02", "working_day": True, "entries": []},
                {"date": "2020-01-03", "working_day": True, "entries": [{"id": 1}]},
                {"date": "2020-01-04", "working_day": False, "entries": []},
            ],
            "totals": {"days_missing": 1},
        },
        {},
    )
    assert shaped["missing_days_until_today"] == ["2020-01-02"]
    assert shaped["timesheet"] == {"status": "nierozpoczęty"}
    returned = TOOLS_BY_NAME["my_month"].shape(*_SAMPLES["my_month"])
    assert returned["timesheet"]["return_note"] == "Popraw piątek"


def test_free_equipment_filters_go_to_the_register() -> None:
    spec = TOOLS_BY_NAME["free_equipment"].build(
        {"category": "laptop", "query": "32 GB"}
    )
    assert spec.path == "/api/equipment/items"
    assert spec.params == {
        "free": True,
        "category": "laptop",
        "q": "32 GB",
        "limit": 10,
    }


@pytest.mark.parametrize(
    "screen,href",
    [
        ("my_time", "/my-time"),
        ("people", "/people"),
        ("people_approvals", "/people/approvals"),
        ("equipment", "/equipment"),
        ("care", "/care"),
    ],
)
def test_hr_screens_open_without_record_id(screen: str, href: str) -> None:
    assert screen in SCREENS
    assert build_screen_link({"screen": screen, "reason": "x"})["href"] == href
