"""„Przekaż do front office” (D15) — ``/api/care/contracts/{id}/front-office``.

Zakres: pasujące rekrutacje z silnika „Pasuje też do” (podmieniony — Qdrant
w testach nie działa) i stan „nie udało się sprawdzić”; przekazanie zostawia
ślad (zdarzenie w śladzie HR, wpis „Do przepięcia” w toku), powiadamia front
office własnym typem ``care_front_office_handoff`` (head pionu front office,
Head of Recruitment, Delivery Leadzi rekrutacji i klienta — także bez sekcji
Delivery) i trafia na oś i listę „Ten tydzień”; odmowy: konsultant bez końca
projektu i bez „chce zmiany” (409), zamknięta rekrutacja (422), Finanse bez
zapisu i rola bez sekcji Delivery (403).

Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.contract_care import RedeployQueueItem
from app.models.hr_ops import HrAuditEvent
from app.models.job import Job, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.user import UserRole
from app.services import also_fits
from app.services.care.front_office import HANDOFF_ACTION
from app.services.hr_foundation_schema import HR_DIVISIONS_SETTING, HR_MODULE_KEYS
from tests.test_care_api import (
    _previous_modules,
    headers,
    make_client,
    make_contract,
    make_user,
    set_modules,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def care_on():
    previous = await _previous_modules()
    await set_modules({key: True for key in HR_MODULE_KEYS})
    yield
    await set_modules(previous or {key: False for key in HR_MODULE_KEYS})


async def make_job(client_id: int, lead_id: int, *, closed: bool = False) -> int:
    async with AsyncSessionLocal() as db:
        job = Job(
            title="QA Automation (przykład)",
            status=JobStatus.closed if closed else JobStatus.published,
            client_id=client_id,
            delivery_lead_id=lead_id,
            work_state="finished" if closed else "searching",
        )
        db.add(job)
        await db.commit()
        return job.id


def fake_matches(monkeypatch, *, job_ids: list[int], status: str = "ok") -> list:
    calls: list = []

    async def fake(db, *, candidate, from_job_id, profile_user_id, scope_clause=None):
        calls.append((candidate.id, from_job_id))
        return also_fits.AlsoFitsResult(
            status=status,
            jobs=tuple(
                also_fits.AlsoFitsJob(
                    job_id=job_id,
                    title="QA Automation (przykład)",
                    client_name="Telekom Przykładowy",
                    score=82,
                    matching_must=("Playwright",),
                )
                for job_id in job_ids
            ),
        )

    monkeypatch.setattr(also_fits, "also_fits_for_candidate", fake)
    return calls


async def test_handoff_leaves_trace_and_notifies_front_office(
    app_client, care_on, monkeypatch
) -> None:
    tcm = await make_user(UserRole.talent_community_manager)
    dl = await make_user(UserRole.delivery_lead)
    job_dl = await make_user(UserRole.delivery_lead)
    hor = await make_user(UserRole.head_of_recruitment)
    client_id = await make_client(dl=dl)
    other_client = await make_client(dl=job_dl)
    contract_id, candidate_id = await make_contract(
        client_id, started_days_ago=200, end_in_days=25
    )
    job_id = await make_job(other_client, job_dl.id)
    calls = fake_matches(monkeypatch, job_ids=[job_id])
    url = f"/api/care/contracts/{contract_id}/front-office"

    overview = await app_client.get(url, headers=headers(tcm))
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert body["eligible"] is True and body["reasons"] == ["project_end"]
    assert body["status"] == "ok"
    assert [job["job_id"] for job in body["jobs"]] == [job_id]
    assert body["jobs"][0]["score"] == 82
    assert body["handoffs"] == []
    assert calls == [(candidate_id, 0)]

    sent = await app_client.post(url, headers=headers(tcm), json={"job_ids": [job_id]})
    assert sent.status_code == 201, sent.text
    result = sent.json()
    recipients = {person["id"] for person in result["recipients"]}
    notified = {person["id"] for person in result["notified"]}
    assert {dl.id, job_dl.id, hor.id} <= recipients
    assert tcm.id not in recipients
    # Własny typ przekazania nie zależy od sekcji Delivery: Head of Recruitment
    # (domyślnie bez niej) dostaje je tak samo jak Delivery Leadzi.
    assert {dl.id, job_dl.id, hor.id} <= notified

    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(Notification).where(
                    Notification.related_entity_type == "care_front_office",
                    Notification.related_entity_id == contract_id,
                )
            )
        ).all()
        assert {row.user_id for row in rows} == notified
        assert all(
            row.notification_type == NotificationType.care_front_office_handoff
            for row in rows
        )
        # Front office nie ma ekranu opieki — link prowadzi do profilu osoby.
        assert all(row.link == f"/candidates/{candidate_id}" for row in rows)
        assert "„QA Automation (przykład)”" in rows[0].message
        trace = (
            await db.scalars(
                select(HrAuditEvent).where(
                    HrAuditEvent.entity_type == "contract",
                    HrAuditEvent.entity_id == str(contract_id),
                    HrAuditEvent.action == HANDOFF_ACTION,
                )
            )
        ).all()
        assert len(trace) == 1
        assert trace[0].actor_user_id == tcm.id
        assert trace[0].details["job_ids"] == [job_id]
        item = await db.get(RedeployQueueItem, result["redeploy_item_id"])
        assert item is not None
        assert (item.reason, item.status) == ("project_end", "in_progress")

    timeline = await app_client.get(
        f"/api/care/contracts/{contract_id}/timeline", headers=headers(tcm)
    )
    handoff = next(e for e in timeline.json()["events"] if e["kind"] == "handoff")
    assert handoff["title"] == "Przekazano do front office"
    again = await app_client.get(url, headers=headers(tcm))
    assert len(again.json()["handoffs"]) == 1
    assert again.json()["handoffs"][0]["job_ids"] == [job_id]


@pytest_asyncio.fixture
async def front_office_head():
    """Head pionu front office w ``app_settings['hr_divisions']`` (przywracany)."""

    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_DIVISIONS_SETTING)
        previous = dict(row.value) if row is not None else None
    head = await make_user(UserRole.recruiter)

    async def set_heads(value):
        async with AsyncSessionLocal() as db:
            row = await db.get(AppSetting, HR_DIVISIONS_SETTING)
            if row is None:
                db.add(AppSetting(key=HR_DIVISIONS_SETTING, value=value))
            else:
                row.value = value
            await db.commit()

    await set_heads({"front_office": head.id, "back_office": None})
    yield head
    await set_heads(previous or {"front_office": None, "back_office": None})


async def test_handoff_reaches_front_office_head_without_delivery_section(
    app_client, care_on, monkeypatch, front_office_head
) -> None:
    tcm = await make_user(UserRole.talent_community_manager)
    client_id = await make_client(dl=await make_user(UserRole.delivery_lead))
    contract_id, candidate_id = await make_contract(
        client_id, started_days_ago=200, end_in_days=20
    )
    fake_matches(monkeypatch, job_ids=[])

    sent = await app_client.post(
        f"/api/care/contracts/{contract_id}/front-office",
        headers=headers(tcm),
        json={"job_ids": []},
    )
    assert sent.status_code == 201, sent.text
    assert front_office_head.id in {p["id"] for p in sent.json()["notified"]}
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(Notification).where(
                Notification.user_id == front_office_head.id,
                Notification.related_entity_type == "care_front_office",
                Notification.related_entity_id == contract_id,
            )
        )
    assert row is not None
    assert row.notification_type == NotificationType.care_front_office_handoff
    assert row.link == f"/candidates/{candidate_id}"
    # Head pionu bez sekcji Delivery widzi je w swoich powiadomieniach.
    listing = await app_client.get(
        "/api/notifications", headers=headers(front_office_head)
    )
    assert listing.status_code == 200, listing.text
    assert row.id in {item["id"] for item in listing.json()["items"]}
    # Temat „Rekrutacje”: pozycja po linku profilu, sprawa imienna (dymek).
    threads = await app_client.get(
        "/api/notifications/jobs", headers=headers(front_office_head)
    )
    assert threads.status_code == 200, threads.text
    thread = next(i for i in threads.json()["items"] if i["link"] == row.link)
    assert thread["has_task"] is True


async def test_handoff_refusals(app_client, care_on, monkeypatch) -> None:
    tcm = await make_user(UserRole.talent_community_manager)
    finance = await make_user(UserRole.finance)
    recruiter = await make_user(UserRole.recruiter)
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    staying, _ = await make_contract(client_id, started_days_ago=100)
    ending, _ = await make_contract(client_id, started_days_ago=100, end_in_days=10)
    closed_job = await make_job(client_id, dl.id, closed=True)
    open_job = await make_job(client_id, dl.id)
    fake_matches(monkeypatch, job_ids=[])

    # Bez końca projektu i bez „chce zmiany”: nie ma czego przekazywać.
    calm = await app_client.get(
        f"/api/care/contracts/{staying}/front-office", headers=headers(tcm)
    )
    assert calm.status_code == 200, calm.text
    assert calm.json()["eligible"] is False and calm.json()["jobs"] == []
    refused = await app_client.post(
        f"/api/care/contracts/{staying}/front-office",
        headers=headers(tcm),
        json={"job_ids": []},
    )
    assert refused.status_code == 409
    assert "60 dni" in refused.json()["detail"]

    url = f"/api/care/contracts/{ending}/front-office"
    gone = await app_client.post(
        url, headers=headers(tcm), json={"job_ids": [closed_job]}
    )
    assert gone.status_code == 422
    too_many = await app_client.post(
        url, headers=headers(tcm), json={"job_ids": [open_job, 1, 2, 3, 4, 5]}
    )
    assert too_many.status_code == 422
    read_only = await app_client.post(
        url, headers=headers(finance), json={"job_ids": []}
    )
    assert read_only.status_code == 403
    blocked = await app_client.get(url, headers=headers(recruiter))
    assert blocked.status_code == 403

    # Bez pasujących rekrutacji przekazanie też zostawia ślad (DL klienta).
    plain = await app_client.post(url, headers=headers(tcm), json={"job_ids": []})
    assert plain.status_code == 201, plain.text
    assert dl.id in {person["id"] for person in plain.json()["notified"]}


async def test_unavailable_vector_search_is_not_an_empty_match(
    app_client, care_on, monkeypatch
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    contract_id, _ = await make_contract(client_id, end_in_days=30)
    fake_matches(monkeypatch, job_ids=[], status="unavailable")
    response = await app_client.get(
        f"/api/care/contracts/{contract_id}/front-office", headers=headers(dl)
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "unavailable"
    assert response.json()["can_edit"] is True
