"""Archiwum potwierdzeń godzin (art. 8c) idzie za formą z miesiąca dokumentu.

Przyjęte potwierdzenie godzin zlecenia po terminie wypłaty zostaje bez zmian
3 lata. ``time_retention`` brało formę z kartoteki w chwili żądania, więc po
zmianie formy osoby na B2B to samo potwierdzenie (dokument z czasu zlecenia)
dawało się cofnąć. Akceptacja zapisuje teraz formę w ``timesheets.employment_type``;
stare wiersze bez niej liczą się obecną formą. Dane fikcyjne.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.models.hr_profile import EmployeeProfile
from app.models.hr_time import Timesheet
from app.services.hr import time_retention
from tests.test_hr_time_support import headers, make_user, time_on  # noqa: F401

Y, M = 2025, 1  # termin wypłaty (28.02.2025) dawno minął, 3 lata jeszcze nie


async def _approved(app_client, person, boss) -> dict:
    base = f"/api/hr/time/me/{Y}/{M}"
    added = await app_client.post(
        f"{base}/entries",
        json={"work_date": f"{Y}-01-07", "hours": "8", "description": "Praca"},
        headers=headers(person),
    )
    assert added.status_code == 201, added.text
    sent = await app_client.post(f"{base}/submit", headers=headers(person))
    assert sent.status_code == 200, sent.text
    approved = await app_client.post(
        f"/api/hr/time/timesheets/{sent.json()['id']}/approve", headers=headers(boss)
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


async def _change_form(user_id: int, form: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(EmployeeProfile)
            .where(EmployeeProfile.user_id == user_id)
            .values(employment_type=form)
        )
        await db.commit()


async def _form_of(ts_id: int):
    async with AsyncSessionLocal() as db:
        return (await db.get(Timesheet, ts_id)).employment_type


@pytest.mark.asyncio
async def test_mandate_confirmation_stays_frozen_after_form_change(
    app_client,
    time_on,  # noqa: F811
) -> None:
    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "delivery_lead", employment_type="uop")
        person = await make_user(
            db, "employee", employment_type="zlecenie", manager_user_id=boss.id
        )
        await db.commit()
    sheet = await _approved(app_client, person, boss)
    assert await _form_of(sheet["id"]) == "zlecenie"

    await _change_form(person.id, "b2b")
    refused = await app_client.post(
        f"/api/hr/time/timesheets/{sheet['id']}/revoke", headers=headers(boss)
    )
    assert refused.status_code == 409, refused.text
    assert "art. 8c" in refused.json()["detail"]


@pytest.mark.asyncio
async def test_b2b_report_stays_revocable_after_change_to_mandate(
    app_client,
    time_on,  # noqa: F811
) -> None:
    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "delivery_lead", employment_type="uop")
        person = await make_user(
            db, "employee", employment_type="b2b", manager_user_id=boss.id
        )
        await db.commit()
    sheet = await _approved(app_client, person, boss)
    assert await _form_of(sheet["id"]) == "b2b"

    await _change_form(person.id, "zlecenie")
    revoked = await app_client.post(
        f"/api/hr/time/timesheets/{sheet['id']}/revoke", headers=headers(boss)
    )
    assert revoked.status_code == 200, revoked.text
    # Cofnięta akceptacja nie niesie już formy — zapisze ją kolejna akceptacja.
    assert await _form_of(sheet["id"]) is None


def test_sheet_without_saved_form_uses_current_form() -> None:
    old = Timesheet(user_id=1, year=Y, month=M, status="approved")
    assert time_retention.document_form(old, "zlecenie") == "zlecenie"
    saved = Timesheet(
        user_id=1, year=Y, month=M, status="approved", employment_type="zlecenie"
    )
    assert time_retention.document_form(saved, "b2b") == "zlecenie"
    assert time_retention.revoke_refusal(saved, current_form="b2b") is not None
    assert time_retention.delete_refusal(saved, current_form="b2b") is not None
    b2b = Timesheet(
        user_id=1, year=Y, month=M, status="approved", employment_type="b2b"
    )
    assert time_retention.revoke_refusal(b2b, current_form="zlecenie") is None


@pytest.mark.asyncio
async def test_timesheet_form_check_rejects_unknown_form() -> None:
    async with AsyncSessionLocal() as db:
        person = await make_user(db, "employee", employment_type="b2b")
        try:
            with pytest.raises(IntegrityError, match="ck_timesheets_employment_type"):
                await db.execute(
                    text(
                        "INSERT INTO timesheets (user_id, year, month, employment_type) "
                        "VALUES (:user_id, 2025, 2, 'etat')"
                    ),
                    {"user_id": person.id},
                )
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_pdf_of_mandate_confirmation_keeps_the_form_after_change(
    app_client,
    time_on,  # noqa: F811
) -> None:
    """PDF przyjętego potwierdzenia godzin zlecenia po zmianie formy osoby na
    B2B nadal jest „Potwierdzeniem godzin”, nie „Raportem godzin”."""

    from app.api import hr_time

    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "delivery_lead", employment_type="uop")
        person = await make_user(
            db, "employee", employment_type="zlecenie", manager_user_id=boss.id
        )
        await db.commit()
    sheet = await _approved(app_client, person, boss)
    await _change_form(person.id, "b2b")

    async with AsyncSessionLocal() as db:
        pdf, matches = await hr_time._pdf_sheet(
            db, await db.get(Timesheet, sheet["id"])
        )
    assert matches
    assert pdf.employment_type == "zlecenie"
