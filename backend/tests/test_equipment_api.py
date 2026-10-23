"""Sprzęt i protokoły (S1–S3): uprawnienia, rejestr, wydanie i zwrot, zadania.

Recepcja = konto z uprawnieniem „Sprzęt”; Kadry widzą tylko sprzęt osoby;
rekruter nic. Dane fikcyjne (repo jest publiczne): osoby „Przykładowe”,
numery „TEST…”, kwoty zmyślone.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.equipment import (
    EquipmentAssignment,
    EquipmentItem,
    EquipmentModel,
    EquipmentTask,
)
from app.models.hr_ops import HrJobRun
from app.models.notification import Notification, NotificationType
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services.equipment import tasks as equipment_tasks
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


def _tag() -> str:
    return uuid.uuid4().hex[:8].upper()


async def _user(
    db, role: str = "recruiter", *, grants: tuple[str, ...] = (), name=None
) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"eq-{marker}@example.com",
        name=name or f"Osoba {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    for action in grants:
        db.add(UserActionOverride(user_id=user.id, action=action, access="manage"))
    await db.flush()
    return user


async def _set_modules(value: dict) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value=value))
        else:
            row.value = value
        await db.commit()


async def _modules(value: dict):
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _set_modules(value)
    return previous


@asynccontextmanager
async def modules_state(on: bool):
    """Przełączniki modułów na czas testu (stan sprzed testu wraca)."""
    previous = await _modules({key: on for key in HR_MODULE_KEYS})
    try:
        yield
    finally:
        await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


@pytest_asyncio.fixture
async def modules_on():
    async with modules_state(True):
        yield


@pytest_asyncio.fixture
async def modules_off():
    async with modules_state(False):
        yield


async def make_people() -> dict[str, User]:
    """Recepcja, Kadry, rekruter, podgląd Delivery, pracownik i admin."""
    async with AsyncSessionLocal() as db:
        out = {
            "reception": await _user(db, grants=("equipment",)),
            "hr": await _user(db, grants=("people_admin",)),
            "recruiter": await _user(db),
            "delivery": await _user(db, grants=("delivery_view",)),
            "worker": await _user(db, "employee", name="Anna Przykładowa " + _tag()),
            "admin": await _user(db, "admin"),
        }
        await db.commit()
    return out


@pytest_asyncio.fixture
async def people():
    return await make_people()


async def _contract(
    *, start: date, end: date | None, provider: str = "nieznany"
) -> dict:
    token = _tag()
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Jan", lastname=f"Testowy-{token}", email=f"eqc-{token}@example.com"
        )
        client = Client(name=f"Klient Fikcyjny {token}")
        db.add_all([candidate, client])
        await db.flush()
        await db.execute(
            text("UPDATE clients SET equipment_provider = :p WHERE id = :id"),
            {"p": provider, "id": client.id},
        )
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            status=ContractStatus.active,
            contract_type=ContractType("b2b"),
            start_date=start,
            end_date=end,
            rate_client=100,
            rate_candidate=80,
            margin=20,
            currency="PLN",
        )
        db.add(contract)
        await db.commit()
        return {"id": contract.id, "client_id": client.id, "candidate_id": candidate.id}


async def _drop_contract(ids: dict) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Contract).where(Contract.id == ids["id"]))
        await db.execute(delete(Candidate).where(Candidate.id == ids["candidate_id"]))
        await db.execute(delete(Client).where(Client.id == ids["client_id"]))
        await db.commit()


async def _model(app_client, headers, category="laptop", price="2589.00") -> dict:
    response = await app_client.post(
        "/api/equipment/models",
        json={"category": category, "name": f"Model {_tag()}", "price_pln": price},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _item(app_client, headers, model_id: int, **fields) -> dict:
    payload = {"model_id": model_id, **fields}
    if not any(
        k in fields
        for k in ("serial_number", "phone_number", "imei", "inventory_number")
    ):
        payload["serial_number"] = f"TEST{_tag()}"
    response = await app_client.post(
        "/api/equipment/items", json=payload, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


# ── Moduł i uprawnienia ───────────────────────────────────────────────────────


async def test_switched_off_module_answers_404_except_admin(
    app_client, modules_off, people
) -> None:
    refused = await app_client.get(
        "/api/equipment/items", headers=_headers(people["reception"])
    )
    assert refused.status_code == 404
    assert refused.json()["detail"] == "Ten moduł nie jest jeszcze włączony."
    mine = await app_client.get("/api/equipment/me", headers=_headers(people["worker"]))
    assert mine.status_code == 404
    admin = await app_client.get(
        "/api/equipment/items", headers=_headers(people["admin"])
    )
    assert admin.status_code == 200


async def test_reception_manages_hr_reads_person_recruiter_nothing(
    app_client, modules_on, people
) -> None:
    worker = people["worker"]
    assert (
        await app_client.get(
            "/api/equipment/items", headers=_headers(people["reception"])
        )
    ).status_code == 200
    for who in ("hr", "recruiter", "delivery", "worker"):
        response = await app_client.get(
            "/api/equipment/items", headers=_headers(people[who])
        )
        assert response.status_code == 403, who
    hr_read = await app_client.get(
        f"/api/equipment/people/{worker.id}", headers=_headers(people["hr"])
    )
    assert hr_read.status_code == 200
    assert set(hr_read.json()) >= {"active", "history", "protocols"}
    hr_issue = await app_client.post(
        "/api/equipment/issue",
        json={"holder_kind": "user", "holder_id": worker.id, "lines": [{"item_id": 1}]},
        headers=_headers(people["hr"]),
    )
    assert hr_issue.status_code == 403
    assert (
        await app_client.get(
            f"/api/equipment/people/{worker.id}", headers=_headers(people["recruiter"])
        )
    ).status_code == 403
    own = await app_client.get(
        f"/api/equipment/people/{worker.id}", headers=_headers(worker)
    )
    assert own.status_code == 200
    assert (
        await app_client.get("/api/equipment/me", headers=_headers(worker))
    ).status_code == 200


# ── Rejestr ───────────────────────────────────────────────────────────────────


async def test_identifiers_are_unique_only_when_present(
    app_client, modules_on, people
) -> None:
    headers = _headers(people["reception"])
    model = await _model(app_client, headers)
    serial = f"TEST{_tag()}"
    await _item(app_client, headers, model["id"], serial_number=serial)
    duplicate = await app_client.post(
        "/api/equipment/items",
        json={"model_id": model["id"], "serial_number": f"  {serial.lower()} "},
        headers=headers,
    )
    assert duplicate.status_code == 409
    assert "jest już w rejestrze" in duplicate.json()["detail"]
    # Dwa egzemplarze bez S/N (różne numery ewidencyjne) — puste nie kolidują.
    for _ in range(2):
        await _item(app_client, headers, model["id"], inventory_number=f"T-{_tag()}")

    bad_imei = await app_client.post(
        "/api/equipment/items",
        json={"model_id": model["id"], "imei": "123"},
        headers=headers,
    )
    assert bad_imei.status_code == 422
    secret = await app_client.post(
        "/api/equipment/items",
        json={
            "model_id": model["id"],
            "serial_number": "111111-222222-333333-444444-555555-666666-777777-888888",
        },
        headers=headers,
    )
    assert secret.status_code == 422
    private = await app_client.post(
        "/api/equipment/items",
        json={
            "model_id": model["id"],
            "serial_number": f"TEST{_tag()}",
            "notes": "kontakt anna.przykladowa@gmail.com",
        },
        headers=headers,
    )
    assert private.status_code == 422
    issued = await app_client.post(
        "/api/equipment/items",
        json={
            "model_id": model["id"],
            "serial_number": f"TEST{_tag()}",
            "status": "wydany",
        },
        headers=headers,
    )
    assert issued.status_code == 422
    nothing = await app_client.post(
        "/api/equipment/items", json={"model_id": model["id"]}, headers=headers
    )
    assert nothing.status_code == 422


async def test_database_keeps_one_active_holder_and_exactly_one_holder(
    app_client, modules_on, people
) -> None:
    async with AsyncSessionLocal() as db:
        model = EquipmentModel(category="monitor", name=f"Monitor {_tag()}")
        db.add(model)
        await db.flush()
        item = EquipmentItem(model_id=model.id, serial_number=f"TEST{_tag()}")
        db.add(item)
        await db.flush()
        db.add(EquipmentAssignment(item_id=item.id, user_id=people["worker"].id))
        await db.flush()
        db.add(EquipmentAssignment(item_id=item.id, user_id=people["hr"].id))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()
    for holders in ({}, {"user_id": "worker", "external_person_id": "hr"}):
        async with AsyncSessionLocal() as db:
            model = EquipmentModel(category="monitor", name=f"Monitor {_tag()}")
            db.add(model)
            await db.flush()
            item = EquipmentItem(model_id=model.id, serial_number=f"TEST{_tag()}")
            db.add(item)
            await db.flush()
            values = {"item": item.id, "user": people["worker"].id}
            sql = "INSERT INTO equipment_assignments (item_id) VALUES (:item)"
            if holders:
                # Konto i osoba spoza naraz: id osoby spoza nie musi istnieć —
                # CHECK jednego posiadacza pada wcześniej niż klucz obcy.
                sql = (
                    "INSERT INTO equipment_assignments "
                    "(item_id, user_id, external_person_id) VALUES (:item, :user, -1)"
                )
            with pytest.raises(IntegrityError):
                await db.execute(text(sql), values)
            await db.rollback()


# ── Wydanie i zwrot ───────────────────────────────────────────────────────────


async def test_issue_and_return_with_protocols(app_client, modules_on, people) -> None:
    headers = _headers(people["reception"])
    worker = people["worker"]
    async with AsyncSessionLocal() as db:
        start_task = await equipment_tasks.tasks_for_person_start(
            db, worker.id, business_today()
        )
        await db.commit()
    laptop_model = await _model(app_client, headers, "laptop", "2589.00")
    sim_model = await _model(app_client, headers, "karta_sim", "50.00")
    assert sim_model["price_pln"] is None  # D6: SIM bez wartości
    laptop = await _item(
        app_client, headers, laptop_model["id"], inventory_number=f"L-{_tag()}"
    )
    phone_digits = str(500_000_000 + int(uuid.uuid4().int % 99_999_999))
    sim = await _item(app_client, headers, sim_model["id"], phone_number=phone_digits)

    issued = await app_client.post(
        "/api/equipment/issue",
        json={
            "holder_kind": "user",
            "holder_id": worker.id,
            "lines": [
                {"item_id": laptop["id"], "accessories": "zasilacz, mysz"},
                {"item_id": sim["id"], "unit_value": "99.00"},
            ],
        },
        headers=headers,
    )
    assert issued.status_code == 201, issued.text
    protocol = issued.json()["protocol"]
    today = business_today()
    assert protocol["number"].startswith(f"PZO/{today.year}/{today.month:02d}/")
    assert protocol["kind"] == "wydanie"
    assert protocol["status"] == "oczekuje"
    assert protocol["total_value"] == "2589.00"
    assert protocol["lines"][0]["name"].endswith("zasilacz, mysz")
    assert protocol["lines"][1]["unit_value"] is None
    assert protocol["lines"][1]["name"].startswith("Karta SIM +48 ")

    detail = await app_client.get(
        f"/api/equipment/items/{laptop['id']}", headers=headers
    )
    assert detail.json()["status"] == "wydany"
    assert detail.json()["holder"]["id"] == worker.id

    again = await app_client.post(
        "/api/equipment/issue",
        json={
            "holder_kind": "user",
            "holder_id": people["hr"].id,
            "lines": [{"item_id": laptop["id"]}],
        },
        headers=headers,
    )
    assert again.status_code == 409
    dup = await app_client.post(
        "/api/equipment/issue",
        json={
            "holder_kind": "user",
            "holder_id": worker.id,
            "lines": [{"item_id": laptop["id"]}, {"item_id": laptop["id"]}],
        },
        headers=headers,
    )
    assert dup.status_code == 422

    async with AsyncSessionLocal() as db:
        task = await db.get(EquipmentTask, start_task.id)
        assert task.status == "zrobione"  # wydanie odhacza „Zestaw biura”

    mine = await app_client.get("/api/equipment/me", headers=_headers(worker))
    active = mine.json()["active"]
    assert {row["item_id"] for row in active} == {laptop["id"], sim["id"]}

    returned = await app_client.post(
        "/api/equipment/return",
        json={
            "lines": [
                {
                    "assignment_id": row["assignment_id"],
                    "condition": cond,
                    "notes": note,
                }
                for row, (cond, note) in zip(
                    sorted(active, key=lambda r: r["item_id"] != laptop["id"]),
                    [("sprawny", None), ("zgubiony", "zgłoszone")],
                )
            ]
        },
        headers=headers,
    )
    assert returned.status_code == 201, returned.text
    back = returned.json()["protocol"]
    assert back["kind"] == "zwrot"
    assert back["number"] != protocol["number"]
    statuses = {
        item_id: (
            await app_client.get(f"/api/equipment/items/{item_id}", headers=headers)
        ).json()["status"]
        for item_id in (laptop["id"], sim["id"])
    }
    assert statuses == {laptop["id"]: "na_stanie", sim["id"]: "zgubiony"}
    twice = await app_client.post(
        "/api/equipment/return",
        json={
            "lines": [
                {"assignment_id": active[0]["assignment_id"], "condition": "sprawny"}
            ]
        },
        headers=headers,
    )
    assert twice.status_code == 409
    history = (
        await app_client.get(f"/api/equipment/items/{laptop['id']}", headers=headers)
    ).json()["history"]
    assert history[0]["issue_protocol"] == protocol["number"]
    assert history[0]["return_protocol"] == back["number"]

    docx_file = await app_client.get(
        f"/api/equipment/protocols/{protocol['id']}/document.docx", headers=headers
    )
    assert docx_file.status_code == 200
    assert docx_file.content.startswith(b"PK")


async def test_return_of_two_people_needs_two_protocols(
    app_client, modules_on, people
) -> None:
    headers = _headers(people["reception"])
    model = await _model(app_client, headers, "akcesorium", "100.00")
    first = await _item(app_client, headers, model["id"])
    second = await _item(app_client, headers, model["id"])
    for item, holder in ((first, people["worker"]), (second, people["hr"])):
        issued = await app_client.post(
            "/api/equipment/issue",
            json={
                "holder_kind": "user",
                "holder_id": holder.id,
                "lines": [{"item_id": item["id"]}],
            },
            headers=headers,
        )
        assert issued.status_code == 201, issued.text
    async with AsyncSessionLocal() as db:
        assignment_ids = (
            await db.scalars(
                select(EquipmentAssignment.id).where(
                    EquipmentAssignment.item_id.in_([first["id"], second["id"]]),
                    EquipmentAssignment.returned_at.is_(None),
                )
            )
        ).all()
    mixed = await app_client.post(
        "/api/equipment/return",
        json={
            "lines": [
                {"assignment_id": a, "condition": "sprawny"} for a in assignment_ids
            ]
        },
        headers=headers,
    )
    assert mixed.status_code == 422


async def test_issue_to_contract_links_tab_rows_and_keeps_return_alert(
    app_client, app_auth_headers, modules_on, people
) -> None:
    from app.tasks.contract_alerts import _equipment_due_for_return

    headers = _headers(people["reception"])
    ids = await _contract(
        start=business_today() - timedelta(days=30),
        end=business_today() + timedelta(days=10),
    )
    try:
        model = await _model(app_client, headers, "laptop", "3000.00")
        laptop = await _item(app_client, headers, model["id"])
        issued = await app_client.post(
            "/api/equipment/issue",
            json={
                "holder_kind": "contract",
                "holder_id": ids["id"],
                "lines": [{"item_id": laptop["id"]}],
            },
            headers=headers,
        )
        assert issued.status_code == 201, issued.text
        rows = (
            await app_client.get(
                f"/api/contracts/{ids['id']}/equipment", headers=app_auth_headers
            )
        ).json()
        assert len(rows) == 1
        row = rows[0]
        assert row["item_id"] == laptop["id"]
        assert row["assignment_id"] is not None
        assert (
            row["return_due_date"]
            == (business_today() + timedelta(days=10)).isoformat()
        )
        assert row["item_type"] == "laptop" and row["owner"] == "ours"

        async with AsyncSessionLocal() as db:
            due = await _equipment_due_for_return(db)
        assert row["id"] in {item.id for item in due}  # stary dzwonek 14 dni działa

        bypass = await app_client.patch(
            f"/api/contracts/{ids['id']}/equipment/{row['id']}",
            json={"return_status": "returned"},
            headers=app_auth_headers,
        )
        assert bypass.status_code == 409
        note = await app_client.patch(
            f"/api/contracts/{ids['id']}/equipment/{row['id']}",
            json={"notes": "Uwaga fikcyjna"},
            headers=app_auth_headers,
        )
        assert note.status_code == 200
        removal = await app_client.delete(
            f"/api/contracts/{ids['id']}/equipment/{row['id']}",
            headers=app_auth_headers,
        )
        assert removal.status_code == 409

        view = await app_client.get(
            f"/api/equipment/contracts/{ids['id']}",
            headers=_headers(people["delivery"]),
        )
        assert view.status_code == 200
        assert [r["item_id"] for r in view.json()["active"]] == [laptop["id"]]
        assert (
            await app_client.get(
                f"/api/equipment/contracts/{ids['id']}",
                headers=_headers(people["recruiter"]),
            )
        ).status_code == 403

        task = await app_client.post(
            f"/api/equipment/contracts/{ids['id']}/return-task", headers=headers
        )
        assert (
            task.json()["task"]["due_on"]
            == (business_today() + timedelta(days=10)).isoformat()
        )

        returned = await app_client.post(
            "/api/equipment/return",
            json={
                "lines": [
                    {"assignment_id": row["assignment_id"], "condition": "sprawny"}
                ]
            },
            headers=headers,
        )
        assert returned.status_code == 201
        after = (
            await app_client.get(
                f"/api/contracts/{ids['id']}/equipment", headers=app_auth_headers
            )
        ).json()[0]
        assert after["return_status"] == "returned"
        assert after["returned_date"] == business_today().isoformat()
        async with AsyncSessionLocal() as db:
            closed = await db.scalar(
                select(EquipmentTask.status).where(
                    EquipmentTask.source_key == f"contract:{ids['id']}:end"
                )
            )
        assert closed == "zrobione"
    finally:
        await _drop_contract(ids)


async def test_hard_deleted_contract_returns_item_to_stock(
    app_client, modules_on, people
) -> None:
    headers = _headers(people["reception"])
    ids = await _contract(start=business_today(), end=None)
    model = await _model(app_client, headers, "telefon", "800.00")
    phone = await _item(
        app_client,
        headers,
        model["id"],
        imei=str(350000000000000 + uuid.uuid4().int % 99999),
    )
    issued = await app_client.post(
        "/api/equipment/issue",
        json={
            "holder_kind": "contract",
            "holder_id": ids["id"],
            "lines": [{"item_id": phone["id"]}],
        },
        headers=headers,
    )
    assert issued.status_code == 201
    await _drop_contract(ids)
    detail = (
        await app_client.get(f"/api/equipment/items/{phone['id']}", headers=headers)
    ).json()
    assert detail["status"] == "na_stanie"
    assert detail["holder"] is None


async def test_manual_tab_rows_link_to_register_only_when_unambiguous(
    app_client, modules_on, people
) -> None:
    from app.models.contract_equipment import (
        ContractEquipment,
        EquipmentItemType,
        EquipmentOwner,
    )
    from app.services.equipment import registry

    headers = _headers(people["reception"])
    ids = await _contract(start=business_today(), end=None)
    try:
        tag = _tag()
        unique = f"TEST{tag}A"
        ambiguous = str(350_000_000_000_000 + uuid.uuid4().int % 99_999_999_999)
        model = await _model(app_client, headers, "telefon", "500.00")
        await _item(app_client, headers, model["id"], serial_number=unique)
        # Ten sam numer jako IMEI jednego i S/N drugiego egzemplarza = niejednoznaczny.
        await _item(app_client, headers, model["id"], imei=ambiguous)
        await _item(app_client, headers, model["id"], serial_number=ambiguous)
        async with AsyncSessionLocal() as db:
            rows = [
                ContractEquipment(
                    contract_id=ids["id"],
                    item_type=EquipmentItemType.phone,
                    owner=EquipmentOwner.ours,
                    serial_number=serial,
                )
                for serial in (unique.lower(), ambiguous, "BRAK-W-REJESTRZE")
            ]
            db.add_all(rows)
            await db.flush()
            await registry.link_contract_equipment(db)
            await db.commit()
            linked = {
                row.serial_number: row.item_id
                for row in (
                    await db.scalars(
                        select(ContractEquipment).where(
                            ContractEquipment.contract_id == ids["id"]
                        )
                    )
                ).all()
            }
        assert linked[unique.lower()] is not None
        assert linked[ambiguous] is None
        assert linked["BRAK-W-REJESTRZE"] is None
    finally:
        await _drop_contract(ids)


# ── Zadania ───────────────────────────────────────────────────────────────────


async def test_workdays_before_skips_weekends_and_public_holidays() -> None:
    async with AsyncSessionLocal() as db:
        # Pn 11.01.2027 − 7 dni rob.: 6.01 (Trzech Króli) i 1.01 to święta.
        assert await equipment_tasks.workdays_before(db, date(2027, 1, 11), 7) == date(
            2026, 12, 29
        )


async def test_contract_and_exit_tasks_are_idempotent(
    app_client, modules_on, people
) -> None:
    start = business_today() + timedelta(days=40)
    ours = await _contract(start=start, end=start + timedelta(days=90), provider="nasz")
    theirs = await _contract(start=start, end=None, provider="klienta")
    try:
        async with AsyncSessionLocal() as db:
            contract = await db.get(Contract, ours["id"])
            first = await equipment_tasks.tasks_for_contract_start(db, contract)
            second = await equipment_tasks.tasks_for_contract_start(db, contract)
            assert first is not None and first.id == second.id
            assert first.due_on == await equipment_tasks.workdays_before(db, start, 7)
            assert first.kind == "wydanie"
            assert (
                await equipment_tasks.tasks_for_contract_start(
                    db, await db.get(Contract, theirs["id"])
                )
                is None
            )
            # Przesunięty start = nowy termin tego samego zadania, nie drugie zadanie.
            contract.start_date = start + timedelta(days=7)
            await db.flush()
            moved = await equipment_tasks.tasks_for_contract_start(db, contract)
            assert moved.id == first.id
            assert moved.due_on == await equipment_tasks.workdays_before(
                db, start + timedelta(days=7), 7
            )
            # Koniec współpracy bez sprzętu = bez zadania.
            assert await equipment_tasks.tasks_for_contract_end(db, contract) is None
            count = await db.scalar(
                select(text("count(*)"))
                .select_from(EquipmentTask)
                .where(EquipmentTask.source_key.like(f"contract:{ours['id']}:%"))
            )
            assert count == 1
            await db.commit()

        headers = _headers(people["reception"])
        model = await _model(app_client, headers, "akcesorium", "10.00")
        item = await _item(app_client, headers, model["id"])
        await app_client.post(
            "/api/equipment/issue",
            json={
                "holder_kind": "user",
                "holder_id": people["hr"].id,
                "lines": [{"item_id": item["id"]}],
            },
            headers=headers,
        )
        async with AsyncSessionLocal() as db:
            last_day = business_today() + timedelta(days=20)
            exit_a = await equipment_tasks.tasks_for_person_exit(
                db, people["hr"].id, last_day
            )
            exit_b = await equipment_tasks.tasks_for_person_exit(
                db, people["hr"].id, last_day
            )
            assert exit_a.id == exit_b.id and exit_a.kind == "zwrot"
            assert exit_a.due_on == last_day
            nothing = await equipment_tasks.tasks_for_person_exit(
                db, people["recruiter"].id, last_day
            )
            assert nothing is None
            await db.commit()
        listed = await app_client.get("/api/equipment/tasks", headers=headers)
        titles = {t["id"] for t in listed.json()["items"]}
        assert exit_a.id in titles
    finally:
        await _drop_contract(ours)
        await _drop_contract(theirs)


async def test_reminders_run_once_per_day(app_client, modules_on, people) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(HrJobRun).where(
                HrJobRun.kind == equipment_tasks.REMINDER_JOB,
                HrJobRun.period_key == business_today().isoformat(),
            )
        )
        await equipment_tasks.upsert_task(
            db,
            kind="zakup",
            source_key=f"test:{_tag()}",
            title="Kup zasilacz (fikcja)",
            due_on=business_today() - timedelta(days=1),
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        first = await equipment_tasks.run_once(db, remind_from_hour=0)
    async with AsyncSessionLocal() as db:
        second = await equipment_tasks.run_once(db, remind_from_hour=0)
    assert first["tasks"] >= 1
    assert second == {"skipped": True}
    async with AsyncSessionLocal() as db:
        bells = (
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == people["reception"].id,
                    Notification.notification_type == NotificationType.equipment_task,
                )
            )
        ).all()
        recruiter_bells = await db.scalar(
            select(text("count(*)"))
            .select_from(Notification)
            .where(
                Notification.user_id == people["recruiter"].id,
                Notification.notification_type == NotificationType.equipment_task,
            )
        )
    assert len(bells) == 1
    assert bells[0].link == "/equipment?tab=tasks"
    assert recruiter_bells == 0


async def test_reminders_stay_silent_when_module_is_off(modules_off) -> None:
    async with AsyncSessionLocal() as db:
        result = await equipment_tasks.run_once(db, remind_from_hour=0)
    assert result == {"status": "disabled"}


# ── Protokół: podpis i potwierdzenie ──────────────────────────────────────────


async def _issued_protocol(app_client, people) -> dict:
    headers = _headers(people["reception"])
    model = await _model(app_client, headers, "monitor", "700.00")
    item = await _item(app_client, headers, model["id"])
    issued = await app_client.post(
        "/api/equipment/issue",
        json={
            "holder_kind": "user",
            "holder_id": people["worker"].id,
            "lines": [{"item_id": item["id"]}],
        },
        headers=headers,
    )
    assert issued.status_code == 201, issued.text
    return issued.json()["protocol"]


async def test_paper_signature_is_confirmed_by_a_person(
    app_client, modules_on, people
) -> None:
    headers = _headers(people["reception"])
    protocol = await _issued_protocol(app_client, people)
    unsigned = await app_client.post(
        f"/api/equipment/protocols/{protocol['id']}/confirm", json={}, headers=headers
    )
    assert unsigned.status_code == 422
    confirmed = await app_client.post(
        f"/api/equipment/protocols/{protocol['id']}/confirm",
        json={"method": "papier"},
        headers=headers,
    )
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert (body["status"], body["signature_method"]) == ("potwierdzony", "papier")
    again = await app_client.post(
        f"/api/equipment/protocols/{protocol['id']}/link", headers=headers
    )
    assert again.status_code == 409
    async with AsyncSessionLocal() as db:
        task = await db.scalar(
            select(EquipmentTask).where(
                EquipmentTask.source_key == f"protocol:{protocol['id']}:podpis"
            )
        )
    assert task.status == "zrobione"


async def test_signature_task_title_names_the_person_and_row_carries_context(
    app_client, modules_on, people
) -> None:
    """Prod 20.10: „Podpis protokołu PZO/2026/10/001: …” ucinał nazwisko przy 1280.

    Tytuł = osoba; numer, klient i dzień wysłania linku idą do drugiej linii.
    """
    headers = _headers(people["reception"])
    ids = await _contract(start=business_today() - timedelta(days=30), end=None)
    try:
        model = await _model(app_client, headers, "monitor", "700.00")
        item = await _item(app_client, headers, model["id"])
        issued = await app_client.post(
            "/api/equipment/issue",
            json={
                "holder_kind": "contract",
                "holder_id": ids["id"],
                "lines": [{"item_id": item["id"]}],
            },
            headers=headers,
        )
        assert issued.status_code == 201, issued.text
        protocol = issued.json()["protocol"]

        def signature_row(payload: dict) -> dict:
            return next(
                t
                for t in payload["items"]
                if t["protocol"] and t["protocol"]["id"] == protocol["id"]
            )

        before = signature_row(
            (await app_client.get("/api/equipment/tasks", headers=headers)).json()
        )
        assert before["title"] == f"Podpis protokołu: {protocol['holder']['name']}"
        assert protocol["number"] not in before["title"]
        assert before["protocol"]["number"] == protocol["number"]
        assert before["protocol"]["client_name"].startswith("Klient Fikcyjny")
        assert before["protocol"]["link_sent_on"] is None

        link = await app_client.post(
            f"/api/equipment/protocols/{protocol['id']}/link", headers=headers
        )
        assert link.status_code == 200, link.text
        after = signature_row(
            (await app_client.get("/api/equipment/tasks", headers=headers)).json()
        )
        assert after["protocol"]["link_sent_on"] == business_today().isoformat()
    finally:
        await _drop_contract(ids)


async def test_signed_scan_upload(app_client, modules_on, people) -> None:
    headers = _headers(people["reception"])
    protocol = await _issued_protocol(app_client, people)
    wrong = await app_client.post(
        f"/api/equipment/protocols/{protocol['id']}/signed-file",
        files={"file": ("skan.txt", b"to nie pdf", "text/plain")},
        data={"method": "papier"},
        headers=headers,
    )
    assert wrong.status_code == 422
    uploaded = await app_client.post(
        f"/api/equipment/protocols/{protocol['id']}/signed-file",
        files={"file": ("skan.pdf", b"%PDF-1.4 fikcja", "application/pdf")},
        data={"method": "profil_zaufany"},
        headers=headers,
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["status"] == "podpisany"
    assert uploaded.json()["has_signed_file"] is True
    download = await app_client.get(
        f"/api/equipment/protocols/{protocol['id']}/signed-file", headers=headers
    )
    assert download.status_code == 200
    assert download.content.startswith(b"%PDF")


# ── Flaga klienta i osoby spoza NEXUSA ───────────────────────────────────────


async def test_client_provider_flag_and_external_people(
    app_client, modules_on, people
) -> None:
    ids = await _contract(start=business_today(), end=None)
    try:
        async with AsyncSessionLocal() as db:
            editor = await _user(db, grants=("clients_edit",))
            await db.commit()
        url = f"/api/equipment/clients/{ids['client_id']}/provider"
        assert (
            await app_client.put(
                url,
                json={"equipment_provider": "nasz"},
                headers=_headers(people["recruiter"]),
            )
        ).status_code == 403
        saved = await app_client.put(
            url, json={"equipment_provider": "nasz"}, headers=_headers(editor)
        )
        assert saved.status_code == 200
        assert saved.json() == {"equipment_provider": "nasz"}
        bad = await app_client.put(
            url, json={"equipment_provider": "x"}, headers=_headers(editor)
        )
        assert bad.status_code == 422
        read = await app_client.get(url, headers=_headers(people["delivery"]))
        assert read.json() == {"equipment_provider": "nasz"}
    finally:
        await _drop_contract(ids)

    headers = _headers(people["reception"])
    private = await app_client.post(
        "/api/equipment/external-people",
        json={"full_name": "Ola Przykładowa", "work_email": "ola@wp.pl"},
        headers=headers,
    )
    assert private.status_code == 422
    person = await app_client.post(
        "/api/equipment/external-people",
        json={
            "full_name": "Ola Przykładowa",
            "work_email": "ola@example.com",
            "note": "Akademia",
        },
        headers=headers,
    )
    assert person.status_code == 201
    model = await _model(app_client, headers, "laptop", "1500.00")
    item = await _item(app_client, headers, model["id"])
    issued = await app_client.post(
        "/api/equipment/issue",
        json={
            "holder_kind": "external",
            "holder_id": person.json()["id"],
            "lines": [{"item_id": item["id"]}],
        },
        headers=headers,
    )
    assert issued.status_code == 201
    assert issued.json()["protocol"]["holder"]["kind"] == "external"


async def test_summary_counts_free_items(app_client, modules_on, people) -> None:
    headers = _headers(people["reception"])
    before = (await app_client.get("/api/equipment/summary", headers=headers)).json()
    model = await _model(app_client, headers, "monitor", "500.00")
    await _item(app_client, headers, model["id"])
    after = (await app_client.get("/api/equipment/summary", headers=headers)).json()
    assert (
        after["free_by_category"]["monitor"]
        == before["free_by_category"]["monitor"] + 1
    )


# ── Czwarty posiadacz: uczestnik Akademii (0465) ──────────────────────────────


async def make_academy_participant(
    *,
    status: str = "signed",
    program_id: int | None = None,
    session_id: int | None = None,
    cohort_month: date | None = None,
    closed_stage: str | None = None,
    session_days_ahead: int = -7,
) -> dict:
    """Program, termin (edycja) i zgłoszenie fikcyjnej osoby z Akademii."""
    from datetime import datetime, timezone

    from app.models.academy import (
        AcademyApplication,
        AcademyProgram,
        AcademySession,
    )

    token = _tag()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        if program_id is None:
            program = AcademyProgram(name=f"Akademia Testowa {token}")
            db.add(program)
            await db.flush()
            program_id = program.id
        if session_id is None:
            session = AcademySession(
                program_id=program_id,
                starts_at=now + timedelta(days=session_days_ahead),
                location="sala testowa",
                capacity=8,
            )
            db.add(session)
            await db.flush()
            session_id = session.id
        candidate = Candidate(
            name="Ola",
            lastname=f"Przykładowa-{token}",
            email=f"akademia-{token.lower()}@example.com",
            city="Lublin",
        )
        db.add(candidate)
        await db.flush()
        application = AcademyApplication(
            program_id=program_id,
            candidate_id=candidate.id,
            applied_at=now - timedelta(days=30),
            status=status,
            session_id=session_id,
            attended=True,
            cohort_month=cohort_month,
            signed_at=now if status == "signed" else None,
            closed_stage=closed_stage,
            closed_reason="Test" if status in ("rejected", "withdrew") else None,
        )
        db.add(application)
        await db.commit()
        return {
            "program_id": program_id,
            "session_id": session_id,
            "application_id": application.id,
            "candidate_id": candidate.id,
            "name": f"Ola Przykładowa-{token}",
            "email": candidate.email,
        }


async def test_academy_participant_is_the_fourth_holder(
    app_client, modules_on, people
) -> None:
    headers = _headers(people["reception"])
    person = await make_academy_participant(status="signed")
    model = await _model(app_client, headers, "laptop", "1800.00")
    item = await _item(app_client, headers, model["id"], inventory_number=f"A-{_tag()}")

    found = await app_client.get(
        "/api/equipment/holders",
        params={"q": person["name"], "kind": "academy"},
        headers=headers,
    )
    assert found.status_code == 200
    hits = [h for h in found.json()["items"] if h["id"] == person["application_id"]]
    assert hits and hits[0]["kind"] == "academy"
    assert hits[0]["detail"].startswith("Uczestnik Akademii")
    general = await app_client.get(
        "/api/equipment/holders", params={"q": person["name"]}, headers=headers
    )
    assert all(h["kind"] != "academy" for h in general.json()["items"])

    issued = await app_client.post(
        "/api/equipment/issue",
        json={
            "holder_kind": "academy",
            "holder_id": person["application_id"],
            "lines": [{"item_id": item["id"]}],
        },
        headers=headers,
    )
    assert issued.status_code == 201, issued.text
    protocol = issued.json()["protocol"]
    # Nazwa i e-mail z kandydata zgłoszenia; PESEL-u ani adresu nie ma w ogóle.
    assert protocol["holder"] == {
        "kind": "academy",
        "id": person["application_id"],
        "name": person["name"],
        "email": person["email"],
    }
    assert "pesel" not in issued.text.lower()

    items = await app_client.get(
        "/api/equipment/items", params={"holder": "academy"}, headers=headers
    )
    row = next(i for i in items.json()["items"] if i["id"] == item["id"])
    assert row["holder"]["kind"] == "academy"
    assert row["holder"]["name"] == person["name"]
    own = await app_client.get(
        f"/api/equipment/holders/academy/{person['application_id']}", headers=headers
    )
    assert own.status_code == 200
    assert [r["item_id"] for r in own.json()["active"]] == [item["id"]]
    assert own.json()["holder"]["name"] == person["name"]

    tasks = await app_client.get(
        "/api/equipment/tasks", params={"status": "otwarte"}, headers=headers
    )
    signature = next(
        t
        for t in tasks.json()["items"]
        if (t["protocol"] or {}).get("id") == protocol["id"]
    )
    assert signature["holder"]["kind"] == "academy"
    assert signature["holder"]["name"] == person["name"]

    returned = await app_client.post(
        "/api/equipment/return",
        json={
            "lines": [
                {
                    "assignment_id": own.json()["active"][0]["assignment_id"],
                    "condition": "sprawny",
                }
            ]
        },
        headers=headers,
    )
    assert returned.status_code == 201, returned.text
    assert returned.json()["protocol"]["holder"]["kind"] == "academy"


async def test_academy_holder_must_be_a_participant(
    app_client, modules_on, people
) -> None:
    headers = _headers(people["reception"])
    model = await _model(app_client, headers, "monitor", "400.00")
    for status_value, expected in (("withdrew", 409), ("to_call", 409)):
        person = await make_academy_participant(
            status=status_value,
            closed_stage="signed" if status_value == "withdrew" else None,
        )
        item = await _item(app_client, headers, model["id"])
        refused = await app_client.post(
            "/api/equipment/issue",
            json={
                "holder_kind": "academy",
                "holder_id": person["application_id"],
                "lines": [{"item_id": item["id"]}],
            },
            headers=headers,
        )
        assert refused.status_code == expected, (status_value, refused.text)
        detail = await app_client.get(
            f"/api/equipment/items/{item['id']}", headers=headers
        )
        assert detail.json()["status"] == "na_stanie"
    missing = await app_client.post(
        "/api/equipment/issue",
        json={
            "holder_kind": "academy",
            "holder_id": 987654321,
            "lines": [{"item_id": 1}],
        },
        headers=headers,
    )
    assert missing.status_code == 404
    # Baza: dokładnie jeden z czterech posiadaczy.
    person = await make_academy_participant()
    async with AsyncSessionLocal() as db:
        model_row = EquipmentModel(category="monitor", name=f"Monitor {_tag()}")
        db.add(model_row)
        await db.flush()
        item_row = EquipmentItem(model_id=model_row.id, serial_number=f"TEST{_tag()}")
        db.add(item_row)
        await db.flush()
        with pytest.raises(IntegrityError):
            await db.execute(
                text(
                    "INSERT INTO equipment_assignments "
                    "(item_id, user_id, academy_application_id) "
                    "VALUES (:item, :user, :app)"
                ),
                {
                    "item": item_row.id,
                    "user": people["worker"].id,
                    "app": person["application_id"],
                },
            )
        await db.rollback()


async def test_protocol_texts_refuse_secrets(app_client, modules_on, people) -> None:
    """D10 także w tekstach protokołu: akcesoria przy wydaniu i notatka przy zwrocie.

    Te teksty trafiają do pozycji protokołu, DOCX/PDF i na publiczną stronę
    podpisu — klucz BitLocker wklejony „przy okazji” nie może tam dojść.
    """
    headers = _headers(people["reception"])
    worker = people["worker"]
    bitlocker = "-".join(["123456"] * 8)
    model = await _model(app_client, headers, "laptop", "2000.00")
    laptop = await _item(
        app_client, headers, model["id"], inventory_number=f"S-{_tag()}"
    )

    refused = await app_client.post(
        "/api/equipment/issue",
        json={
            "holder_kind": "user",
            "holder_id": worker.id,
            "lines": [
                {"item_id": laptop["id"], "accessories": f"zasilacz, klucz {bitlocker}"}
            ],
        },
        headers=headers,
    )
    assert refused.status_code == 422, refused.text
    assert bitlocker not in refused.text

    issued = await app_client.post(
        "/api/equipment/issue",
        json={
            "holder_kind": "user",
            "holder_id": worker.id,
            "lines": [{"item_id": laptop["id"], "accessories": "zasilacz"}],
        },
        headers=headers,
    )
    assert issued.status_code == 201, issued.text
    async with AsyncSessionLocal() as db:
        assignment_id = await db.scalar(
            select(EquipmentAssignment.id).where(
                EquipmentAssignment.item_id == laptop["id"],
                EquipmentAssignment.returned_at.is_(None),
            )
        )
    returned = await app_client.post(
        "/api/equipment/return",
        json={
            "lines": [
                {
                    "assignment_id": assignment_id,
                    "condition": "sprawny",
                    "notes": f"klucz odzyskiwania {bitlocker}",
                }
            ]
        },
        headers=headers,
    )
    assert returned.status_code == 422, returned.text


# ── Makieta Sprzętu (19.10.2026): przypomnienie, liczniki, „bez podpisu” ───────


async def test_remind_holder_rings_the_account_and_records_the_reminder(
    app_client, modules_on, people
) -> None:
    headers = _headers(people["reception"])
    model = await _model(app_client, headers, "akcesorium", "37.00")
    item = await _item(app_client, headers, model["id"])
    issued = await app_client.post(
        "/api/equipment/issue",
        json={
            "holder_kind": "user",
            "holder_id": people["worker"].id,
            "lines": [{"item_id": item["id"]}],
        },
        headers=headers,
    )
    assert issued.status_code == 201, issued.text
    async with AsyncSessionLocal() as db:
        task = await equipment_tasks.tasks_for_person_exit(
            db, people["worker"].id, business_today() - timedelta(days=2)
        )
        await db.commit()
    url = f"/api/equipment/tasks/{task.id}/remind"

    for who in ("hr", "recruiter", "worker"):
        refused = await app_client.post(url, headers=_headers(people[who]))
        assert refused.status_code == 403, who

    reminded = await app_client.post(url, headers=headers)
    assert reminded.status_code == 200, reminded.text
    body = reminded.json()
    assert body["channel"] == "powiadomienie" and body["email"] is None
    assert body["reminded_on"] == business_today().isoformat()
    async with AsyncSessionLocal() as db:
        bells = (
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == people["worker"].id,
                    Notification.notification_type
                    == NotificationType.equipment_return_reminder,
                )
            )
        ).all()
        stored = await db.get(EquipmentTask, task.id)
    assert len(bells) == 1
    assert bells[0].link == "/my-time?tab=profile"
    # Bez listy sprzętu i bez kwot — tylko prośba i termin.
    assert "37" not in bells[0].message and model["name"] not in bells[0].message
    assert stored.details["reminded_on"] == business_today().isoformat()
    assert stored.details["reminders"] == 1

    listed = await app_client.get("/api/equipment/tasks", headers=headers)
    row = next(t for t in listed.json()["items"] if t["id"] == task.id)
    assert row["details"]["reminded_on"] == business_today().isoformat()


async def test_remind_holder_does_not_fake_success_when_nothing_went_out(
    app_client, modules_on, people
) -> None:
    """Audyt 22.10, F23: wyłączone konto (odejście) nie dostaje dzwonka — 409
    bez wpisu „przypomniano”; drugie przypomnienie tego samego dnia połyka
    dzienny dedup — recepcja dostaje adres do własnego maila."""

    headers = _headers(people["reception"])
    model = await _model(app_client, headers, "akcesorium", "37.00")
    item = await _item(app_client, headers, model["id"])
    issued = await app_client.post(
        "/api/equipment/issue",
        json={
            "holder_kind": "user",
            "holder_id": people["worker"].id,
            "lines": [{"item_id": item["id"]}],
        },
        headers=headers,
    )
    assert issued.status_code == 201, issued.text
    async with AsyncSessionLocal() as db:
        task = await equipment_tasks.tasks_for_person_exit(
            db, people["worker"].id, business_today() - timedelta(days=2)
        )
        await db.commit()
    url = f"/api/equipment/tasks/{task.id}/remind"

    first = await app_client.post(url, headers=headers)
    assert first.json()["channel"] == "powiadomienie", first.text
    again = await app_client.post(url, headers=headers)
    assert again.status_code == 200, again.text
    assert again.json()["channel"] == "mail"
    assert again.json()["email"] == people["worker"].email

    async with AsyncSessionLocal() as db:
        worker = await db.get(User, people["worker"].id)
        worker.is_active = False
        await db.commit()
    gone = await app_client.post(url, headers=headers)
    assert gone.status_code == 409, gone.text
    assert "wyłączone" in gone.json()["detail"]
    async with AsyncSessionLocal() as db:
        stored = await db.get(EquipmentTask, task.id)
        bells = (
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == people["worker"].id,
                    Notification.notification_type
                    == NotificationType.equipment_return_reminder,
                )
            )
        ).all()
    assert len(bells) == 1
    assert stored.details["reminders"] == 2


async def test_remind_holder_without_account_returns_the_mail_address(
    app_client, modules_on, people
) -> None:
    headers = _headers(people["reception"])
    ids = await _contract(start=business_today() - timedelta(days=30), end=None)
    try:
        model = await _model(app_client, headers, "telefon", "649.00")
        item = await _item(app_client, headers, model["id"])
        issued = await app_client.post(
            "/api/equipment/issue",
            json={
                "holder_kind": "contract",
                "holder_id": ids["id"],
                "lines": [{"item_id": item["id"]}],
            },
            headers=headers,
        )
        assert issued.status_code == 201, issued.text
        async with AsyncSessionLocal() as db:
            contract = await db.get(Contract, ids["id"])
            contract.end_date = business_today() - timedelta(days=1)
            task = await equipment_tasks.tasks_for_contract_end(db, contract)
            start_task = await equipment_tasks.upsert_task(
                db,
                kind="wydanie",
                source_key=f"test:{_tag()}",
                title="Przygotuj zestaw (fikcja)",
                due_on=business_today(),
                contract_id=ids["id"],
            )
            await db.commit()
        reminded = await app_client.post(
            f"/api/equipment/tasks/{task.id}/remind", headers=headers
        )
        assert reminded.status_code == 200, reminded.text
        assert reminded.json()["channel"] == "mail"
        assert reminded.json()["email"].startswith("eqc-")
        # Przypomnieć można tylko o zwrocie.
        wrong = await app_client.post(
            f"/api/equipment/tasks/{start_task.id}/remind", headers=headers
        )
        assert wrong.status_code == 409
        missing = await app_client.post(
            "/api/equipment/tasks/999999999/remind", headers=headers
        )
        assert missing.status_code == 404
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(EquipmentTask).where(EquipmentTask.contract_id == ids["id"])
            )
            await db.commit()
        await _drop_contract(ids)


async def test_summary_breaks_down_categories_and_unsigned_items(
    app_client, modules_on, people
) -> None:
    headers = _headers(people["reception"])
    before = (await app_client.get("/api/equipment/summary", headers=headers)).json()
    model = await _model(app_client, headers, "monitor", "650.00")
    first = await _item(app_client, headers, model["id"])
    await _item(app_client, headers, model["id"])
    issued = await app_client.post(
        "/api/equipment/issue",
        json={
            "holder_kind": "user",
            "holder_id": people["worker"].id,
            "lines": [{"item_id": first["id"]}],
        },
        headers=headers,
    )
    assert issued.status_code == 201, issued.text
    protocol = issued.json()["protocol"]
    after = (await app_client.get("/api/equipment/summary", headers=headers)).json()
    monitors_before = before["by_category"]["monitor"]
    monitors = after["by_category"]["monitor"]
    assert monitors["wydany"] == monitors_before["wydany"] + 1
    assert monitors["na_stanie"] == monitors_before["na_stanie"] + 1
    assert after["unsigned_items"] == before["unsigned_items"] + 1
    assert after["oldest_waiting_on"] is not None
    assert after["oldest_waiting_on"] <= protocol["protocol_date"]

    unsigned = await app_client.get(
        "/api/equipment/items",
        params={"unsigned": "true", "category": "monitor"},
        headers=headers,
    )
    assert unsigned.status_code == 200
    ids = {row["id"] for row in unsigned.json()["items"]}
    assert first["id"] in ids
    assert all(
        row["issue_protocol"]["status"] in ("oczekuje", "podpisany")
        for row in unsigned.json()["items"]
    )

    # Zadanie podpisu niesie skład protokołu (ikony w agendzie).
    tasks = await app_client.get("/api/equipment/tasks", headers=headers)
    signature = next(
        t
        for t in tasks.json()["items"]
        if t["protocol"] and t["protocol"]["id"] == protocol["id"]
    )
    assert signature["protocol"]["categories"] == ["monitor"]
    assert signature["protocol"]["status"] == "oczekuje"

    confirmed = await app_client.post(
        f"/api/equipment/protocols/{protocol['id']}/confirm",
        json={"method": "papier"},
        headers=headers,
    )
    assert confirmed.status_code == 200
    unsigned_after = await app_client.get(
        "/api/equipment/items",
        params={"unsigned": "true", "category": "monitor"},
        headers=headers,
    )
    assert first["id"] not in {row["id"] for row in unsigned_after.json()["items"]}
