"""Import z Compassa z ekranu: na sucho → zapis → historia (``/api/hr/admin/import``).

Paczki są fikcyjne (repo publiczne): osoby „Osoba <znacznik>”, e-maile
``@example.com``, identyfikatory Compassa losowe. Testy idą przez API, więc
zapisują do bazy — każdy ma własne konta i własne identyfikatory.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, update

from app.api import hr_import
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.hr_leave import LeaveRequest
from app.models.hr_ops import HrAuditEvent, HrImportBatch, HrImportUpload
from app.models.hr_profile import EmployeeProfile
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from tests._route_introspection import iter_api_routes

BASE = "/api/hr/admin/import"


@pytest.fixture(autouse=True)
def _router_mounted():
    """Router rejestruje ``main.py`` — do tego czasu test montuje go sam."""
    from app.main import app

    if not any(path == f"{BASE}/batches" for path, _ in iter_api_routes(app)):
        app.include_router(hr_import.router, prefix=BASE)
    yield


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(db, role: str, *, grant: str | None = None, marker: str = "") -> User:
    marker = marker or uuid.uuid4().hex[:10]
    user = User(
        email=f"import-{marker}@example.com",
        name=f"Osoba {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    if grant:
        db.add(UserActionOverride(user_id=user.id, action=grant, access="manage"))
        await db.flush()
    return user


def _profile_row(marker: str, **values: Any) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "email": f"Import-{marker}@Example.com",
        "role": "internal",
        "is_external": False,
        "employment_type": "uop",
        "employment_status": "active",
        "default_location": "remote",
        "work_start_date": "2025-03-03",
        "hired_at": "2025-03-01",
        "termination_date": None,
        "job_title": "Rekruterka",
        "department": "Rekrutacja IT",
        "phone": None,
        "can_log_overtime": False,
        "leave_entitlement_days": 26,
        "leave_carried_over_days": "0",
        "leave_used_initial_days": "0",
        "manager_id": None,
        **values,
    }


def _leave_row(person: str) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "user_id": person,
        "leave_type": "vacation",
        "status": "approved",
        "start_date": "2026-05-04",
        "end_date": "2026-05-05",
        "half_day": None,
        "note": None,
        "substitute_id": None,
        "forward_mail_enabled": False,
        "created_by": person,
        "created_on_behalf": False,
        "decided_by": None,
        "decided_at": "2026-04-20T09:00:00+00:00",
        "paid_days": 2,
        "unpaid_days": 0,
        "source": None,
        "created_at": "2026-04-19T09:00:00+00:00",
    }


def _bundle_bytes(tables: dict[str, list[dict[str, Any]]]) -> bytes:
    return json.dumps(
        {
            "format": "compass-bundle",
            "version": 1,
            "exported_at": "2026-11-13T18:00:00+01:00",
            "tables": tables,
        }
    ).encode()


async def _dry_run(app_client, user: User, content: bytes, name="paczka.json"):
    return await app_client.post(
        f"{BASE}/dry-run",
        headers=_headers(user),
        files={"file": (name, content, "application/json")},
    )


async def _apply(app_client, user: User, upload: dict, modules=None, sha=None):
    return await app_client.post(
        f"{BASE}/{upload['id']}/apply",
        headers=_headers(user),
        json={
            "bundle_sha256": sha or upload["bundle_sha256"],
            "modules": modules or [m["module"] for m in upload["modules"]],
        },
    )


def _module(upload: dict, module: str) -> dict:
    return next(m for m in upload["modules"] if m["module"] == module)


async def _simple_bundle() -> tuple[bytes, User]:
    """Paczka z jedną osobą bez kartoteki (konto jest) — kartoteka do założenia."""
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        worker = await _user(db, "recruiter", marker=f"{tag}-w")
        await db.commit()
    return _bundle_bytes({"profiles": [_profile_row(f"{tag}-w")]}), worker


@pytest.mark.asyncio
async def test_role_without_permission_gets_403(app_client) -> None:
    async with AsyncSessionLocal() as db:
        recruiter = await _user(db, "recruiter")
        await db.commit()
    content, _ = await _simple_bundle()

    assert (await _dry_run(app_client, recruiter, content)).status_code == 403
    listed = await app_client.get(f"{BASE}/batches", headers=_headers(recruiter))
    assert listed.status_code == 403
    applied = await _apply(
        app_client,
        recruiter,
        {"id": 1, "bundle_sha256": "0" * 64, "modules": []},
        modules=["profiles"],
    )
    assert applied.status_code == 403


@pytest.mark.asyncio
async def test_people_admin_dry_runs_but_only_admin_applies(app_client) -> None:
    async with AsyncSessionLocal() as db:
        hr = await _user(db, "recruiter", grant="people_admin")
        admin = await _user(db, "admin")
        await db.commit()
    tag = uuid.uuid4().hex[:8]
    content = _bundle_bytes({"profiles": [_profile_row(f"{tag}-noaccount")]})

    dry = await _dry_run(app_client, hr, content)
    assert dry.status_code == 200, dry.text
    upload = dry.json()
    profiles = _module(upload, "profiles")
    assert profiles["counts"]["skip"] == 1
    # E-mail przy pozycji do wyjaśnienia widzi wyłącznie administrator.
    assert profiles["attention"][0]["reason"] == "brak konta w NEXUSIE"
    assert "email" not in profiles["attention"][0]

    denied = await _apply(app_client, hr, upload, modules=["profiles"])
    assert denied.status_code == 403
    listed = await app_client.get(f"{BASE}/batches", headers=_headers(hr))
    assert listed.status_code == 200
    assert any(row["id"] == upload["id"] for row in listed.json())

    as_admin = await _dry_run(app_client, admin, content)
    assert as_admin.status_code == 200
    item = _module(as_admin.json(), "profiles")["attention"][0]
    assert item["email"] == f"Import-{tag}-noaccount@Example.com"


@pytest.mark.asyncio
async def test_chain_dry_run_writes_nothing_apply_writes_and_repeat_is_unchanged(
    app_client,
) -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        admin = await _user(db, "admin")
        worker = await _user(db, "recruiter", marker=f"{tag}-w")
        await db.commit()
    person = _profile_row(f"{tag}-w")
    leave = _leave_row(person["id"])
    content = _bundle_bytes(
        {
            "profiles": [person, _profile_row(f"{tag}-noaccount")],
            "leave_requests": [leave],
        }
    )

    dry = await _dry_run(app_client, admin, content)
    assert dry.status_code == 200, dry.text
    upload = dry.json()
    assert upload["status"] == "dry_run"
    assert _module(upload, "profiles")["counts"]["create"] == 1
    assert _module(upload, "profiles")["counts"]["skip"] == 1
    # Łańcuch: urlop liczy się na kartotece, którą założy zapis kartotek.
    assert _module(upload, "leave")["counts"]["create"] == 1
    assert all(m["error"] is None for m in upload["modules"])

    async with AsyncSessionLocal() as db:
        # Na sucho nic nie zostaje: ani kartoteka, ani urlop, ani próbne partie.
        assert (
            await db.scalar(
                select(EmployeeProfile).where(EmployeeProfile.user_id == worker.id)
            )
        ) is None
        assert await db.get(LeaveRequest, uuid.UUID(leave["id"])) is None
        batches = await db.scalar(
            select(func.count())
            .select_from(HrImportBatch)
            .where(HrImportBatch.bundle_sha256 == upload["bundle_sha256"])
        )
        assert batches == len(upload["modules"])
        stored = await db.get(HrImportUpload, upload["id"])
        dumped = json.dumps(stored.report, ensure_ascii=False)
        assert "example.com" not in dumped.lower() and "Osoba" not in dumped

    # Urlopy bez kartotek, gdy paczka zakłada nowe kartoteki — odmowa.
    alone = await _apply(app_client, admin, upload, modules=["leave"])
    assert alone.status_code == 422
    assert "Najpierw kartoteki" in alone.json()["detail"]

    applied = await _apply(app_client, admin, upload, modules=["leave", "profiles"])
    assert applied.status_code == 200, applied.text
    result = applied.json()
    assert result["status"] == "applied"
    assert result["applied_modules"] == ["profiles", "leave"]
    assert _module(result, "profiles")["applied"]["written"]["profiles_created"] == 1
    assert _module(result, "leave")["applied"]["written"]["requests_created"] == 1

    async with AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == worker.id)
        )
        assert profile is not None and str(profile.compass_profile_id) == person["id"]
        assert await db.get(LeaveRequest, uuid.UUID(leave["id"])) is not None
        raw = await db.scalar(
            select(HrImportUpload.bundle).where(HrImportUpload.id == upload["id"])
        )
        assert raw is None  # po zapisie surowa paczka znika, zostają liczby i SHA
        event = await db.scalar(
            select(HrAuditEvent).where(
                HrAuditEvent.entity_type == "hr_import_upload",
                HrAuditEvent.entity_id == str(upload["id"]),
                HrAuditEvent.action == "compass_import_apply",
            )
        )
        assert event is not None and event.actor_user_id == admin.id

    again = await _apply(app_client, admin, upload, modules=["profiles"])
    assert again.status_code == 409

    # Ta sama paczka jeszcze raz: same „bez zmian”, zapis niczego nie zmienia.
    second = await _dry_run(app_client, admin, content)
    assert second.status_code == 200
    repeat = second.json()
    assert repeat["bundle_sha256"] == upload["bundle_sha256"]
    assert _module(repeat, "profiles")["counts"]["create"] == 0
    assert _module(repeat, "profiles")["counts"]["unchanged"] == 1
    assert _module(repeat, "leave")["counts"]["unchanged"] == 1
    reapplied = await _apply(app_client, admin, repeat, modules=["profiles", "leave"])
    assert reapplied.status_code == 200
    for module in reapplied.json()["modules"]:
        if module["applied"] is not None:
            assert not any(module["applied"]["written"].values()), module

    listed = await app_client.get(f"{BASE}/batches", headers=_headers(admin))
    rows = {row["id"]: row for row in listed.json()}
    assert rows[upload["id"]]["status"] == "applied"
    assert rows[upload["id"]]["applied_by_name"] == admin.name
    assert "attention" not in _module(rows[upload["id"]], "profiles")


@pytest.mark.asyncio
async def test_wrong_sha_expired_and_superseded_are_409(app_client) -> None:
    async with AsyncSessionLocal() as db:
        admin = await _user(db, "admin")
        await db.commit()
    content, _ = await _simple_bundle()
    first = (await _dry_run(app_client, admin, content)).json()

    wrong = await _apply(app_client, admin, first, modules=["profiles"], sha="a" * 64)
    assert wrong.status_code == 409
    assert "SHA-256" in wrong.json()["detail"]

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(HrImportUpload)
            .where(HrImportUpload.id == first["id"])
            .values(expires_at=func.now() - timedelta(minutes=1))
        )
        await db.commit()
    expired = await _apply(app_client, admin, first, modules=["profiles"])
    assert expired.status_code == 409
    assert "wygasło" in expired.json()["detail"]
    async with AsyncSessionLocal() as db:
        row = await db.get(HrImportUpload, first["id"])
        assert row.status == "expired"
        raw = await db.scalar(
            select(HrImportUpload.bundle).where(HrImportUpload.id == first["id"])
        )
        assert raw is None

    # Dwie paczki sprawdzone na sucho; zapis jednej unieważnia drugą.
    other_content, _ = await _simple_bundle()
    older = (await _dry_run(app_client, admin, content)).json()
    newer = (await _dry_run(app_client, admin, other_content)).json()
    assert (await _apply(app_client, admin, newer)).status_code == 200
    stale = await _apply(app_client, admin, older)
    assert stale.status_code == 409
    assert "inną paczkę" in stale.json()["detail"]


@pytest.mark.asyncio
async def test_too_large_file_is_413(app_client, monkeypatch) -> None:
    async with AsyncSessionLocal() as db:
        admin = await _user(db, "admin")
        await db.commit()
    monkeypatch.setattr(hr_import, "MAX_UPLOAD_BYTES", 1024)
    content = _bundle_bytes({"profiles": [_profile_row("x" * 8) for _ in range(20)]})
    assert len(content) > 1024
    response = await _dry_run(app_client, admin, content)
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_zip_bundle_works_and_zip_bomb_is_rejected(app_client) -> None:
    async with AsyncSessionLocal() as db:
        admin = await _user(db, "admin")
        before = await db.scalar(select(func.count()).select_from(HrImportUpload))
        await db.commit()

    # Bomba: 65 MB zer schodzi do kilkudziesięciu KB — odmowa po nagłówku,
    # zanim cokolwiek zostanie rozpakowane.
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive:
        with archive.open("paczka.json", "w", force_zip64=True) as handle:
            chunk = b"\0" * (1024 * 1024)
            for _ in range(hr_import.MAX_UNPACKED_BYTES // len(chunk) + 1):
                handle.write(chunk)
    assert len(bomb.getvalue()) < 1024 * 1024
    response = await _dry_run(app_client, admin, bomb.getvalue(), name="paczka.zip")
    assert response.status_code == 413

    two = io.BytesIO()
    with zipfile.ZipFile(two, "w") as archive:
        archive.writestr("a.json", "{}")
        archive.writestr("b.json", "{}")
    response = await _dry_run(app_client, admin, two.getvalue(), name="paczka.zip")
    assert response.status_code == 422

    not_json = await _dry_run(app_client, admin, b"to nie jest json")
    assert not_json.status_code == 422

    async with AsyncSessionLocal() as db:
        after = await db.scalar(select(func.count()).select_from(HrImportUpload))
    assert after == before

    content, _ = await _simple_bundle()
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("__MACOSX/._paczka.json", b"\0\1")
        archive.writestr("eksport/paczka.json", content)
    response = await _dry_run(app_client, admin, packed.getvalue(), name="paczka.zip")
    assert response.status_code == 200, response.text
    assert _module(response.json(), "profiles")["counts"]["create"] == 1
