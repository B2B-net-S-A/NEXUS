"""„Mój miesiąc” przez API: wpisy, limity, urlop, przejścia, PDF, uprawnienia.

Miesiąc testowy: marzec 2031 (bez świąt, 21 dni roboczych). Dane fikcyjne.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.models.hr_ops import HrAuditEvent
from app.models.hr_time import Timesheet, TimesheetEntry
from app.services.hr.time_hash import HashEntry, compute_timesheet_hash
from tests.test_hr_time_support import (  # noqa: F401 — fikstury
    add_leave,
    grant,
    headers,
    make_user,
    notifications_of,
    time_off,
    time_on,
)

Y, M = 2031, 3
BASE = f"/api/hr/time/me/{Y}/{M}"


def entry(day: int, hours: float, description: str = "Praca nad rekrutacjami", **extra):
    return {
        "work_date": date(Y, M, day).isoformat(),
        "hours": hours,
        "description": description,
        **extra,
    }


async def _team(**worker_profile):
    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "recruiter")
        worker = await make_user(
            db, "employee", manager_user_id=boss.id, **worker_profile
        )
        await db.commit()
    return boss, worker


# ── Bramki ────────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("time_off")
@pytest.mark.asyncio
async def test_switched_off_module_is_404_except_admin(app_client) -> None:
    async with AsyncSessionLocal() as db:
        worker = await make_user(db, "employee")
        admin = await make_user(db, "admin")
        await db.commit()
    denied = await app_client.get(BASE, headers=headers(worker))
    assert denied.status_code == 404
    assert denied.json()["detail"] == "Ten moduł nie jest jeszcze włączony."
    allowed = await app_client.get(BASE, headers=headers(admin))
    assert allowed.status_code == 200, allowed.text


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_recruiter_without_profile_is_refused(app_client) -> None:
    async with AsyncSessionLocal() as db:
        outsider = await make_user(db, "recruiter", profile=False)
        await db.commit()
    assert (await app_client.get(BASE, headers=headers(outsider))).status_code == 403
    queue = await app_client.get(
        f"/api/hr/time/team/{Y}/{M}", headers=headers(outsider)
    )
    assert queue.status_code == 403
    zip_ = await app_client.get(
        f"/api/hr/time/export/{Y}/{M}/zip", headers=headers(outsider)
    )
    assert zip_.status_code == 403


# ── Wpisy i limity ────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_day_limit_is_on_the_sum_and_overtime_needs_the_right(app_client) -> None:
    _, worker = await _team()
    h = headers(worker)
    first = await app_client.post(f"{BASE}/entries", json=entry(3, 6), headers=h)
    assert first.status_code == 201, first.text
    second = await app_client.post(f"{BASE}/entries", json=entry(3, 2), headers=h)
    assert second.status_code == 201
    over = await app_client.post(
        f"{BASE}/entries",
        json=entry(3, 1, overtime_reason="wdrożenie u klienta"),
        headers=h,
    )
    assert over.status_code == 403
    # Osoba na B2B (forma domyślna kartoteki): słowa bez „nadgodzin” (21.10.2026).
    assert "Godziny ponad 8 h" in over.json()["detail"]
    assert "nadgodzin" not in over.json()["detail"]
    outside = await app_client.post(
        f"{BASE}/entries",
        json={**entry(3, 1), "work_date": "2031-04-01"},
        headers=h,
    )
    assert outside.status_code == 422
    assert "nie należy do miesiąca" in outside.json()["detail"]
    empty = await app_client.post(f"{BASE}/entries", json=entry(4, 8, "   "), headers=h)
    assert empty.status_code == 422


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_overtime_with_right_requires_reason_and_caps_at_16(app_client) -> None:
    _, worker = await _team(can_log_overtime=True)
    h = headers(worker)
    assert (
        await app_client.post(f"{BASE}/entries", json=entry(4, 8), headers=h)
    ).status_code == 201
    no_reason = await app_client.post(
        f"{BASE}/entries", json=entry(4, 2, overtime_reason="abc"), headers=h
    )
    assert no_reason.status_code == 422
    # Osoba na B2B (forma domyślna): opis godzin ponad 8 h, bez „nadgodzin”.
    assert "czego dotyczyły godziny ponad 8 h" in no_reason.json()["detail"]
    ok = await app_client.post(
        f"{BASE}/entries",
        json=entry(4, 2, overtime_reason="Wdrożenie po godzinach"),
        headers=h,
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["is_overtime"] is True
    too_much = await app_client.post(
        f"{BASE}/entries",
        json=entry(4, 6.5, overtime_reason="Migracja danych"),
        headers=h,
    )
    assert too_much.status_code == 422
    assert "16 h" in too_much.json()["detail"]
    month = (await app_client.get(BASE, headers=h)).json()
    day = next(d for d in month["days"] if d["date"] == "2031-03-04")
    assert day["hours"] == 10
    assert day["overtime_hours"] == 2
    assert month["totals"]["overtime_hours"] == 2


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_lowering_the_day_clears_overtime_flags(app_client) -> None:
    _, worker = await _team(can_log_overtime=True)
    h = headers(worker)
    base_entry = await app_client.post(f"{BASE}/entries", json=entry(5, 8), headers=h)
    extra = await app_client.post(
        f"{BASE}/entries",
        json=entry(5, 2, overtime_reason="Dyżur wieczorny"),
        headers=h,
    )
    assert extra.json()["is_overtime"] is True
    removed = await app_client.delete(
        f"/api/hr/time/me/entries/{base_entry.json()['id']}", headers=h
    )
    assert removed.status_code == 204
    async with AsyncSessionLocal() as db:
        row = await db.get(TimesheetEntry, extra.json()["id"])
    assert row.is_overtime is False
    assert row.overtime_reason is None


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_text_only_edit_keeps_overtime_flags(app_client) -> None:
    # Audyt 19.10.2026: poprawka samego opisu w dniu z nadgodzinami dawała 422
    # (wpis 8 h bez uzasadnienia), a przełożonemu bez prawa do nadgodzin 403.
    boss, worker = await _team(can_log_overtime=True)
    h = headers(worker)
    base_entry = await app_client.post(f"{BASE}/entries", json=entry(6, 8), headers=h)
    extra = await app_client.post(
        f"{BASE}/entries",
        json=entry(6, 2, overtime_reason="Dyżur wieczorny"),
        headers=h,
    )
    assert extra.json()["is_overtime"] is True
    own = await app_client.patch(
        f"/api/hr/time/me/entries/{base_entry.json()['id']}",
        json={"description": "Praca nad rekrutacjami — poprawka"},
        headers=h,
    )
    assert own.status_code == 200, own.text
    assert own.json()["is_overtime"] is False
    by_boss = await app_client.patch(
        f"/api/hr/time/team/entries/{extra.json()['id']}",
        json={"description": "Dyżur — poprawka", "overtime_reason": "Dyżur wieczorny"},
        headers=headers(boss),
    )
    assert by_boss.status_code == 200, by_boss.text
    async with AsyncSessionLocal() as db:
        row = await db.get(TimesheetEntry, extra.json()["id"])
    assert row.is_overtime is True
    assert row.overtime_reason == "Dyżur wieczorny"
    assert row.overtime_by == worker.id


# ── Urlop ─────────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_leave_blocks_full_day_and_half_day_takes_four_hours(app_client) -> None:
    _, worker = await _team(employment_type="uop")
    async with AsyncSessionLocal() as db:
        await add_leave(db, worker.id, [date(Y, M, 10)])
        await add_leave(db, worker.id, [date(Y, M, 11)], status="pending")
        await add_leave(db, worker.id, [date(Y, M, 12)], fraction=0.5)
        await db.commit()
    h = headers(worker)
    full = await app_client.post(f"{BASE}/entries", json=entry(10, 2), headers=h)
    assert full.status_code == 422
    assert "dzień urlopu" in full.json()["detail"]
    pending = await app_client.post(f"{BASE}/entries", json=entry(11, 2), headers=h)
    assert pending.status_code == 422
    assert "czeka na decyzję" in pending.json()["detail"]
    half_over = await app_client.post(f"{BASE}/entries", json=entry(12, 5), headers=h)
    assert half_over.status_code == 422
    assert "pół dnia urlopu" in half_over.json()["detail"]
    half_ok = await app_client.post(f"{BASE}/entries", json=entry(12, 4), headers=h)
    assert half_ok.status_code == 201

    month = (await app_client.get(BASE, headers=h)).json()
    by_day = {d["date"]: d for d in month["days"]}
    assert by_day["2031-03-10"]["leave"]["label"] == "Urlop wypoczynkowy"
    assert by_day["2031-03-10"]["capacity"] is None
    assert by_day["2031-03-12"]["capacity"] == 4
    # Etat: urlop nie daje godzin (blokuje), nic nie wpisało się samo.
    assert by_day["2031-03-10"]["entries"] == []


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_contractor_paid_leave_becomes_standard_work_entry(app_client) -> None:
    _, worker = await _team(employment_type="b2b")
    async with AsyncSessionLocal() as db:
        await add_leave(db, worker.id, [date(Y, M, 17), date(Y, M, 18)])
        await add_leave(db, worker.id, [date(Y, M, 19)], fraction=0.5)
        await add_leave(db, worker.id, [date(Y, M, 20)], paid=False)
        await db.commit()
    h = headers(worker)
    assert (
        await app_client.post(f"{BASE}/entries", json=entry(3, 8), headers=h)
    ).status_code == 201
    month = (await app_client.get(BASE, headers=h)).json()
    by_day = {d["date"]: d for d in month["days"]}
    auto = by_day["2031-03-17"]["entries"]
    assert [(e["hours"], e["source"], e["description"]) for e in auto] == [
        (8.0, "leave_paid", "Realizacja usług zgodnie z umową")
    ]
    assert by_day["2031-03-19"]["entries"][0]["hours"] == 4.0
    assert by_day["2031-03-20"]["entries"] == []  # bezpłatny dzień blokuje
    assert month["totals"]["leave_paid_hours"] == 20

    blocked = await app_client.patch(
        f"/api/hr/time/me/entries/{auto[0]['id']}", json={"hours": 6}, headers=h
    )
    assert blocked.status_code == 409
    assert "płatnego urlopu" in blocked.json()["detail"]
    extra = await app_client.post(f"{BASE}/entries", json=entry(17, 1), headers=h)
    assert extra.status_code == 422  # pełny dzień urlopu, także płatnego
    assert by_day["2031-03-17"]["capacity"] is None
    # Druga połowa dnia z płatną połówką: 4 h wolnego miejsca.
    rest = await app_client.post(f"{BASE}/entries", json=entry(19, 4), headers=h)
    assert rest.status_code == 201
    over = await app_client.post(f"{BASE}/entries", json=entry(19, 1), headers=h)
    assert over.status_code == 403


# ── Przejścia ─────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_submit_approve_return_revoke_with_conditional_updates(
    app_client,
) -> None:
    boss, worker = await _team()
    async with AsyncSessionLocal() as db:
        payroll = await make_user(db, "finance", profile=False)
        await grant(db, payroll, "payroll")
        hr = await make_user(db, "recruiter", profile=False)
        await grant(db, hr, "people_admin")
        await db.commit()
    h = headers(worker)
    empty = await app_client.post(f"{BASE}/submit", headers=h)
    assert empty.status_code == 422
    await app_client.post(f"{BASE}/entries", json=entry(3, 8, "Sourcing"), headers=h)
    await app_client.post(
        f"{BASE}/entries", json=entry(4, 7.5, "Weryfikacje"), headers=h
    )
    sent = await app_client.post(f"{BASE}/submit", headers=h)
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "submitted"
    assert await notifications_of(boss.id, "hr_timesheet_submitted")
    again = await app_client.post(f"{BASE}/submit", headers=h)
    assert again.status_code == 409
    locked_edit = await app_client.post(f"{BASE}/entries", json=entry(5, 8), headers=h)
    assert locked_edit.status_code == 409

    ts_id = sent.json()["id"]
    self_approve = await app_client.post(
        f"/api/hr/time/timesheets/{ts_id}/approve", headers=h
    )
    assert self_approve.status_code == 403  # bramka: osoba bez zespołu
    no_note = await app_client.post(
        f"/api/hr/time/timesheets/{ts_id}/return",
        json={"note": "  "},
        headers=headers(boss),
    )
    assert no_note.status_code == 422
    returned = await app_client.post(
        f"/api/hr/time/timesheets/{ts_id}/return",
        json={"note": "Brakuje opisu 5 marca"},
        headers=headers(boss),
    )
    assert returned.status_code == 200
    assert returned.json()["status"] == "draft"
    assert returned.json()["return_note"] == "Brakuje opisu 5 marca"
    decided = await notifications_of(worker.id, "hr_timesheet_decided")
    # Słowa formy (D4): domyślna kartoteka to B2B — „Raport godzin”.
    assert decided[-1][0] == "Raport godzin zwrócony do poprawy"

    assert (await app_client.post(f"{BASE}/submit", headers=h)).status_code == 200
    approved = await app_client.post(
        f"/api/hr/time/timesheets/{ts_id}/approve", headers=headers(boss)
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "approved"
    expected = compute_timesheet_hash(
        [
            HashEntry("2031-03-03", 8, None, "Sourcing"),
            HashEntry("2031-03-04", 7.5, None, "Weryfikacje"),
        ]
    )
    assert body["pdf_hash"] == expected
    second = await app_client.post(
        f"/api/hr/time/timesheets/{ts_id}/approve", headers=headers(hr)
    )
    assert second.status_code == 409
    decided = await notifications_of(worker.id, "hr_timesheet_decided")
    assert decided[-1][0] == "Raport godzin potwierdzony"

    revoked = await app_client.post(
        f"/api/hr/time/timesheets/{ts_id}/revoke", headers=headers(boss)
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "submitted"
    assert revoked.json()["pdf_hash"] is None
    payroll_bell = await notifications_of(payroll.id, "hr_timesheet_decided")
    assert payroll_bell and "Cofnięto potwierdzenie" in payroll_bell[-1][0]
    assert "Anna Przykładowa" in payroll_bell[-1][1]


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_concurrent_approvals_have_one_winner(app_client) -> None:
    import asyncio

    boss, worker = await _team()
    async with AsyncSessionLocal() as db:
        hr = await make_user(db, "recruiter", profile=False)
        await grant(db, hr, "people_admin")
        await db.commit()
    h = headers(worker)
    await app_client.post(f"{BASE}/entries", json=entry(6, 8), headers=h)
    ts_id = (await app_client.post(f"{BASE}/submit", headers=h)).json()["id"]
    first, second = await asyncio.gather(
        app_client.post(
            f"/api/hr/time/timesheets/{ts_id}/approve", headers=headers(boss)
        ),
        app_client.post(
            f"/api/hr/time/timesheets/{ts_id}/approve", headers=headers(hr)
        ),
    )
    assert sorted([first.status_code, second.status_code]) == [200, 409]


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_payroll_locked_month_refuses_every_change(app_client) -> None:
    boss, worker = await _team()
    h = headers(worker)
    created = await app_client.post(f"{BASE}/entries", json=entry(7, 8), headers=h)
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE timesheets SET payroll_locked = true WHERE user_id = :u"),
            {"u": worker.id},
        )
        await db.commit()
    add = await app_client.post(f"{BASE}/entries", json=entry(10, 8), headers=h)
    assert add.status_code == 409
    assert "zamknięty w płacach" in add.json()["detail"]
    edit = await app_client.patch(
        f"/api/hr/time/me/entries/{created.json()['id']}", json={"hours": 7}, headers=h
    )
    assert edit.status_code == 409
    submit = await app_client.post(f"{BASE}/submit", headers=h)
    assert submit.status_code == 409
    fill = await app_client.post(f"{BASE}/fill", json={}, headers=h)
    assert fill.status_code == 409


# ── Zakres akceptującego ──────────────────────────────────────────────────────


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_manager_sees_and_decides_only_own_team(app_client) -> None:
    boss, worker = await _team()
    other_boss, stranger = await _team()
    h = headers(worker)
    await app_client.post(f"{BASE}/entries", json=entry(3, 8), headers=h)
    ts_id = (await app_client.post(f"{BASE}/submit", headers=h)).json()["id"]

    queue = await app_client.get(f"/api/hr/time/team/{Y}/{M}", headers=headers(boss))
    assert queue.status_code == 200
    items = {item["user_id"]: item for item in queue.json()["items"]}
    assert set(items) == {worker.id}
    assert items[worker.id]["status"] == "submitted"
    assert items[worker.id]["hours"] == 8
    # „8 / 168 h” w „Akceptacjach”: ta sama norma co w „Moim miesiącu” osoby.
    own = (await app_client.get(BASE, headers=h)).json()
    assert queue.json()["norm_hours"] == own["totals"]["norm_hours"] > 0

    other_queue = await app_client.get(
        f"/api/hr/time/team/{Y}/{M}", headers=headers(other_boss)
    )
    placeholders = {item["user_id"]: item for item in other_queue.json()["items"]}
    assert placeholders[stranger.id]["status"] == "missing"
    assert placeholders[stranger.id]["timesheet"] is None

    foreign = await app_client.post(
        f"/api/hr/time/timesheets/{ts_id}/approve", headers=headers(other_boss)
    )
    assert foreign.status_code == 404
    preview = await app_client.get(
        f"/api/hr/time/team/{worker.id}/{Y}/{M}", headers=headers(other_boss)
    )
    assert preview.status_code == 404
    own_preview = await app_client.get(
        f"/api/hr/time/team/{worker.id}/{Y}/{M}", headers=headers(boss)
    )
    assert own_preview.status_code == 200
    assert own_preview.json()["totals"]["work_hours"] == 8


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_approver_edits_submitted_entries_of_own_team(app_client) -> None:
    boss, worker = await _team()
    h = headers(worker)
    created = await app_client.post(f"{BASE}/entries", json=entry(3, 8), headers=h)
    await app_client.post(f"{BASE}/submit", headers=h)
    edited = await app_client.patch(
        f"/api/hr/time/team/entries/{created.json()['id']}",
        json={"hours": 6, "description": "Sourcing i weryfikacje"},
        headers=headers(boss),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["hours"] == 6
    over = await app_client.post(
        f"/api/hr/time/team/{worker.id}/{Y}/{M}/entries",
        json=entry(3, 4, overtime_reason="Dyżur po godzinach"),
        headers=headers(boss),
    )
    assert over.status_code == 403  # przełożony bez prawa do nadgodzin


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_people_admin_cannot_approve_own_timesheet(app_client) -> None:
    async with AsyncSessionLocal() as db:
        hr = await make_user(db, "recruiter")
        await grant(db, hr, "people_admin")
        await db.commit()
    h = headers(hr)
    await app_client.post(f"{BASE}/entries", json=entry(3, 8), headers=h)
    ts_id = (await app_client.post(f"{BASE}/submit", headers=h)).json()["id"]
    own = await app_client.post(f"/api/hr/time/timesheets/{ts_id}/approve", headers=h)
    assert own.status_code == 403
    assert "samemu" in own.json()["detail"]
    queue = await app_client.get(f"/api/hr/time/team/{Y}/{M}", headers=h)
    assert hr.id not in {item["user_id"] for item in queue.json()["items"]}


# ── PDF i ZIP ─────────────────────────────────────────────────────────────────


async def _approved(app_client, boss, worker) -> int:
    h = headers(worker)
    await app_client.post(
        f"{BASE}/entries", json=entry(3, 8, "Zażółć gęślą jaźń"), headers=h
    )
    ts_id = (await app_client.post(f"{BASE}/submit", headers=h)).json()["id"]
    approved = await app_client.post(
        f"/api/hr/time/timesheets/{ts_id}/approve", headers=headers(boss)
    )
    assert approved.status_code == 200
    return ts_id


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_pdf_after_approval_and_409_on_tampered_entries(app_client) -> None:
    boss, worker = await _team()
    h = headers(worker)
    draft_pdf = await app_client.get(f"{BASE}/pdf", headers=h)
    assert draft_pdf.status_code == 404
    ts_id = await _approved(app_client, boss, worker)
    pdf = await app_client.get(f"{BASE}/pdf", headers=h)
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    by_boss = await app_client.get(
        f"/api/hr/time/timesheets/{ts_id}/pdf", headers=headers(boss)
    )
    assert by_boss.status_code == 200

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE timesheet_entries SET hours = 7 WHERE timesheet_id = :id"),
            {"id": ts_id},
        )
        await db.commit()
    tampered = await app_client.get(f"{BASE}/pdf", headers=h)
    assert tampered.status_code == 409
    assert "sumą kontrolną" in tampered.json()["detail"]
    async with AsyncSessionLocal() as db:
        actions = list(
            await db.scalars(
                select(HrAuditEvent.action).where(
                    HrAuditEvent.entity_type == "timesheet",
                    HrAuditEvent.entity_id == str(ts_id),
                )
            )
        )
    assert "hash_mismatch" in actions


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_month_zip_for_payroll_only(app_client) -> None:
    boss, worker = await _team()
    await _approved(app_client, boss, worker)
    async with AsyncSessionLocal() as db:
        payroll = await make_user(db, "finance", profile=False)
        await grant(db, payroll, "payroll")
        await db.commit()
    refused = await app_client.get(
        f"/api/hr/time/export/{Y}/{M}/zip", headers=headers(boss)
    )
    assert refused.status_code == 403
    response = await app_client.get(
        f"/api/hr/time/export/{Y}/{M}/zip", headers=headers(payroll)
    )
    assert response.status_code == 200, response.text
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    slug = worker.name.lower().replace(" ", "-").replace("ł", "l")
    assert f"timesheet-{slug}-2031-03.pdf" in archive.namelist()


# ── Wypełnianie, obecność, podpowiedź ─────────────────────────────────────────


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_fill_month_skips_weekends_holidays_days_off_and_leave(
    app_client,
) -> None:
    _, worker = await _team(employment_type="uop")
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO company_days_off (day, name, kind) VALUES "
                "('2031-11-10', 'Dzień firmy (test)', 'company') "
                "ON CONFLICT (day) DO NOTHING"
            )
        )
        await add_leave(db, worker.id, [date(2031, 11, 12)])
        await add_leave(db, worker.id, [date(2031, 11, 13)], fraction=0.5)
        await add_leave(db, worker.id, [date(2031, 11, 14)], status="pending")
        await db.execute(
            text(
                "INSERT INTO timesheet_role_defaults (label, applies_to_role, "
                "default_description) VALUES ('Pracownik', 'employee', "
                "'Obsługa administracyjna biura')"
            )
        )
        await db.commit()
    h = headers(worker)
    try:
        manual = await app_client.post(
            "/api/hr/time/me/2031/11/entries",
            json={"work_date": "2031-11-03", "hours": 6, "description": "Szkolenie"},
            headers=h,
        )
        assert manual.status_code == 201
        filled = await app_client.post(
            "/api/hr/time/me/2031/11/fill", json={}, headers=h
        )
        assert filled.status_code == 200, filled.text
        body = filled.json()
        # 20 dni pn–pt − 11.11 − 10.11 (dzień firmy) = 18 roboczych.
        assert body["working_days"] == 18
        assert body["skipped_existing"] == 1
        assert body["skipped_leave"] == 2  # pełny dzień i oczekujący
        assert body["inserted"] == 15
        assert body["description"] == "Obsługa administracyjna biura"
        month = (await app_client.get("/api/hr/time/me/2031/11", headers=h)).json()
        by_day = {d["date"]: d for d in month["days"]}
        assert by_day["2031-11-13"]["hours"] == 4
        assert by_day["2031-11-11"]["holiday"] == "Narodowe Święto Niepodległości"
        assert by_day["2031-11-10"]["day_off"] == "Dzień firmy (test)"
        assert by_day["2031-11-08"]["entries"] == []
        weekend = await app_client.post(
            "/api/hr/time/me/2031/11/entries",
            json={"work_date": "2031-11-08", "hours": 3, "description": "Dyżur"},
            headers=h,
        )
        assert weekend.status_code == 201  # ręcznie wolno wpisać weekend
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("DELETE FROM company_days_off WHERE day = '2031-11-10'")
            )
            await db.execute(
                text(
                    "DELETE FROM timesheet_role_defaults "
                    "WHERE default_description = 'Obsługa administracyjna biura'"
                )
            )
            await db.commit()


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_copy_previous_approved_month_descriptions(app_client) -> None:
    boss, worker = await _team()
    h = headers(worker)
    await app_client.post(
        "/api/hr/time/me/2031/2/entries",
        json={
            "work_date": "2031-02-03",
            "hours": 8,
            "description": "Projekt Alfa: testy",
            "project": "Alfa",
        },
        headers=h,
    )
    ts_id = (await app_client.post("/api/hr/time/me/2031/2/submit", headers=h)).json()[
        "id"
    ]
    await app_client.post(
        f"/api/hr/time/timesheets/{ts_id}/approve", headers=headers(boss)
    )
    copied = await app_client.post(f"{BASE}/copy-previous", headers=h)
    assert copied.status_code == 200, copied.text
    assert copied.json()["source"] == {"year": 2031, "month": 2}
    assert copied.json()["inserted"] == 1
    month = (await app_client.get(BASE, headers=h)).json()
    day = next(d for d in month["days"] if d["date"] == "2031-03-03")
    assert day["entries"][0]["description"] == "Projekt Alfa: testy"
    assert day["entries"][0]["project"] == "Alfa"


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_attendance_stores_only_exceptions(app_client) -> None:
    _, worker = await _team(default_location="onsite")
    async with AsyncSessionLocal() as db:
        await add_leave(db, worker.id, [date(Y, M, 25)])
        await db.commit()
    h = headers(worker)
    remote = await app_client.put(
        "/api/hr/time/me/attendance/2031-03-24",
        json={"status": "active", "location": "remote"},
        headers=h,
    )
    assert remote.status_code == 200
    assert remote.json()["source"] == "exception"
    month = (await app_client.get(BASE, headers=h)).json()
    by_day = {d["date"]: d for d in month["days"]}
    assert by_day["2031-03-24"]["location"] == "remote"
    assert by_day["2031-03-24"]["location_source"] == "exception"
    assert by_day["2031-03-26"]["location"] == "onsite"
    assert by_day["2031-03-26"]["location_source"] == "default"
    assert by_day["2031-03-25"]["location"] is None

    back = await app_client.put(
        "/api/hr/time/me/attendance/2031-03-24",
        json={"status": "active", "location": "onsite"},
        headers=h,
    )
    assert back.json()["source"] == "default"
    async with AsyncSessionLocal() as db:
        left = await db.scalar(
            text("SELECT count(*) FROM attendance_days WHERE user_id = :u"),
            {"u": worker.id},
        )
    assert left == 0
    on_leave = await app_client.put(
        "/api/hr/time/me/attendance/2031-03-25",
        json={"status": "active", "location": "remote"},
        headers=h,
    )
    assert on_leave.status_code == 422


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_description_hint_counts_work_without_candidate_data(app_client) -> None:
    from datetime import datetime, timezone

    from app.models.call import Call, CallDirection, CallStatus
    from app.models.candidate import Candidate

    _, worker = await _team()
    async with AsyncSessionLocal() as db:
        candidate = Candidate(name="Zofia", lastname="Testowa")
        db.add(candidate)
        await db.flush()
        for _ in range(2):
            db.add(
                Call(
                    candidate_id=candidate.id,
                    user_id=worker.id,
                    direction=CallDirection.outbound,
                    status=CallStatus.completed,
                    started_at=datetime(2031, 3, 5, 9, 30, tzinfo=timezone.utc),
                )
            )
        await db.commit()
    hint = await app_client.get(
        "/api/hr/time/me/suggestion",
        params={"day": "2031-03-05"},
        headers=headers(worker),
    )
    assert hint.status_code == 200, hint.text
    body = hint.json()
    assert body["counts"]["calls"] == 2
    assert body["text"] == "2 rozmowy"
    assert "Zofia" not in str(body) and "Testowa" not in str(body)
    quiet = await app_client.get(
        "/api/hr/time/me/suggestion",
        params={"day": "2031-03-06"},
        headers=headers(worker),
    )
    assert quiet.json()["text"] is None


@pytest.mark.asyncio
async def test_timesheet_check_constraint_refuses_self_approval() -> None:
    from sqlalchemy.exc import IntegrityError

    async with AsyncSessionLocal() as db:
        worker = await make_user(db, "employee")
        db.add(
            Timesheet(
                user_id=worker.id,
                year=2031,
                month=1,
                status="approved",
                approved_by=worker.id,
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()
