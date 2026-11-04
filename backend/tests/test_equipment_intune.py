"""Sprzęt ↔ Intune (etap 4, D9): nocny odczyt, rozjazdy, decyzje recepcji, bramki.

Przebieg dostaje fałszywe źródło urządzeń (bez sieci), klient ``live`` —
fałszywy transport HTTP pod ``AppGraphClient``. Dane fikcyjne (repo jest
publiczne): S/N „TESTINT…”, konta i UPN ``@example.com``.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.api.equipment_intune import router as intune_router
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.equipment import EquipmentAssignment, EquipmentItem, EquipmentModel
from app.models.equipment_intune import (
    EquipmentIntuneDevice,
    EquipmentIntuneSyncState,
)
from app.models.hr_ops import HrJobRun
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services.equipment import intune, intune_graph
from app.services.equipment.intune_graph import IntuneDevice, device_from_graph
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING

WARSAW = ZoneInfo("Europe/Warsaw")


def _tag() -> str:
    return uuid.uuid4().hex[:8].upper()


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


class FakeSource:
    def __init__(self, devices: list[IntuneDevice]) -> None:
        self.devices = devices

    async def list_devices(self) -> list[IntuneDevice]:
        return list(self.devices)


def _device(
    device_id: str,
    *,
    serial: Optional[str] = None,
    upn: Optional[str] = None,
    name: Optional[str] = None,
) -> IntuneDevice:
    device = device_from_graph(
        {
            "id": device_id,
            "deviceName": name or f"LAPTOP-{device_id[-6:]}",
            "serialNumber": serial,
            "manufacturer": "Lenovo",
            "model": "ThinkPad",
            "operatingSystem": "Windows",
            "userPrincipalName": upn,
            "complianceState": "compliant",
            "lastSyncDateTime": "2026-10-15T05:00:00Z",
        }
    )
    assert device is not None
    return device


# ── Stan bazy i ludzie ───────────────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def clean_intune():
    """Migawka Intune i rezerwacje są globalne — każdy test startuje od zera.

    Wiersz stanu też znika: przebieg musi go założyć sam (świeża baza bez
    ``DATA_DDL`` nie może wywrócić pętli)."""
    async with AsyncSessionLocal() as db:
        await db.execute(delete(EquipmentIntuneDevice))
        await db.execute(delete(HrJobRun).where(HrJobRun.kind == intune.JOB_KIND))
        await db.execute(delete(EquipmentIntuneSyncState))
        await db.commit()
    yield


async def _set_modules(value: dict) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value=value))
        else:
            row.value = value
        await db.commit()


@asynccontextmanager
async def modules_state(on: bool):
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _set_modules({key: on for key in HR_MODULE_KEYS})
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


async def _user(
    db, role: str = "recruiter", *, grants: tuple[str, ...] = (), upn=None
) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"intune-{marker}@example.com",
        name=f"Osoba Przykładowa {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
        microsoft_upn=upn,
    )
    db.add(user)
    await db.flush()
    for action in grants:
        db.add(UserActionOverride(user_id=user.id, action=action, access="manage"))
    await db.flush()
    return user


@pytest_asyncio.fixture
async def people() -> dict[str, User]:
    async with AsyncSessionLocal() as db:
        out = {
            "reception": await _user(db, grants=("equipment",)),
            "hr": await _user(db, grants=("people_admin",)),
            "recruiter": await _user(db),
            "admin": await _user(db, "admin"),
        }
        await db.commit()
    return out


@pytest_asyncio.fixture
async def api():
    app = FastAPI()
    app.include_router(intune_router, prefix="/api/equipment/intune")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


async def _laptop(
    db,
    serial: Optional[str],
    *,
    status: str = "na_stanie",
    ownership: str = "nasz",
    category: str = "laptop",
) -> EquipmentItem:
    model = EquipmentModel(category=category, name=f"Model {_tag()}")
    db.add(model)
    await db.flush()
    item = EquipmentItem(
        model_id=model.id, serial_number=serial, status=status, ownership=ownership
    )
    db.add(item)
    await db.flush()
    return item


async def _issue(db, item: EquipmentItem, **holder: int) -> None:
    item.status = "wydany"
    db.add(EquipmentAssignment(item_id=item.id, **holder))
    await db.flush()


async def _contract(db, email: Optional[str]) -> Contract:
    token = _tag()
    candidate = Candidate(name="Jan", lastname=f"Testowy-{token}", email=email)
    client = Client(name=f"Klient Fikcyjny {token}")
    db.add_all([candidate, client])
    await db.flush()
    contract = Contract(
        candidate_id=candidate.id,
        client_id=client.id,
        status=ContractStatus.active,
        contract_type=ContractType("b2b"),
        start_date=date(2026, 9, 1),
        end_date=None,
        rate_client=100,
        rate_candidate=80,
        margin=20,
        currency="PLN",
    )
    db.add(contract)
    await db.flush()
    return contract


async def _run(devices: list[IntuneDevice], now: datetime) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        return await intune.run_once(
            db, source=FakeSource(devices), mode="simulate", now=now, manual=True
        )


async def _devices() -> dict[str, EquipmentIntuneDevice]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(select(EquipmentIntuneDevice))
        return {row.intune_device_id: row for row in rows.all()}


async def _report() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        return await intune.discrepancies(db)


def _kinds(report: dict[str, Any]) -> dict[str, str]:
    return {row["key"]: row["kind"] for row in report["rows"]}


# ── Przebieg ─────────────────────────────────────────────────────────────────


async def test_upsert_matches_serial_and_upn_without_case_and_is_idempotent() -> None:
    serial = f"TESTINT{_tag()}"
    async with AsyncSessionLocal() as db:
        item = await _laptop(db, serial)
        anna = await _user(db, "employee")
        piotr = await _user(db, "employee", upn=f"piotr.{_tag()}@example.com")
        await db.commit()
    devices = [
        _device("dev-a", serial=f"  {serial.lower()} ", upn=anna.email.upper()),
        _device("dev-b", serial=f"OBCY{_tag()}", upn=piotr.microsoft_upn.upper()),
        _device("dev-c", serial=None, upn=None),
    ]
    now = datetime.now(timezone.utc)

    first = await _run(devices, now)
    assert first["status"] == "ok"
    assert first["devices"] == 3 and first["created"] == 3
    assert first["matched_items"] == 1 and first["matched_users"] == 2
    second = await _run(devices, now + timedelta(minutes=5))
    assert second["status"] == "ok"
    assert second["created"] == 0 and second["missing"] == 0

    stored = await _devices()
    assert sorted(stored) == ["dev-a", "dev-b", "dev-c"]
    assert stored["dev-a"].item_id == item.id
    assert stored["dev-a"].user_id == anna.id
    # UPN inny niż e-mail konta — dopasowanie po ``microsoft_upn``.
    assert stored["dev-b"].user_id == piotr.id and stored["dev-b"].item_id is None
    assert stored["dev-a"].first_seen_at == now
    assert stored["dev-a"].last_seen_at == now + timedelta(minutes=5)
    async with AsyncSessionLocal() as db:
        state = await db.get(EquipmentIntuneSyncState, 1)
        assert state.device_count == 3 and state.last_error is None
        assert state.last_success_at == now + timedelta(minutes=5)


async def test_nightly_run_once_a_day_after_0530_and_only_with_module(
    modules_on,
) -> None:
    source = FakeSource([_device("dev-n")])
    early = datetime(2026, 1, 15, 5, 0, tzinfo=WARSAW)
    async with AsyncSessionLocal() as db:
        assert (await intune.run_once(db, source=source, mode="simulate", now=early))[
            "status"
        ] == "too_early"
        due = early + timedelta(hours=1)
        assert (await intune.run_once(db, source=source, mode="simulate", now=due))[
            "status"
        ] == "ok"
        again = await intune.run_once(
            db, source=source, mode="simulate", now=due + timedelta(hours=3)
        )
        assert again == {"status": "skipped", "reason": "already_ran"}
        # Admin może odczytać jeszcze raz tego samego dnia.
        manual = await intune.run_once(
            db,
            source=source,
            mode="simulate",
            now=due + timedelta(hours=4),
            manual=True,
        )
        assert manual["status"] == "ok"
        runs = await db.scalars(
            select(HrJobRun).where(HrJobRun.kind == intune.JOB_KIND)
        )
        assert [(r.period_key, r.status) for r in runs.all()] == [
            ("2026-01-15", "done")
        ]


async def test_nightly_run_respects_switched_off_module(modules_off) -> None:
    async with AsyncSessionLocal() as db:
        result = await intune.run_once(
            db,
            source=FakeSource([_device("dev-x")]),
            mode="simulate",
            now=datetime(2026, 1, 15, 6, 0, tzinfo=WARSAW),
        )
    assert result == {"status": "disabled"}
    assert await _devices() == {}


async def test_mode_off_does_nothing(monkeypatch) -> None:
    monkeypatch.setattr(intune_graph, "current_mode", lambda: "off")
    async with AsyncSessionLocal() as db:
        assert await intune.run_once(db, manual=True) == {"status": "disabled"}
        assert await intune.health_state(db) == "disabled"
        runs = await db.scalar(
            select(HrJobRun.id).where(HrJobRun.kind == intune.JOB_KIND)
        )
    assert runs is None


async def test_missing_since_is_set_once_and_cleared_on_return() -> None:
    t0 = datetime.now(timezone.utc)
    both = [_device("dev-1", serial="TESTINTA1"), _device("dev-2", serial="TESTINTA2")]
    await _run(both, t0)
    gone = await _run(both[:1], t0 + timedelta(minutes=1))
    assert gone["missing"] == 1
    assert (await _devices())["dev-2"].missing_since == t0 + timedelta(minutes=1)
    still = await _run(both[:1], t0 + timedelta(minutes=2))
    assert still["missing"] == 0
    # Data pierwszego braku zostaje.
    assert (await _devices())["dev-2"].missing_since == t0 + timedelta(minutes=1)
    back = await _run(both, t0 + timedelta(minutes=3))
    assert back["returned"] == 1
    stored = await _devices()
    assert stored["dev-2"].missing_since is None
    assert stored["dev-2"].last_seen_at == t0 + timedelta(minutes=3)


async def test_empty_answer_marks_nothing_missing_and_reports_error() -> None:
    t0 = datetime.now(timezone.utc)
    await _run([_device("dev-1")], t0)
    result = await _run([], t0 + timedelta(minutes=1))
    assert result == {"status": "error", "error": "empty_response"}
    assert (await _devices())["dev-1"].missing_since is None
    async with AsyncSessionLocal() as db:
        status = await intune.sync_status(db)
        state = await db.get(EquipmentIntuneSyncState, 1)
        assert state.last_success_at == t0
        assert intune.health_verdict("live", state, t0 + timedelta(minutes=2)) == (
            "degraded"
        )
    assert status["error_code"] == "empty_response"
    assert "pustą listę" in status["error"]


async def test_source_failure_keeps_snapshot_and_stores_category_only() -> None:
    class Failing:
        async def list_devices(self):
            raise intune_graph.IntuneSourceError(403)

    t0 = datetime.now(timezone.utc)
    await _run([_device("dev-1")], t0)
    async with AsyncSessionLocal() as db:
        result = await intune.run_once(
            db,
            source=Failing(),
            mode="live",
            now=t0 + timedelta(minutes=1),
            manual=True,
        )
        status = await intune.sync_status(db)
    assert result == {"status": "error", "error": "forbidden (403)"}
    assert (await _devices())["dev-1"].missing_since is None
    assert "DeviceManagementManagedDevices.Read.All" in status["error"]
    assert status["device_count"] == 1


# ── Rozjazdy ─────────────────────────────────────────────────────────────────


async def test_every_discrepancy_kind_and_matching_count() -> None:
    tag = _tag()
    async with AsyncSessionLocal() as db:
        anna = await _user(db, "employee")
        ewa = await _user(db, "employee")
        ok_item = await _laptop(db, f"TESTINTOK{tag}")
        await _issue(db, ok_item, user_id=anna.id)
        other_item = await _laptop(db, f"TESTINTOT{tag}")
        await _issue(db, other_item, user_id=ewa.id)
        contract = await _contract(db, f"konsultant-{tag.lower()}@example.com")
        contract_ok = await _laptop(db, f"TESTINTCO{tag}")
        await _issue(db, contract_ok, contract_id=contract.id)
        contract_other = await _laptop(db, f"TESTINTCX{tag}")
        await _issue(db, contract_other, contract_id=contract.id)
        no_mail = await _contract(db, None)
        no_mail_item = await _laptop(db, f"TESTINTNM{tag}")
        await _issue(db, no_mail_item, contract_id=no_mail.id)
        not_in_intune = await _laptop(db, f"TESTINTNI{tag}")
        await _issue(db, not_in_intune, user_id=anna.id)
        client_laptop = await _laptop(db, f"TESTINTCL{tag}", ownership="klienta")
        await _issue(db, client_laptop, user_id=anna.id)
        stock_laptop = await _laptop(db, f"TESTINTST{tag}")
        phone = await _laptop(db, f"TESTINTPH{tag}", category="telefon")
        await _issue(db, phone, user_id=anna.id)
        gone_item = await _laptop(db, f"TESTINTGO{tag}")
        await _issue(db, gone_item, user_id=anna.id)
        await db.commit()

    t0 = datetime.now(timezone.utc)
    devices = [
        _device("dev-ok", serial=ok_item.serial_number.lower(), upn=anna.email),
        _device("dev-other", serial=other_item.serial_number, upn=anna.email),
        _device("dev-unknown", serial=f"OBCY{tag}", upn=anna.email),
        _device(
            "dev-contract-ok",
            serial=contract_ok.serial_number,
            upn=f"KONSULTANT-{tag}@example.com",
        ),
        _device(
            "dev-contract-other",
            serial=contract_other.serial_number,
            upn=f"ktos-inny-{tag.lower()}@example.com",
        ),
        _device("dev-no-mail", serial=no_mail_item.serial_number, upn=anna.email),
        _device("dev-no-user", serial=stock_laptop.serial_number, upn=None),
        _device("dev-gone", serial=gone_item.serial_number, upn=anna.email),
    ]
    async with AsyncSessionLocal() as db:
        before = await intune.discrepancies(db)
    assert before["checked"] is False
    assert f"item:{not_in_intune.id}" not in _kinds(before)

    await _run(devices, t0)
    await _run(devices[:-1], t0 + timedelta(minutes=1))
    report = await _report()
    stored = await _devices()
    kinds = _kinds(report)
    assert report["checked"] is True
    assert kinds[f"device:{stored['dev-other'].id}"] == "inny_posiadacz"
    assert kinds[f"device:{stored['dev-unknown'].id}"] == "brak_w_ewidencji"
    assert kinds[f"device:{stored['dev-contract-other'].id}"] == "inny_posiadacz"
    assert kinds[f"device:{stored['dev-gone'].id}"] == "zniknal_z_intune"
    assert kinds[f"item:{not_in_intune.id}"] == "brak_w_intune"
    for quiet in ("dev-ok", "dev-contract-ok", "dev-no-mail", "dev-no-user"):
        assert f"device:{stored[quiet].id}" not in kinds, quiet
    # Laptop klienta, telefon i laptop na stanie nie są „brak w Intune”.
    for item in (client_laptop, phone, stock_laptop, gone_item):
        assert f"item:{item.id}" not in kinds
    assert report["counts"]["zgodne"] == 4
    assert report["counts"]["inny_posiadacz"] == 2
    assert report["counts"]["zniknal_z_intune"] == 1
    assert report["counts"]["brak_w_ewidencji"] == 1
    assert report["counts"]["brak_w_intune"] >= 1
    assert report["devices"] == 7

    row = next(
        r for r in report["rows"] if r["key"] == f"device:{stored['dev-other'].id}"
    )
    assert row["holder"] == {"kind": "user", "id": ewa.id, "name": ewa.name}
    assert row["item"]["id"] == other_item.id
    assert row["device"]["user"] == {"id": anna.id, "name": anna.name}
    order = [r["kind"] for r in report["rows"]]
    assert order == sorted(order, key=intune.KINDS.index)


async def test_resolution_removes_the_device_from_discrepancies(
    api, modules_on, people
) -> None:
    t0 = datetime.now(timezone.utc)
    await _run([_device("dev-r", serial=f"OBCY{_tag()}")], t0)
    device = (await _devices())["dev-r"]
    assert _kinds(await _report())[f"device:{device.id}"] == "brak_w_ewidencji"

    headers = _headers(people["reception"])
    leaked = await api.post(
        f"/api/equipment/intune/devices/{device.id}/resolve",
        json={"resolution": "wyjasnione", "note": "kontakt anna.przykladowa@gmail.com"},
        headers=headers,
    )
    assert leaked.status_code == 422
    assert "prywatny e-mail" in leaked.json()["detail"]
    bad = await api.post(
        f"/api/equipment/intune/devices/{device.id}/resolve",
        json={"resolution": "usuniete"},
        headers=headers,
    )
    assert bad.status_code == 422
    missing = await api.post(
        "/api/equipment/intune/devices/999999/resolve",
        json={"resolution": "pominiete"},
        headers=headers,
    )
    assert missing.status_code == 404

    done = await api.post(
        f"/api/equipment/intune/devices/{device.id}/resolve",
        json={"resolution": "pominiete", "note": "Urządzenie testowe działu IT"},
        headers=headers,
    )
    assert done.status_code == 200, done.text
    assert done.json()["resolution"] == "pominiete"
    report = await _report()
    assert f"device:{device.id}" not in _kinds(report)
    assert report["counts"]["wyjasnione"] == 1
    # Kolejny przebieg nie zdejmuje decyzji recepcji.
    await _run([_device("dev-r", serial="INNY")], t0 + timedelta(minutes=1))
    assert (await _devices())["dev-r"].resolution == "pominiete"


async def test_link_item_and_conflict_409(api, modules_on, people) -> None:
    tag = _tag()
    async with AsyncSessionLocal() as db:
        owner = await _user(db, "employee")
        taken = await _laptop(db, f"TESTINTTK{tag}")
        typo = await _laptop(db, f"TESTINTTY{tag}")
        await _issue(db, typo, user_id=owner.id)
        await db.commit()
    t0 = datetime.now(timezone.utc)
    await _run(
        [
            _device("dev-taken", serial=taken.serial_number),
            # S/N w rejestrze z literówką — urządzenie bez egzemplarza.
            _device("dev-typo", serial=f"TESTINTTV{tag}", upn=owner.email),
        ],
        t0,
    )
    stored = await _devices()
    headers = _headers(people["reception"])
    url = f"/api/equipment/intune/devices/{stored['dev-typo'].id}/link"

    conflict = await api.post(url, json={"item_id": taken.id}, headers=headers)
    assert conflict.status_code == 409
    assert "innym urządzeniem" in conflict.json()["detail"]
    nothing = await api.post(url, json={"item_id": 999999}, headers=headers)
    assert nothing.status_code == 404
    linked = await api.post(url, json={"item_id": typo.id}, headers=headers)
    assert linked.status_code == 200, linked.text
    assert linked.json()["item_id"] == typo.id

    kinds = _kinds(await _report())
    assert f"device:{stored['dev-typo'].id}" not in kinds
    assert f"item:{typo.id}" not in kinds
    # Nocny przebieg bez dopasowania po S/N zostawia powiązanie ręczne.
    await _run(
        [
            _device("dev-taken", serial=taken.serial_number),
            _device("dev-typo", serial=f"TESTINTTV{tag}", upn=owner.email),
        ],
        t0 + timedelta(minutes=1),
    )
    assert (await _devices())["dev-typo"].item_id == typo.id


# ── Trasy i bramki ───────────────────────────────────────────────────────────


async def test_gates_module_off_404_and_permission_403(
    api, modules_off, people
) -> None:
    for path in ("/status", "/discrepancies"):
        refused = await api.get(
            f"/api/equipment/intune{path}", headers=_headers(people["reception"])
        )
        assert refused.status_code == 404
        assert refused.json()["detail"] == "Ten moduł nie jest jeszcze włączony."
        admin = await api.get(
            f"/api/equipment/intune{path}", headers=_headers(people["admin"])
        )
        assert admin.status_code == 200


async def test_gates_with_module_on(api, modules_on, people, monkeypatch) -> None:
    monkeypatch.setattr(intune_graph, "current_mode", lambda: "simulate")
    for who in ("hr", "recruiter"):
        for path in ("/status", "/discrepancies"):
            response = await api.get(
                f"/api/equipment/intune{path}", headers=_headers(people[who])
            )
            assert response.status_code == 403, (who, path)
        resolve = await api.post(
            "/api/equipment/intune/devices/1/resolve",
            json={"resolution": "pominiete"},
            headers=_headers(people[who]),
        )
        assert resolve.status_code == 403
    status = await api.get(
        "/api/equipment/intune/status", headers=_headers(people["reception"])
    )
    assert status.status_code == 200
    assert status.json()["mode"] == "simulate"
    sync_by_reception = await api.post(
        "/api/equipment/intune/sync", headers=_headers(people["reception"])
    )
    assert sync_by_reception.status_code == 403
    assert (
        sync_by_reception.json()["detail"]
        == "Ręczny odczyt z Intune uruchamia administrator."
    )

    synced = await api.post(
        "/api/equipment/intune/sync", headers=_headers(people["admin"])
    )
    assert synced.status_code == 200, synced.text
    body = synced.json()
    assert body["status"] == "ok" and body["devices"] == 5
    assert body["error_text"] is None
    after = (
        await api.get(
            "/api/equipment/intune/discrepancies",
            headers=_headers(people["reception"]),
        )
    ).json()
    assert after["devices"] == 5 and after["checked"] is True


async def test_sync_when_mode_off_is_409(api, modules_on, people, monkeypatch) -> None:
    monkeypatch.setattr(intune_graph, "current_mode", lambda: "off")
    response = await api.post(
        "/api/equipment/intune/sync", headers=_headers(people["admin"])
    )
    assert response.status_code == 409
    assert "zgodę administratora" in response.json()["detail"]
    status = await api.get(
        "/api/equipment/intune/status", headers=_headers(people["reception"])
    )
    assert status.json()["mode"] == "off"
    assert status.json()["health"] == "disabled"


async def test_sync_while_another_run_holds_the_claim_is_409(
    api, modules_on, people, monkeypatch
) -> None:
    monkeypatch.setattr(intune_graph, "current_mode", lambda: "simulate")
    today = datetime.now(timezone.utc).astimezone(WARSAW).date().isoformat()
    async with AsyncSessionLocal() as db:
        db.add(HrJobRun(kind=intune.JOB_KIND, period_key=today, status="claimed"))
        await db.commit()
    response = await api.post(
        "/api/equipment/intune/sync", headers=_headers(people["admin"])
    )
    assert response.status_code == 409
    assert (
        response.json()["detail"] == "Odczyt z Intune właśnie trwa. Odśwież za chwilę."
    )


# ── Sonda health ─────────────────────────────────────────────────────────────


def test_health_verdict() -> None:
    now = datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc)
    fresh = EquipmentIntuneSyncState(id=1, last_success_at=now - timedelta(hours=2))
    stale = EquipmentIntuneSyncState(id=1, last_success_at=now - timedelta(hours=27))
    failed = EquipmentIntuneSyncState(
        id=1, last_success_at=now - timedelta(hours=2), last_error="forbidden (403)"
    )
    assert intune.health_verdict("off", fresh, now) == "disabled"
    assert intune.health_verdict("live", fresh, now) == "healthy"
    assert intune.health_verdict("live", stale, now) == "degraded"
    assert intune.health_verdict("live", failed, now) == "degraded"
    assert intune.health_verdict("simulate", None, now) == "degraded"
    assert intune.error_text("throttled (429)").startswith("Microsoft chwilowo")
    assert intune.error_text("internal: KeyError") == intune.DEFAULT_ERROR_TEXT
    assert intune.error_text(None) is None


# ── Klient live na fałszywym transporcie HTTP ────────────────────────────────


def _graph_client(handler, token: Optional[str] = "test-token"):
    from app.services.m365.app_graph_client import AppGraphClient

    def factory():
        client = AppGraphClient(token_provider=lambda *, force_refresh=False: token)
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return client

    return factory


async def test_live_client_pages_retries_and_selects_only_needed_fields(
    monkeypatch,
) -> None:
    from app.services.m365 import graph_client

    calls: list[httpx.Request] = []
    throttled = {"done": False}
    failed = {"done": False}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer test-token"
        if not throttled["done"]:
            throttled["done"] = True
            return httpx.Response(429, headers={"Retry-After": "7"}, json={})
        if "skiptoken" not in str(request.url):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "live-1",
                            "deviceName": "LAPTOP-LIVE-1",
                            "serialNumber": "TESTLIVE1",
                            "userPrincipalName": "anna.przykladowa@example.com",
                            # Graph mógłby oddać więcej — nie zapisujemy tego.
                            "phoneNumber": "+48500000000",
                            "imei": "000000000000000",
                            "lastSyncDateTime": "0001-01-01T00:00:00Z",
                        }
                    ],
                    "@odata.nextLink": (
                        "https://graph.microsoft.com/v1.0/deviceManagement/"
                        "managedDevices?$skiptoken=abc"
                    ),
                },
            )
        if not failed["done"]:
            failed["done"] = True
            return httpx.Response(502, json={"error": {"code": "BadGateway"}})
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "live-2",
                        "serialNumber": "TESTLIVE2",
                        "lastSyncDateTime": "2026-10-15T05:00:00Z",
                    }
                ]
            },
        )

    throttle_sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds: float) -> None:
        throttle_sleeps.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(graph_client.asyncio, "sleep", fake_sleep)
    retry_sleeps: list[float] = []

    async def record(seconds: float) -> None:
        retry_sleeps.append(seconds)

    source = intune_graph.GraphIntuneSource(
        client_factory=_graph_client(handler), sleep=record
    )
    devices = await source.list_devices()

    assert [d.intune_device_id for d in devices] == ["live-1", "live-2"]
    assert devices[0].last_sync_at is None
    assert devices[1].last_sync_at == datetime(2026, 10, 15, 5, 0, tzinfo=timezone.utc)
    assert set(vars(devices[0])) == {
        "intune_device_id",
        "device_name",
        "serial_number",
        "manufacturer",
        "model",
        "operating_system",
        "user_principal_name",
        "compliance_state",
        "last_sync_at",
    }
    assert throttle_sleeps == [7.0]
    assert retry_sleeps == [intune_graph.SERVER_ERROR_DELAYS[0]]
    first = calls[0]
    assert first.url.path == "/v1.0/deviceManagement/managedDevices"
    selected = first.url.params["$select"].split(",")
    assert selected == list(intune_graph.SELECT_FIELDS)
    for sensitive in ("bitLocker", "phoneNumber", "imei", "email", "recovery"):
        assert not any(sensitive.lower() in field.lower() for field in selected)
    # Druga strona idzie dokładnie pod ``nextLink`` (bez ponownego ``$select``).
    assert calls[-1].url.params.get("$skiptoken") == "abc"
    assert "$select" not in calls[-1].url.params


async def test_live_client_refuses_foreign_next_link_and_maps_errors() -> None:
    hosts: list[str] = []

    def foreign(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return httpx.Response(
            200,
            json={"value": [], "@odata.nextLink": "https://example.com/steal?x=1"},
        )

    source = intune_graph.GraphIntuneSource(client_factory=_graph_client(foreign))
    with pytest.raises(intune_graph.IntuneSourceError) as refused:
        await source.list_devices()
    assert refused.value.category == "bad_next_link"
    assert hosts == ["graph.microsoft.com"]

    def forbidden(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "anna@example.com"}})

    source = intune_graph.GraphIntuneSource(client_factory=_graph_client(forbidden))
    with pytest.raises(intune_graph.IntuneSourceError) as denied:
        await source.list_devices()
    assert denied.value.label == "forbidden (403)"
    assert "anna" not in denied.value.label

    source = intune_graph.GraphIntuneSource(
        client_factory=_graph_client(forbidden, token=None)
    )
    with pytest.raises(intune_graph.IntuneSourceError) as no_token:
        await source.list_devices()
    assert no_token.value.category == "auth"


async def test_simulated_source_is_deterministic_and_fictional() -> None:
    now = datetime(2026, 10, 16, 6, 0, tzinfo=timezone.utc)
    first = await intune_graph.SimulatedIntuneSource(now).list_devices()
    second = await intune_graph.SimulatedIntuneSource(now).list_devices()
    assert first == second and len(first) == 5
    for device in first:
        assert (
            device.user_principal_name is None
            or device.user_principal_name.endswith("@example.com")
        )
