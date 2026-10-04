"""Negocjacja i decyzja DL przy zmianie stawki kandydata (0418, D3 i D6).

* negocjację zleca DL rekrutacji albo Head of Recruitment, nie rekruter,
* wynik zapisuje osoba negocjująca (albo DL/HoR); niższa stawka trafia na
  wiersz etapu, a zejście do stawki sprzed zmiany zamyka sprawę samo,
* o stawce do klienta decyduje WYŁĄCZNIE DL rekrutacji albo admin; „podnoszę”
  zapisuje stawkę do klienta z wpisem audytu,
* „Czeka na Ciebie” pokazuje sprawę właściwym osobom,
* przypomnienie raz dziennie.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.candidate_rate_change import CandidateRateChange
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from tests.test_candidate_rate_change import URL, _body, _notes, _pair


async def _open_case(app_client: AsyncClient, client_rate: str | None = "150") -> dict:
    p = await _pair(
        PipelineStage.cv_sent,
        client_rate=Decimal(client_rate) if client_rate else None,
    )
    res = await app_client.post(URL, headers=p["rec_h"], json=_body(p, "130"))
    assert res.status_code == 200, res.text
    p["change_id"] = res.json()["change"]["id"]
    assert res.json()["change"]["status"] == "requested"
    return p


async def _stage_rate(p: dict) -> tuple[Decimal | None, Decimal | None]:
    async with AsyncSessionLocal() as db:
        stage = await db.scalar(
            select(CandidateStage)
            .where(
                CandidateStage.candidate_id == p["cand_id"],
                CandidateStage.job_id == p["job_id"],
            )
            .order_by(CandidateStage.id.desc())
            .limit(1)
        )
        return stage.expected_rate_value, stage.client_rate_value


async def test_recruiter_cannot_order_negotiation_hor_can(app_client: AsyncClient):
    p = await _open_case(app_client)
    url = f"{URL}/{p['change_id']}/negotiation"
    denied = await app_client.post(
        url, headers=p["rec_h"], json={"negotiator_id": p["dl_id"]}
    )
    assert denied.status_code == 403, denied.text

    ok = await app_client.post(
        url,
        headers=p["hor_h"],
        json={
            "negotiator_id": p["dl_id"],
            "target_hourly": "120",
            "due": business_today().isoformat(),
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "negotiating"
    notes = await _notes(p["change_id"])
    assert notes[p["dl_id"]].notification_type == NotificationType.candidate_rate_change_task


async def test_negotiated_lower_rate_lands_on_stage_and_waits_for_dl(
    app_client: AsyncClient,
):
    p = await _open_case(app_client)
    await app_client.post(
        f"{URL}/{p['change_id']}/negotiation",
        headers=p["dl_h"],
        json={"negotiator_id": p["rec_id"]},
    )
    # Rekruter-negocjator zapisuje wynik.
    out = await app_client.post(
        f"{URL}/{p['change_id']}/outcome",
        headers=p["rec_h"],
        json={"outcome": "lower", "agreed_amount": "120", "note": "zszedł do 120"},
    )
    assert out.status_code == 200, out.text
    assert out.json()["status"] == "agreed"
    assert out.json()["agreed"]["label"] == "120 zł/h"
    expected, _client = await _stage_rate(p)
    assert expected == Decimal("120")

    # Wyższa niż zgłoszona to nie „niższa”.
    view = await app_client.get(
        URL,
        headers=p["dl_h"],
        params={"candidate_id": p["cand_id"], "job_id": p["job_id"]},
    )
    assert view.json()["can_decide"] is True
    assert view.json()["can_manage"] is True

    hor_decide = await app_client.post(
        f"{URL}/{p['change_id']}/decision",
        headers=p["hor_h"],
        json={"decision": "keep_client"},
    )
    assert hor_decide.status_code == 403, hor_decide.text
    rec_decide = await app_client.post(
        f"{URL}/{p['change_id']}/decision",
        headers=p["rec_h"],
        json={"decision": "keep_client"},
    )
    assert rec_decide.status_code == 403

    dl_decide = await app_client.post(
        f"{URL}/{p['change_id']}/decision",
        headers=p["dl_h"],
        json={"decision": "keep_client"},
    )
    assert dl_decide.status_code == 200, dl_decide.text
    assert dl_decide.json()["status"] == "closed"
    assert dl_decide.json()["decision"] == "keep_client"
    again = await app_client.post(
        f"{URL}/{p['change_id']}/decision",
        headers=p["dl_h"],
        json={"decision": "keep_client"},
    )
    assert again.status_code == 409


async def test_outcome_must_be_lower_than_requested(app_client: AsyncClient):
    p = await _open_case(app_client)
    res = await app_client.post(
        f"{URL}/{p['change_id']}/outcome",
        headers=p["dl_h"],
        json={"outcome": "lower", "agreed_amount": "135"},
    )
    assert res.status_code == 422


async def test_back_to_previous_rate_closes_the_case_by_itself(app_client: AsyncClient):
    p = await _open_case(app_client)
    res = await app_client.post(
        f"{URL}/{p['change_id']}/outcome",
        headers=p["dl_h"],
        json={"outcome": "lower", "agreed_amount": "110"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "closed"
    assert res.json()["decision"] == "auto"


async def test_raise_client_writes_client_rate_with_audit(app_client: AsyncClient):
    p = await _open_case(app_client)
    res = await app_client.post(
        f"{URL}/{p['change_id']}/decision",
        headers=p["dl_h"],
        json={"decision": "raise_client", "client_rate": {"amount": "170"}},
    )
    assert res.status_code == 200, res.text
    _expected, client = await _stage_rate(p)
    assert client == Decimal("170")
    async with AsyncSessionLocal() as db:
        audit = await db.scalar(
            select(Activity).where(
                Activity.entity_id == p["cand_id"],
                Activity.action == "client_rate_changed",
            )
        )
        decided = await db.scalar(
            select(Activity).where(
                Activity.entity_id == p["cand_id"],
                Activity.action == "candidate_rate_change_decided",
            )
        )
    assert audit is not None and audit.details["rate_change_id"] == p["change_id"]
    # Oś czasu kandydata jest jawna — decyzja nie niesie stawki do klienta.
    assert "170" not in str(decided.details)

    missing = await _open_case(app_client)
    bad = await app_client.post(
        f"{URL}/{missing['change_id']}/decision",
        headers=missing["dl_h"],
        json={"decision": "raise_client"},
    )
    assert bad.status_code == 422


async def test_withdrew_closes_with_withdraw_decision(app_client: AsyncClient):
    p = await _open_case(app_client)
    res = await app_client.post(
        f"{URL}/{p['change_id']}/outcome",
        headers=p["dl_h"],
        json={"outcome": "withdrew"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "closed"
    assert res.json()["decision"] == "withdraw"


async def test_board_tasks_route_cases_to_the_right_people(app_client: AsyncClient):
    p = await _open_case(app_client)

    def ids(body: dict, key: str) -> set[int]:
        return {row["change_id"] for row in body[key]}

    as_dl = (await app_client.get("/api/board-tasks", headers=p["dl_h"])).json()
    assert p["change_id"] in ids(as_dl, "rate_changes")
    as_rec = (await app_client.get("/api/board-tasks", headers=p["rec_h"])).json()
    assert p["change_id"] in ids(as_rec, "rate_changes_by_others")
    assert p["change_id"] not in ids(as_rec, "rate_changes")
    # HoR widzi sprawę dopiero po 2 dniach roboczych czekania.
    as_hor = (await app_client.get("/api/board-tasks", headers=p["hor_h"])).json()
    assert p["change_id"] not in ids(as_hor, "rate_changes_by_others")

    await app_client.post(
        f"{URL}/{p['change_id']}/negotiation",
        headers=p["dl_h"],
        json={"negotiator_id": p["hor_id"]},
    )
    as_hor = (await app_client.get("/api/board-tasks", headers=p["hor_h"])).json()
    row = next(r for r in as_hor["rate_changes"] if r["change_id"] == p["change_id"])
    assert row["reason"] == "negotiate"
    as_dl = (await app_client.get("/api/board-tasks", headers=p["dl_h"])).json()
    assert p["change_id"] not in ids(as_dl, "rate_changes")


async def test_reminders_once_a_day_for_waiting_decision():
    from app.services import candidate_rate_change as svc

    # Poza oknem 8–17 nic się nie dzieje.
    async with AsyncSessionLocal() as db:
        night = datetime(2026, 10, 7, 2, 0, tzinfo=timezone.utc)
        assert await svc.send_reminders(db, night) == 0


async def test_reminder_reaches_dl_next_business_day(app_client: AsyncClient):
    from app.services import candidate_rate_change as svc

    p = await _open_case(app_client)
    # Środa 07.10.2026, 10:00 czasu firmy; sprawa czeka od wtorku.
    now = datetime(2026, 10, 7, 8, 0, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as db:
        change = await db.get(CandidateRateChange, p["change_id"])
        change.updated_at = now - timedelta(days=1)
        change.created_at = now - timedelta(days=1)
        # Dzwonek z chwili zgłoszenia jest z dziś — dedup dzienny `emit`
        # zjadłby przypomnienie w tym samym dniu bazy.
        for note in (
            await db.scalars(
                select(Notification).where(
                    Notification.related_entity_type == "candidate_rate_change",
                    Notification.related_entity_id == p["change_id"],
                )
            )
        ).all():
            await db.delete(note)
        await db.commit()
    svc._REMINDERS_DONE_FOR = None
    async with AsyncSessionLocal() as db:
        await svc.send_reminders(db, now)
        await db.commit()
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(Notification).where(
                    Notification.related_entity_id == p["change_id"],
                    Notification.related_entity_type == "candidate_rate_change",
                    Notification.user_id == p["dl_id"],
                    Notification.title.like("Przypomnienie%"),
                )
            )
        ).all()
    assert len(rows) == 1
    # Drugi bieg tego samego dnia nic nie dokłada.
    async with AsyncSessionLocal() as db:
        assert await svc.send_reminders(db, now) == 0
    svc._REMINDERS_DONE_FOR = None


async def test_noted_entry_cannot_be_negotiated(app_client: AsyncClient):
    """Przegląd PR3: stary wpis „noted” nie wchodzi w negocjację (nadpisałby
    nowszą stawkę albo trafił na unikalny indeks otwartej sprawy)."""

    p = await _pair(PipelineStage.verified)
    noted = await app_client.post(URL, headers=p["rec_h"], json=_body(p, "130"))
    assert noted.json()["change"]["status"] == "noted"
    res = await app_client.post(
        f"{URL}/{noted.json()['change']['id']}/negotiation",
        headers=p["dl_h"],
        json={"negotiator_id": p["dl_id"]},
    )
    assert res.status_code == 409


async def test_case_of_rejected_candidate_leaves_tasks_and_closes_on_reminder(
    app_client: AsyncClient,
):
    """Przegląd PR3: po odrzuceniu kandydata sprawa nie wisi w „Czeka na
    Ciebie”, a przebieg przypomnień ją zamyka (bez decyzji)."""

    from app.services import candidate_rate_change as svc

    p = await _open_case(app_client)
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=p["cand_id"],
                job_id=p["job_id"],
                stage=PipelineStage.rejected,
                moved_by=p["dl_id"],
            )
        )
        await db.commit()
    as_dl = (await app_client.get("/api/board-tasks", headers=p["dl_h"])).json()
    assert p["change_id"] not in {r["change_id"] for r in as_dl["rate_changes"]}

    svc._REMINDERS_DONE_FOR = None
    now = datetime(2026, 10, 7, 8, 0, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as db:
        await svc.send_reminders(db, now)
        await db.commit()
    svc._REMINDERS_DONE_FOR = None
    async with AsyncSessionLocal() as db:
        change = await db.get(CandidateRateChange, p["change_id"])
        assert change.status == "closed"
        assert change.decision is None
