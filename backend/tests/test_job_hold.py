"""Rekrutacja „Wstrzymana” (``on_hold``, decyzje Artura 26.11.2026).

Bez bazy: lustro DDL, stany i wspólne przypadki, czyste reguły (termin,
zgłoszenia, cisza DL, kolejność panelu), treści dzwonków i rejestry typów.
Z bazą: trasy (401/403/409/422), zgłoszenie rekrutera, panel DL, batch PATCH,
pętla ``job_idle`` (pominięcie, termin, 30 dni) i pola rekrutacji.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.services import job_hold
from app.services.job_hold import (
    Report,
    dl_silent_since,
    held_notice_text,
    long_hold_days,
    parked_still_working,
    resumes_work,
    open_reports,
    resumed_notice_text,
    review_due,
    review_on_error,
    sort_items,
    sort_signals,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 26, 10, 0, tzinfo=timezone.utc)
TODAY = date(2026, 11, 26)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


# ── Bez bazy: schemat ───────────────────────────────────────────────────────


def test_every_ddl_statement_is_mirrored_in_entrypoint() -> None:
    from app.services.job_hold_schema import COLUMN_STATEMENTS, ENUM_STATEMENTS

    entry = _squash((ROOT / "entrypoint.sh").read_text())
    for statement in COLUMN_STATEMENTS + ENUM_STATEMENTS:
        assert _squash(statement) in entry, statement.splitlines()[0]


def test_check_with_on_hold_runs_after_the_0371_check_in_entrypoint() -> None:
    """Na pustej bazie 0371 zakłada stary CHECK — wymiana musi przyjść po nim."""
    entry = (ROOT / "entrypoint.sh").read_text()
    old = entry.index("'client_silent', 'finished'));")
    new = entry.index("'client_silent', 'on_hold', 'finished'));")
    assert old < new


def test_migration_follows_0792_and_reads_the_single_source() -> None:
    migration = (ROOT / "alembic/versions/0794_job_hold.py").read_text()
    assert 'down_revision = "0793_pracuj_public_links"' in migration
    assert "COLUMN_STATEMENTS" in migration and "ENUM_STATEMENTS" in migration
    others = [
        p.name
        for p in (ROOT / "alembic/versions").glob("*.py")
        if 'down_revision = "0793_pracuj_public_links"' in p.read_text()
        and p.name != "0794_job_hold.py"
    ]
    assert others == [], others


def test_check_knows_every_work_state() -> None:
    from app.services.job_hold_schema import WORK_STATES_0793
    from app.services.request_work_state import WORK_STATES

    assert set(WORK_STATES) == set(WORK_STATES_0793)


# ── Bez bazy: stany ─────────────────────────────────────────────────────────


def test_on_hold_is_a_visible_state_outside_the_work_states() -> None:
    from app.services.request_work_state import (
        IN_WORK_STATES,
        LABELS,
        VISIBLE_STATES,
        WORK_STATES,
        visible_state,
    )

    assert "on_hold" in WORK_STATES and "on_hold" in VISIBLE_STATES
    assert "on_hold" not in IN_WORK_STATES
    assert LABELS["on_hold"] == "Wstrzymana"
    # Champion liczy się tylko przy „Szukamy”.
    assert visible_state("on_hold", NOW) == "on_hold"


def test_shared_cases_cover_on_hold() -> None:
    cases = json.loads(
        (
            ROOT.parent / "frontend/src/lib/__fixtures__/request-work-state-cases.json"
        ).read_text()
    )["cases"]
    held = [c for c in cases if c["work_state"] == "on_hold"]
    assert {c["champion"] for c in held} == {True, False}
    assert all(c["visible"] == "on_hold" for c in held)


def test_request_stage_and_status_know_on_hold_after_contract() -> None:
    from app.services import job_similarity as sim

    for values in (sim.REQUEST_STAGES, sim.REQUEST_STATUSES):
        assert values.index("contract") < values.index("on_hold")
        assert values.index("on_hold") < values.index("champion")


def test_quiet_states_and_release_label_treat_on_hold_like_client_silent() -> None:
    from app.services.insights_team_signals import QUIET_WORK_STATES
    from app.services.request_allocation_plan import release_reason_label

    assert "on_hold" in QUIET_WORK_STATES
    assert release_reason_label("proposal:on_hold") == "Rekrutacja wstrzymana"


def test_batch_body_accepts_on_hold_only_to_refuse_it_in_polish() -> None:
    from app.api.request_work_states import HOLD_REFUSED, StateChange

    assert StateChange(job_id=1, state="on_hold").state == "on_hold"
    assert "wymaga powodu" in HOLD_REFUSED
    with pytest.raises(ValidationError):
        StateChange(job_id=1, state="champion")


def test_hold_body_strips_and_limits_the_reason() -> None:
    from app.api.job_hold import HoldIn, HoldReportIn

    assert HoldIn(reason="  Klient wstrzymał budżet  ").reason == (
        "Klient wstrzymał budżet"
    )
    for bad in ("", "   ", "x" * 501):
        with pytest.raises(ValidationError):
            HoldIn(reason=bad)
    assert HoldIn(reason="x" * 500).notify is True
    assert HoldReportIn().note == ""
    with pytest.raises(ValidationError):
        HoldReportIn(note="x" * 501)


# ── Bez bazy: reguły ────────────────────────────────────────────────────────


def test_review_date_from_today_up_to_120_days() -> None:
    assert review_on_error(None, TODAY) is None
    assert review_on_error(TODAY, TODAY) is None
    assert review_on_error(TODAY + timedelta(days=120), TODAY) is None
    past = review_on_error(TODAY - timedelta(days=1), TODAY)
    far = review_on_error(TODAY + timedelta(days=121), TODAY)
    assert (past.status, past.code) == (422, "review_on_past")
    assert (far.status, far.code) == (422, "review_on_too_far")


def test_answer_closes_every_earlier_report() -> None:
    first = Report(1, NOW - timedelta(days=3), "a", "searching")
    second = Report(2, NOW - timedelta(hours=1), "b", "searching")
    assert open_reports([second, first], None) == [first, second]
    assert open_reports([first, second], NOW - timedelta(days=1)) == [second]
    assert open_reports([first, second], NOW) == []


def test_dl_silence_needs_recruiter_work_and_waits_14_days_after_an_answer() -> None:
    quiet = NOW - timedelta(days=20)
    kw = dict(last_dl_move_at=quiet, opened_at=NOW - timedelta(days=90), now=NOW)
    assert dl_silent_since(anchor_at=None, recruiter_moves_7d=3, **kw) == quiet
    # Bez pracy rekruterów to „bez ruchu”, nie pytanie o wstrzymanie.
    assert dl_silent_since(anchor_at=None, recruiter_moves_7d=0, **kw) is None
    # Odpowiedź DL 5 dni temu — sygnał wraca najwcześniej po 14 dniach.
    assert (
        dl_silent_since(anchor_at=NOW - timedelta(days=5), recruiter_moves_7d=3, **kw)
        is None
    )
    assert (
        dl_silent_since(anchor_at=NOW - timedelta(days=15), recruiter_moves_7d=3, **kw)
        == quiet
    )
    recent = dict(kw, last_dl_move_at=NOW - timedelta(days=13))
    assert dl_silent_since(anchor_at=None, recruiter_moves_7d=3, **recent) is None


def test_panel_order_is_report_note_parked_silence_then_recruiter_moves() -> None:
    def item(job_id: int, kind: str, moves: int) -> dict:
        return {
            "job_id": job_id,
            "recruiter_moves_7d": moves,
            "signals": [{"kind": kind, "at": NOW.isoformat()}],
        }

    ordered = sort_items(
        [
            item(1, "dl_silent", 50),
            item(2, "parked_still_working", 1),
            item(3, "note", 1),
            item(4, "report", 0),
            item(5, "note", 9),
        ]
    )
    assert [i["job_id"] for i in ordered] == [4, 5, 3, 2, 1]
    signals = sort_signals(
        [
            {"kind": "dl_silent", "at": NOW.isoformat()},
            {"kind": "report", "at": (NOW - timedelta(days=1)).isoformat()},
            {"kind": "report", "at": NOW.isoformat()},
        ]
    )
    assert [s["kind"] for s in signals] == ["report", "report", "dl_silent"]
    assert signals[0]["at"] == NOW.isoformat()


def test_parked_signal_needs_real_work_this_week() -> None:
    # Staging 26.11: 8 z 10 wierszy panelu DL to zejście z P1 przy 0–1 ruchu
    # rekrutera w tygodniu — szum, który uczy DL ignorować panel.
    assert parked_still_working(moves_after_park=0, moves_7d=5) is False
    assert parked_still_working(moves_after_park=4, moves_7d=0) is False
    assert parked_still_working(moves_after_park=4, moves_7d=2) is False
    assert parked_still_working(moves_after_park=3, moves_7d=3) is True


def test_leaving_hold_into_work_is_a_resume() -> None:
    # Przegląd 26.11: batch na /jobs/review-states zdejmował wstrzymanie bez
    # dzwonka „Rekrutacja wznowiona”. Wznowienie = wyjście z on_hold do pracy.
    assert resumes_work("on_hold", "searching") is True
    assert resumes_work("on_hold", "to_review") is True
    assert resumes_work("on_hold", "client_silent") is False
    assert resumes_work("on_hold", "finished") is False
    assert resumes_work("searching", "to_review") is False


def test_review_and_30_days_rules() -> None:
    assert review_due(TODAY, TODAY) and review_due(TODAY - timedelta(days=2), TODAY)
    assert not review_due(TODAY + timedelta(days=1), TODAY)
    assert not review_due(None, TODAY)
    assert long_hold_days(NOW - timedelta(days=29), TODAY) is None
    assert long_hold_days(NOW - timedelta(days=30), TODAY) == 30
    assert long_hold_days(None, TODAY) is None


def test_notice_texts_say_what_to_do() -> None:
    title, message = held_notice_text(
        job_title="Analityk",
        client_name="Bank",
        actor_name="DL Test",
        reason="Klient wstrzymał budżet",
        review_on=date(2026, 12, 10),
    )
    assert title == "Rekrutacja wstrzymana: Analityk"
    assert "Klient wstrzymał budżet" in message and "10.12" in message
    assert "Nie proponuj kandydatom tego projektu" in message
    title, message = resumed_notice_text(
        job_title="Analityk", client_name=None, actor_name=None
    )
    assert title == "Rekrutacja wznowiona: Analityk"
    assert "Szukamy" in message


def test_resume_anchors_the_idle_counter() -> None:
    from app.services.job_idle import IdleFacts, idle_state

    start = NOW - timedelta(days=60)
    facts = IdleFacts(
        job_id=1,
        opened_at=NOW - timedelta(days=60),
        last_move_at=NOW - timedelta(days=40),
        last_move_kind="cv",
        snoozed_at=None,
        hold_ended_at=NOW - timedelta(days=2),
    )
    state = idle_state(facts, started_at=start, now=NOW)
    assert state.since == facts.hold_ended_at
    assert state.stage is None


def test_notification_types_are_registered_everywhere() -> None:
    from app.models.notification import NotificationType as T
    from app.services.notification_access import NOTIFICATION_SECTION_BY_TYPE
    from app.services.notification_categories import (
        CATEGORY_BY_TYPE,
        NotificationCategory,
    )
    from app.services.notification_delivery import (
        BELL_MAIL_TYPES,
        JOB_HOLD_KIND,
        REQUIRED_KINDS,
    )
    from app.services.notification_email_prefs import APPLIES
    from app.services.notification_mail_card import SPECS
    from app.services.notification_substitution import CURRENT_WORK_TYPES

    assert CATEGORY_BY_TYPE[T.job_hold_changed] is NotificationCategory.mentions
    assert CATEGORY_BY_TYPE[T.job_hold_check] is NotificationCategory.mentions
    for ntype in (T.job_hold_changed, T.job_hold_check):
        assert ntype in NOTIFICATION_SECTION_BY_TYPE
        assert ntype in CURRENT_WORK_TYPES
    # Mail obowiązkowy tylko dla zmiany stanu; pytanie do DL to sam dzwonek.
    assert JOB_HOLD_KIND in REQUIRED_KINDS and JOB_HOLD_KIND in APPLIES
    assert BELL_MAIL_TYPES[JOB_HOLD_KIND] == ("job_hold_changed",)
    assert all("job_hold_check" not in types for types in BELL_MAIL_TYPES.values())
    assert SPECS["job_hold_changed"].use_title


# ── Z bazą ──────────────────────────────────────────────────────────────────


async def _user(role, *, suffix: str, hor: bool = False) -> tuple[int, str]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User

    email = f"hold-{role.value}-{suffix}@example.com"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password("P@ssw0rd"),
            name=f"{role.value} {suffix}",
            role=role,
            roles=[role.value],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id, email


async def _headers(app_client: AsyncClient, email: str) -> dict[str, str]:
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": "P@ssw0rd"}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _seed(*, work_state: str = "searching") -> dict:
    """Rekrutacja z DL-em i rekruterem, który prowadzi osobę w „Screeningu”."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import PipelineStage
    from app.models.user import UserRole
    from app.services.recruitment_process_commands import transition_process

    suffix = uuid.uuid4().hex[:8]
    lead_id, lead_email = await _user(UserRole.delivery_lead, suffix=suffix)
    rec_id, rec_email = await _user(UserRole.recruiter, suffix=suffix)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"HoldClient-{suffix}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"pytest-hold-{suffix}",
            client_id=client.id,
            status=JobStatus.published,
            delivery_lead_id=lead_id,
            work_state=work_state,
            opened_at=datetime.now(timezone.utc) - timedelta(days=3),
        )
        candidate = Candidate(
            name="Wstrzymana",
            lastname=f"Osoba{suffix}",
            email=f"hold-{suffix}@example.com",
        )
        db.add_all([job, candidate])
        await db.flush()
        for stage in ("new", "screening"):
            await transition_process(
                db,
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage(stage),
                actor_user_id=rec_id,
            )
        await db.commit()
        return {
            "job_id": job.id,
            "lead_id": lead_id,
            "lead_email": lead_email,
            "rec_id": rec_id,
            "rec_email": rec_email,
        }


async def _bells(user_id: int, ntype: str) -> list[tuple[str, str]]:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.notification import Notification, NotificationType

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Notification.title, Notification.message)
                .where(
                    Notification.user_id == user_id,
                    Notification.notification_type == NotificationType(ntype),
                )
                .order_by(Notification.id)
            )
        ).all()
        return [(t, m) for t, m in rows]


async def _job(job_id: int):
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        return await db.scalar(select(Job).where(Job.id == job_id))


def _future(days: int) -> str:
    from app.core.scheduling import business_today

    return (business_today() + timedelta(days=days)).isoformat()


@pytest.mark.asyncio
async def test_hold_resume_and_messages(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    seed = await _seed()
    job_id, rec_id = seed["job_id"], seed["rec_id"]

    before = await app_client.get(f"/api/jobs/{job_id}/hold", headers=app_auth_headers)
    assert before.status_code == 200, before.text
    body = before.json()
    assert (body["state"], body["reason"], body["can_manage"]) == (
        "searching",
        None,
        True,
    )
    assert any(
        r["user_id"] == rec_id and r["people"] == 1 for r in body["recipients"]
    ), body["recipients"]

    held = await app_client.put(
        f"/api/jobs/{job_id}/hold",
        json={"reason": "  Klient wstrzymał budżet ", "review_on": _future(14)},
        headers=app_auth_headers,
    )
    assert held.status_code == 200, held.text
    out = held.json()
    assert out["state"] == "on_hold" and out["reason"] == "Klient wstrzymał budżet"
    assert out["review_on"] == _future(14) and out["since"] and out["by_name"]
    bells = await _bells(rec_id, "job_hold_changed")
    assert len(bells) == 1 and bells[0][0].startswith("Rekrutacja wstrzymana")

    # Zmiana powodu nie wysyła drugi raz.
    changed = await app_client.put(
        f"/api/jobs/{job_id}/hold",
        json={"reason": "Zmiana zakresu", "review_on": None},
        headers=app_auth_headers,
    )
    assert changed.status_code == 200 and changed.json()["reason"] == "Zmiana zakresu"
    assert len(await _bells(rec_id, "job_hold_changed")) == 1

    detail = await app_client.get(f"/api/jobs/{job_id}", headers=app_auth_headers)
    assert detail.json()["request_stage"] == "on_hold"
    assert detail.json()["request_status"] == "on_hold"
    assert detail.json()["hold_reason"] == "Zmiana zakresu"
    assert detail.json()["hold_since"] and detail.json()["hold_by_name"]

    resumed = await app_client.delete(
        f"/api/jobs/{job_id}/hold", headers=app_auth_headers
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["state"] == "searching" and resumed.json()["reason"] is None
    job = await _job(job_id)
    assert (job.hold_reason, job.hold_review_on) == (None, None)
    assert job.hold_ended_at is not None
    titles = [t for t, _m in await _bells(rec_id, "job_hold_changed")]
    assert titles[-1].startswith("Rekrutacja wznowiona")

    again = await app_client.delete(
        f"/api/jobs/{job_id}/hold", headers=app_auth_headers
    )
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "job_not_on_hold"


@pytest.mark.asyncio
async def test_hold_refusals(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from sqlalchemy import update

    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobStatus

    seed = await _seed()
    job_id = seed["job_id"]
    url = f"/api/jobs/{job_id}/hold"

    assert (await app_client.put(url, json={"reason": "x"})).status_code == 401
    rec = await _headers(app_client, seed["rec_email"])
    denied = await app_client.put(url, json={"reason": "x"}, headers=rec)
    assert denied.status_code == 403
    assert (await app_client.get(url, headers=rec)).json()["can_manage"] is False

    for review_on, code in (
        (_future(-1), "review_on_past"),
        (_future(121), "review_on_too_far"),
    ):
        resp = await app_client.put(
            url, json={"reason": "x", "review_on": review_on}, headers=app_auth_headers
        )
        assert resp.status_code == 422 and resp.json()["detail"]["code"] == code
    empty = await app_client.put(url, json={"reason": "  "}, headers=app_auth_headers)
    assert empty.status_code == 422

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Job).where(Job.id == job_id).values(status=JobStatus.closed)
        )
        await db.commit()
    closed = await app_client.put(url, json={"reason": "x"}, headers=app_auth_headers)
    assert closed.status_code == 409
    assert closed.json()["detail"]["code"] == "job_not_open"


@pytest.mark.asyncio
async def test_report_once_until_the_lead_answers(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    seed = await _seed()
    job_id = seed["job_id"]
    rec = await _headers(app_client, seed["rec_email"])
    lead = await _headers(app_client, seed["lead_email"])

    first = await app_client.post(
        f"/api/jobs/{job_id}/hold/report",
        json={"note": "Kandydat słyszał od klienta, że projekt stoi"},
        headers=rec,
    )
    assert first.status_code == 201, first.text
    assert first.json() == {"ok": True}
    assert len(await _bells(seed["lead_id"], "job_hold_check")) == 1
    mine = (await app_client.get(f"/api/jobs/{job_id}/hold", headers=rec)).json()
    assert mine["my_open_report"]["note"].startswith("Kandydat słyszał")

    twice = await app_client.post(
        f"/api/jobs/{job_id}/hold/report", json={}, headers=rec
    )
    assert twice.status_code == 409
    assert twice.json()["detail"]["code"] == "already_reported"

    checks = (await app_client.get("/api/hold-checks", headers=lead)).json()
    item = next(i for i in checks["items"] if i["job_id"] == job_id)
    assert item["signals"][0]["kind"] == "report"
    assert item["signals"][0]["by_name"]

    answered = await app_client.post(
        f"/api/jobs/{job_id}/hold-check", json={"answer": "searching"}, headers=lead
    )
    assert answered.status_code == 200 and answered.json() == {"ok": True}
    assert [t for t, _m in await _bells(seed["rec_id"], "job_hold_check")] == [
        "DL potwierdził: szukamy"
    ]
    after = (await app_client.get("/api/hold-checks", headers=lead)).json()
    assert job_id not in {i["job_id"] for i in after["items"]}
    assert (await app_client.get(f"/api/jobs/{job_id}/hold", headers=rec)).json()[
        "my_open_report"
    ] is None
    # Po odpowiedzi można zgłosić ponownie.
    again = await app_client.post(
        f"/api/jobs/{job_id}/hold/report", json={"note": ""}, headers=rec
    )
    assert again.status_code == 201

    wrong = await app_client.post(
        f"/api/jobs/{job_id}/hold-check", json={"answer": "on_hold"}, headers=lead
    )
    assert wrong.status_code == 422
    denied = await app_client.post(
        f"/api/jobs/{job_id}/hold-check", json={"answer": "searching"}, headers=rec
    )
    assert denied.status_code == 403
    assert (await app_client.get("/api/hold-checks", headers=rec)).status_code == 403


@pytest.mark.asyncio
async def test_note_with_on_hold_is_a_signal_without_its_text(
    app_client: AsyncClient,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.note import Note

    seed = await _seed()
    job_id = seed["job_id"]
    async with AsyncSessionLocal() as db:
        db.add(Note(content="Klient mówi: projekt ON HOLD do stycznia", job_id=job_id))
        await db.commit()
    lead = await _headers(app_client, seed["lead_email"])
    checks = (await app_client.get("/api/hold-checks", headers=lead)).json()
    item = next(i for i in checks["items"] if i["job_id"] == job_id)
    note = next(s for s in item["signals"] if s["kind"] == "note")
    assert "stycznia" not in note["text"]
    assert checks["total"] >= 1 and len(checks["items"]) <= job_hold.CHECKS_LIMIT


@pytest.mark.asyncio
async def test_batch_refuses_on_hold_but_lets_a_held_job_out(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    seed = await _seed()
    job_id = seed["job_id"]
    refused = await app_client.patch(
        "/api/request-work-states",
        json={"changes": [{"job_id": job_id, "state": "on_hold"}]},
        headers=app_auth_headers,
    )
    assert refused.status_code == 422
    assert refused.json()["detail"] == (
        "Wstrzymanie ustawisz w rekrutacji — wymaga powodu."
    )

    await app_client.put(
        f"/api/jobs/{job_id}/hold",
        json={"reason": "Czeka na decyzję klienta", "review_on": _future(7)},
        headers=app_auth_headers,
    )
    tab = await app_client.get(
        "/api/request-work-states?tab=on_hold&q=pytest-hold",
        headers=app_auth_headers,
    )
    assert tab.status_code == 200, tab.text
    assert job_id in {row["job_id"] for row in tab.json()["rows"]}
    listed = await app_client.get(
        "/api/jobs?request_stage=on_hold&q=pytest-hold", headers=app_auth_headers
    )
    assert listed.status_code == 200, listed.text

    out = await app_client.patch(
        "/api/request-work-states",
        json={"changes": [{"job_id": job_id, "state": "client_silent"}]},
        headers=app_auth_headers,
    )
    assert out.status_code == 200, out.text
    job = await _job(job_id)
    assert job.work_state == "client_silent"
    assert (job.hold_reason, job.hold_review_on) == (None, None)
    assert job.hold_ended_at is not None
    # „Klient milczy” to nie wznowienie pracy — bez dzwonka „wznowiona”.
    assert not [
        t
        for t, _m in await _bells(seed["rec_id"], "job_hold_changed")
        if t.startswith("Rekrutacja wznowiona")
    ]


@pytest.mark.asyncio
async def test_batch_back_to_searching_tells_the_team_it_resumed(
    app_client: AsyncClient,
) -> None:
    seed = await _seed()
    job_id = seed["job_id"]
    lead = await _headers(app_client, seed["lead_email"])
    held = await app_client.put(
        f"/api/jobs/{job_id}/hold",
        json={"reason": "Klient wstrzymał budżet", "review_on": _future(7)},
        headers=lead,
    )
    assert held.status_code == 200, held.text
    out = await app_client.patch(
        "/api/request-work-states",
        json={"changes": [{"job_id": job_id, "state": "searching"}]},
        headers=lead,
    )
    assert out.status_code == 200, out.text
    titles = [t for t, _m in await _bells(seed["rec_id"], "job_hold_changed")]
    assert any(t.startswith("Rekrutacja wznowiona") for t in titles), titles


@pytest.mark.asyncio
async def test_idle_sweep_skips_held_jobs_and_asks_on_the_review_day(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from sqlalchemy import delete, update

    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.app_setting import AppSetting
    from app.models.job import Job
    from app.services import job_idle
    from app.services.job_lifecycle import PostCommit

    seed = await _seed()
    job_id, lead_id = seed["job_id"], seed["lead_id"]
    now = datetime.now(timezone.utc)
    held = await app_client.put(
        f"/api/jobs/{job_id}/hold",
        json={"reason": "Klient wstrzymał budżet", "review_on": _future(0)},
        headers=app_auth_headers,
    )
    assert held.status_code == 200, held.text
    async with AsyncSessionLocal() as db:
        # Otwarta dawno, start reguły dawno — bez wstrzymania byłoby zamknięcie.
        await db.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                opened_at=now - timedelta(days=60),
                work_state_changed_at=now - timedelta(days=31),
            )
        )
        await db.execute(
            delete(AppSetting).where(AppSetting.key == job_idle.STARTED_KEY)
        )
        db.add(
            AppSetting(
                key=job_idle.STARTED_KEY,
                value={"at": (now - timedelta(days=60)).isoformat()},
            )
        )
        await db.commit()

    async def sweep() -> dict:
        async with AsyncSessionLocal() as db:
            counts = await job_idle.run_idle_sweep(
                db, PostCommit(), now=now, only_job_ids=[job_id]
            )
            await db.commit()
            return counts

    first = await sweep()
    assert (first["remind"], first["hor"], first["closed"]) == (0, 0, 0)
    assert (first["hold_review"], first["hold_long"]) == (1, 1)
    bells = await _bells(lead_id, "job_hold_check")
    assert len(bells) == 1 and bells[0][0].startswith("Wznawiamy?")
    assert "30 dni" in bells[0][1] or "31 dni" in bells[0][1]
    # Ten sam termin i to samo wstrzymanie — bez powtórki.
    second = await sweep()
    assert (second["hold_review"], second["hold_long"]) == (0, 0)
    assert (await _job(job_id)).work_state == "on_hold"

    idle = await app_client.get(f"/api/jobs/{job_id}/idle", headers=app_auth_headers)
    assert idle.json()["stage"] is None
    assert business_today() >= date.fromisoformat(_future(0))


@pytest.mark.asyncio
async def test_planner_keeps_the_team_of_a_held_job_but_drops_proposals(
    app_client: AsyncClient,
) -> None:
    """Zespół zostaje przy wstrzymaniu (decyzja Artura 26.11.2026)."""
    from app.core.database import AsyncSessionLocal
    from app.models.job_work_assignment import JobWorkAssignment
    from app.models.user import UserRole
    from app.services import request_allocation

    seed = await _seed(work_state="on_hold")
    other_id, _ = await _user(UserRole.recruiter, suffix=uuid.uuid4().hex[:8])
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                JobWorkAssignment(
                    job_id=seed["job_id"],
                    user_id=seed["rec_id"],
                    role="recruiter",
                    source="manual",
                    state="active",
                ),
                JobWorkAssignment(
                    job_id=seed["job_id"],
                    user_id=other_id,
                    role="recruiter",
                    source="auto",
                    state="proposed",
                ),
            ]
        )
        await db.commit()
        live, out, _inactive = await request_allocation._live(db)
    mine = {(row.user_id, row.state) for row in live if row.job_id == seed["job_id"]}
    assert mine == {(other_id, "proposed")}
    assert out[seed["job_id"]] == "on_hold"


def test_hold_check_is_a_named_bell_that_cannot_be_muted() -> None:
    # Staging 26.11: rekruterka z wyciszonymi „Przypomnieniami” nie dostała
    # „DL potwierdził: szukamy”, a DL z wyciszeniem nie dostałby zgłoszenia.
    # Pytanie i odpowiedź są imienne — jak przydział i zamknięcie rekrutacji.
    from app.models.notification import NotificationType
    from app.services.notification_categories import (
        NotificationCategory,
        category_for,
        is_mutable,
    )

    category = category_for(NotificationType.job_hold_check)
    assert category is NotificationCategory.mentions
    assert not is_mutable(category)
