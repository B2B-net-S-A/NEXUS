"""Nieobecności i sprzęt w API v1: zdarzenia ``leave.*`` / ``equipment.*``
i trasy ``/absences``, ``/equipment/assignments/{id}`` („Ludzie w NEXUSIE”).

Dwie warstwy:

* bez bazy — katalog zdarzeń i zakresów, budowa zdarzeń z obiektów flusha:
  rodzaj nieobecności (decyzja D6) nie trafia do ``refs``, choć ślad HR go
  niesie; wydanie z importu (bez protokołu) zdarzenia nie daje;
* Postgres — zdarzenia z prawdziwych ścieżek ekranów (akceptacja, wpis za
  pracownika, anulowanie, wydanie i zwrot sprzętu) i trasy v1: zakres klucza
  (403), wyłączony moduł (404), zakres dat (422), brak rodzaju i numerów
  seryjnych w odpowiedzi.

Dane fikcyjne (repo jest publiczne); daty w 2092, żeby nie zderzać się
z „dziś” ani z innymi testami urlopów.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm.attributes import set_committed_value

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.equipment import EquipmentAssignment
from app.models.hr_ops import HrAuditEvent
from app.models.hr_profile import EmployeeProfile, LeaveEntitlement
from app.models.integration_event import IntegrationEvent, IntegrationEventOutbox
from app.models.service_account import SCOPE_LABELS, ServiceScope
from app.models.user import User, UserRole
from app.services import integration_events as ie
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING
from tests.test_equipment_api import _item, _model, make_people
from tests.test_service_accounts import _account_with_key

V1 = "/api/integrations/v1"
LEAVE = "/api/hr/leave"
MON = date(2092, 3, 3)  # poniedziałek
FRI = MON + timedelta(days=4)
TYPES_IN_REFS = ("leave_type", "sick_leave", "vacation", "occasional", "label")


# ═════════════════════════════════════════════════════════════════════════════
# Bez bazy
# ═════════════════════════════════════════════════════════════════════════════


class TestCatalog:
    def test_hr_events_need_their_own_scopes(self) -> None:
        assert set(ie.visible_types({"absences:read"})) == {
            "leave.approved",
            "leave.cancelled",
        }
        assert set(ie.visible_types({"equipment:read"})) == {
            "equipment.issued",
            "equipment.returned",
        }
        # Kadrowe zdarzenia nie wyciekają do kluczy innych obszarów.
        assert not {"leave.approved", "equipment.issued"} & set(
            ie.visible_types({"events:read", "contracts:read", "candidates:read"})
        )

    def test_scopes_have_labels_and_absences_has_no_type_scope(self) -> None:
        assert SCOPE_LABELS[ServiceScope.absences_read] == (
            "Nieobecności — kto i kiedy, bez rodzaju"
        )
        assert SCOPE_LABELS[ServiceScope.equipment_read] == "Sprzęt — wydania i zwroty"
        values = {scope.value for scope in ServiceScope}
        # D6: rodzaju nieobecności nie da się nadać kluczowi żadnym scope'em.
        assert {v for v in values if v.startswith("absences:")} == {"absences:read"}
        assert {v for v in values if v.startswith("equipment:")} == {"equipment:read"}


def _audit(action: str, **details) -> HrAuditEvent:
    return HrAuditEvent(
        id=7,
        actor_user_id=3,
        subject_user_id=11,
        entity_type="leave_request",
        entity_id="9b2f4c1e-0000-4000-8000-000000000001",
        action=action,
        details={
            "leave_type": "sick_leave",
            "start_date": "2092-03-03",
            "end_date": "2092-03-07",
            "has_note": True,
            **details,
        },
        sensitivity="health",
    )


class TestLeaveEventsFromAudit:
    @pytest.mark.parametrize(
        "action", ["leave_approved", "absence_reported", "leave_entered_on_behalf"]
    )
    def test_approval_paths_give_leave_approved_without_the_type(
        self, action: str
    ) -> None:
        rows = ie.collect_flush_events([_audit(action, status="approved")], [])
        assert [row["type"] for row in rows] == ["leave.approved"]
        assert rows[0]["scope"] == "absences:read"
        assert rows[0]["refs"] == {
            "leave_request_id": "9b2f4c1e-0000-4000-8000-000000000001",
            "user_id": 11,
            "start_date": "2092-03-03",
            "end_date": "2092-03-07",
        }
        dumped = json.dumps(rows)
        for forbidden in TYPES_IN_REFS + ("has_note",):
            assert forbidden not in dumped

    def test_cancel_of_approved_gives_leave_cancelled(self) -> None:
        rows = ie.collect_flush_events(
            [_audit("leave_cancelled", status="cancelled", previous_status="approved")],
            [],
        )
        assert [row["type"] for row in rows] == ["leave.cancelled"]
        assert "sick_leave" not in json.dumps(rows)

    @pytest.mark.parametrize(
        "action,details",
        [
            ("leave_requested", {"status": "pending"}),
            ("leave_rejected", {"status": "rejected"}),
            # Oczekujący wniosek nie był nieobecnością — jego anulowanie też nie.
            (
                "leave_cancelled",
                {"status": "cancelled", "previous_status": "pending"},
            ),
            ("m365_forward_opened", {"operation_id": 5}),
        ],
    )
    def test_other_leave_audits_give_nothing(self, action: str, details: dict) -> None:
        assert ie.collect_flush_events([_audit(action, **details)], []) == []

    def test_audit_of_other_entities_gives_nothing(self) -> None:
        other = _audit("leave_approved", status="approved")
        other.entity_type = "payroll_bonus"
        assert ie.collect_flush_events([other], []) == []


def _assignment(**values) -> EquipmentAssignment:
    return EquipmentAssignment(id=21, item_id=31, **values)


class TestEquipmentEvents:
    @pytest.mark.parametrize(
        "column,kind",
        [
            ("user_id", "user"),
            ("contract_id", "contract"),
            ("external_person_id", "external"),
            ("academy_application_id", "academy_application"),
        ],
    )
    def test_issue_with_protocol_names_the_holder(self, column: str, kind: str) -> None:
        rows = ie.collect_flush_events(
            [_assignment(issue_protocol_id=41, **{column: 51})], []
        )
        assert rows == [
            {
                "type": "equipment.issued",
                "scope": "equipment:read",
                "refs": {
                    "assignment_id": 21,
                    "item_id": 31,
                    "holder_kind": kind,
                    "holder_id": 51,
                },
            }
        ]

    def test_import_without_protocol_is_initial_state_not_an_event(self) -> None:
        assert ie.collect_flush_events([_assignment(user_id=51)], []) == []

    def test_setting_returned_at_gives_equipment_returned(self) -> None:
        row = _assignment(user_id=51, issue_protocol_id=41)
        set_committed_value(row, "returned_at", None)
        row.returned_at = datetime(2092, 3, 4, 10, tzinfo=timezone.utc)
        rows = ie.collect_flush_events([], [row])
        assert [r["type"] for r in rows] == ["equipment.returned"]
        assert rows[0]["refs"]["holder_kind"] == "user"

    def test_correcting_return_date_is_not_a_second_return(self) -> None:
        row = _assignment(user_id=51)
        set_committed_value(
            row, "returned_at", datetime(2092, 3, 4, tzinfo=timezone.utc)
        )
        row.returned_at = datetime(2092, 3, 5, tzinfo=timezone.utc)
        assert ie.collect_flush_events([], [row]) == []


# ═════════════════════════════════════════════════════════════════════════════
# Postgres
# ═════════════════════════════════════════════════════════════════════════════


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _set_modules(value: dict) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value=value))
        else:
            row.value = value
        await db.commit()


@pytest_asyncio.fixture
async def modules_on():
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _set_modules({key: True for key in HR_MODULE_KEYS})
    yield
    await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


async def _switch(**changes: bool) -> None:
    await _set_modules({**{key: True for key in HR_MODULE_KEYS}, **changes})


async def _person(db, role: str, **profile) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"events-{marker}@example.com",
        name=f"Osoba Przykładowa {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(EmployeeProfile(user_id=user.id, **profile))
    await db.flush()
    return user


async def _team() -> tuple[User, User]:
    async with AsyncSessionLocal() as db:
        boss = await _person(db, "recruiter")
        worker = await _person(
            db, "employee", employment_type="uop", manager_user_id=boss.id
        )
        db.add(
            LeaveEntitlement(
                user_id=worker.id, year=MON.year, entitlement_days=Decimal("26")
            )
        )
        await db.commit()
    return boss, worker


async def _events(key: str, value) -> list[tuple[str, dict]]:
    """Zdarzenia z poczekalni i z kanału (pętla publikacji mogła je przenieść)."""
    found: list[tuple[str, dict]] = []
    async with AsyncSessionLocal() as db:
        for model in (IntegrationEventOutbox, IntegrationEvent):
            rows = await db.execute(
                select(model.type, model.refs).where(
                    model.refs[key].astext == str(value)
                )
            )
            found.extend((kind, dict(refs)) for kind, refs in rows.all())
    return found


def _body(leave_type: str, start: date, end: date, **extra) -> dict:
    return {
        "leave_type": leave_type,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        **extra,
    }


async def _key(app_client: AsyncClient, headers: dict, scopes: list[str]) -> dict:
    _, api_key, _ = await _account_with_key(app_client, headers, scopes)
    return {"X-API-Key": api_key}


async def test_leave_decisions_publish_events_and_v1_reads_them(
    app_client: AsyncClient, app_auth_headers: dict, modules_on
) -> None:
    boss, worker = await _team()
    created = await app_client.post(
        LEAVE + "/requests",
        json=_body("vacation", MON, FRI, note="Wyjazd rodzinny"),
        headers=_headers(worker),
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["id"]
    # Oczekujący wniosek nie jest nieobecnością — ani zdarzenia, ani odczytu.
    assert await _events("leave_request_id", request_id) == []
    absences = await _key(app_client, app_auth_headers, ["absences:read"])
    pending = await app_client.get(f"{V1}/absences/{request_id}", headers=absences)
    assert pending.status_code == 404, pending.text

    approved = await app_client.post(
        f"{LEAVE}/approvals/{request_id}/approve", headers=_headers(boss)
    )
    assert approved.status_code == 200, approved.text
    events = await _events("leave_request_id", request_id)
    assert events == [
        (
            "leave.approved",
            {
                "leave_request_id": request_id,
                "user_id": worker.id,
                "start_date": MON.isoformat(),
                "end_date": FRI.isoformat(),
            },
        )
    ]

    listing = await app_client.get(
        f"{V1}/absences",
        params={"from": MON.isoformat(), "to": FRI.isoformat(), "page_size": 500},
        headers=absences,
    )
    assert listing.status_code == 200, listing.text
    row = next(i for i in listing.json()["items"] if i["user_id"] == worker.id)
    assert row["name"] == worker.name
    assert row["days_total"] == 5.0
    assert [d["date"] for d in row["days"]] == [
        (MON + timedelta(days=n)).isoformat() for n in range(5)
    ]
    assert {d["request_id"] for d in row["days"]} == {request_id}
    # Węższy zakres — tylko dni, które na niego zachodzą.
    narrow = await app_client.get(
        f"{V1}/absences",
        params={"from": FRI.isoformat(), "to": FRI.isoformat(), "page_size": 500},
        headers=absences,
    )
    row = next(i for i in narrow.json()["items"] if i["user_id"] == worker.id)
    assert row["days_total"] == 1.0

    detail = await app_client.get(f"{V1}/absences/{request_id}", headers=absences)
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "approved"
    assert detail.json()["days_total"] == 5.0
    for body in (listing.text, detail.text):
        for forbidden in TYPES_IN_REFS + ("Wyjazd", "note"):
            assert forbidden not in body

    cancelled = await app_client.post(
        f"{LEAVE}/requests/{request_id}/cancel", headers=_headers(worker)
    )
    assert cancelled.status_code == 200, cancelled.text
    kinds = [kind for kind, _ in await _events("leave_request_id", request_id)]
    assert sorted(kinds) == ["leave.approved", "leave.cancelled"]
    after = await app_client.get(f"{V1}/absences/{request_id}", headers=absences)
    assert after.status_code == 200
    assert after.json()["status"] == "cancelled"
    gone = await app_client.get(
        f"{V1}/absences",
        params={"from": MON.isoformat(), "to": FRI.isoformat(), "page_size": 500},
        headers=absences,
    )
    assert worker.id not in {i["user_id"] for i in gone.json()["items"]}


async def test_on_behalf_entry_and_pending_cancel(
    app_client: AsyncClient, modules_on
) -> None:
    boss, worker = await _team()
    week = MON + timedelta(days=7)
    entered = await app_client.post(
        LEAVE + "/approvals/on-behalf",
        json={
            **_body("occasional", week, week + timedelta(days=1)),
            "user_id": worker.id,
        },
        headers=_headers(boss),
    )
    assert entered.status_code == 201, entered.text
    events = await _events("leave_request_id", entered.json()["id"])
    assert [kind for kind, _ in events] == ["leave.approved"]
    assert "occasional" not in json.dumps(events)

    later = MON + timedelta(days=14)
    pending = await app_client.post(
        LEAVE + "/requests",
        json=_body("vacation", later, later),
        headers=_headers(worker),
    )
    assert pending.status_code == 201, pending.text
    withdrawn = await app_client.post(
        f"{LEAVE}/requests/{pending.json()['id']}/cancel", headers=_headers(worker)
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert await _events("leave_request_id", pending.json()["id"]) == []


async def test_absences_refuse_wrong_scope_bad_range_and_disabled_module(
    app_client: AsyncClient, app_auth_headers: dict, modules_on
) -> None:
    week = {"from": MON.isoformat(), "to": FRI.isoformat()}
    other = await _key(app_client, app_auth_headers, ["equipment:read"])
    refused = await app_client.get(f"{V1}/absences", params=week, headers=other)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["code"] == "insufficient_scope"
    # JWT administratora nie otwiera tras v1.
    admin = await app_client.get(
        f"{V1}/absences", params=week, headers=app_auth_headers
    )
    assert admin.status_code == 401

    key = await _key(app_client, app_auth_headers, ["absences:read"])
    too_long = await app_client.get(
        f"{V1}/absences",
        params={"from": MON.isoformat(), "to": (MON + timedelta(days=93)).isoformat()},
        headers=key,
    )
    assert too_long.status_code == 422, too_long.text
    assert too_long.json()["error"]["code"] == "invalid_period"
    quarter = await app_client.get(
        f"{V1}/absences",
        params={"from": MON.isoformat(), "to": (MON + timedelta(days=92)).isoformat()},
        headers=key,
    )
    assert quarter.status_code == 200, quarter.text
    backwards = await app_client.get(
        f"{V1}/absences",
        params={"from": FRI.isoformat(), "to": MON.isoformat()},
        headers=key,
    )
    assert backwards.status_code == 422
    missing = await app_client.get(f"{V1}/absences", headers=key)
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "validation_error"
    unknown = await app_client.get(f"{V1}/absences/{uuid.uuid4()}", headers=key)
    assert unknown.status_code == 404

    await _switch(leave=False)
    for path in ("/absences", f"/absences/{uuid.uuid4()}"):
        off = await app_client.get(f"{V1}{path}", params=week, headers=key)
        assert off.status_code == 404, path
        assert off.json()["error"]["code"] == "module_disabled"


async def test_equipment_issue_and_return_publish_events_and_v1_reads_them(
    app_client: AsyncClient, app_auth_headers: dict, modules_on
) -> None:
    people = await make_people()
    reception = _headers(people["reception"])
    worker = people["worker"]
    model = await _model(app_client, reception, "laptop", "4321.00")
    laptop = await _item(
        app_client,
        reception,
        model["id"],
        inventory_number=f"EV-{uuid.uuid4().hex[:6]}",
        serial_number=f"TESTSN{uuid.uuid4().hex[:8]}",
    )
    issued = await app_client.post(
        "/api/equipment/issue",
        json={
            "holder_kind": "user",
            "holder_id": worker.id,
            "lines": [{"item_id": laptop["id"]}],
        },
        headers=reception,
    )
    assert issued.status_code == 201, issued.text
    async with AsyncSessionLocal() as db:
        assignment_id = await db.scalar(
            select(EquipmentAssignment.id).where(
                EquipmentAssignment.item_id == laptop["id"]
            )
        )
    assert await _events("assignment_id", assignment_id) == [
        (
            "equipment.issued",
            {
                "assignment_id": assignment_id,
                "item_id": laptop["id"],
                "holder_kind": "user",
                "holder_id": worker.id,
            },
        )
    ]

    key = await _key(app_client, app_auth_headers, ["equipment:read"])
    read = await app_client.get(
        f"{V1}/equipment/assignments/{assignment_id}", headers=key
    )
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["item"]["category"] == "laptop"
    assert body["item"]["model"] == model["name"]
    assert body["item"]["inventory_number"] == laptop["inventory_number"]
    assert body["holder"] == {"kind": "user", "id": worker.id, "name": worker.name}
    assert body["returned_at"] is None
    # Bez wartości z cennika i bez numerów seryjnych.
    assert "4321" not in read.text
    assert laptop["serial_number"] not in read.text
    for field in ("serial_number", "imei", "iccid", "price_pln", "unit_value"):
        assert field not in read.text

    returned = await app_client.post(
        "/api/equipment/return",
        json={"lines": [{"assignment_id": assignment_id, "condition": "sprawny"}]},
        headers=reception,
    )
    assert returned.status_code == 201, returned.text
    kinds = sorted(kind for kind, _ in await _events("assignment_id", assignment_id))
    assert kinds == ["equipment.issued", "equipment.returned"]
    after = await app_client.get(
        f"{V1}/equipment/assignments/{assignment_id}", headers=key
    )
    assert after.json()["returned_at"] is not None
    assert after.json()["return_condition"] == "sprawny"

    absences_only = await _key(app_client, app_auth_headers, ["absences:read"])
    refused = await app_client.get(
        f"{V1}/equipment/assignments/{assignment_id}", headers=absences_only
    )
    assert refused.status_code == 403
    missing = await app_client.get(
        f"{V1}/equipment/assignments/2147483000", headers=key
    )
    assert missing.status_code == 404
    await _switch(equipment=False)
    off = await app_client.get(
        f"{V1}/equipment/assignments/{assignment_id}", headers=key
    )
    assert off.status_code == 404
    assert off.json()["error"]["code"] == "module_disabled"
