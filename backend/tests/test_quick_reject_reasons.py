"""Odrzucenie jednym kliknięciem — najczęstsze powody osoby (23.11.2026).

``GET /api/pipeline/my-quick-reject-reasons`` daje panelowi osoby trzy
najczęstsze powody zalogowanej osoby z 30 dni kalendarza firmy, dopełnione
najczęstszymi w zespole. Dostęp jak ``POST /api/pipeline/move``.
Zasady: ``docs/claude/rekrutacja-tablica/odrzucenie-jednym-kliknieciem.md``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import app.models  # noqa: F401  (register every mapper)
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.pipeline_template import RejectionReason, TerminalType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services import close_reasons
from app.services.quick_reject_reasons import (
    QUICK_KEY_BY_TEMPLATE_NAME,
    pick_quick_reasons,
    window_start,
)

URL = "/api/pipeline/my-quick-reject-reasons"

SKILL = "Nie spełnia wymagań technicznych"
JUNIOR = "Brak doświadczenia"
PRICE = "Za wysokie oczekiwania finansowe"
NOT_LOOKING = "not_looking_for_work"


# ── Wybór powodów (bez bazy) ────────────────────────────────────────────────


def test_top_three_of_the_person_by_count():
    picked = pick_quick_reasons(
        [(JUNIOR, 85), (SKILL, 108), (PRICE, 84), (NOT_LOOKING, 10)], []
    )
    assert [(r.key, r.count, r.source) for r in picked] == [
        ("missing_skill", 108, "mine"),
        ("too_junior", 85, "mine"),
        ("too_expensive", 84, "mine"),
    ]


def test_template_names_map_to_window_keys():
    # Konto 241 ma „Nie spełnia wymagań technicznych”, „Brak doświadczenia”
    # i „Za wysokie oczekiwania finansowe” — w oknie to te trzy powody.
    assert QUICK_KEY_BY_TEMPLATE_NAME[SKILL] == "missing_skill"
    assert QUICK_KEY_BY_TEMPLATE_NAME[JUNIOR] == "too_junior"
    assert QUICK_KEY_BY_TEMPLATE_NAME[PRICE] == "too_expensive"
    assert QUICK_KEY_BY_TEMPLATE_NAME["client_other_vendor"] == "client_employed"


def test_no_history_takes_the_team_top():
    picked = pick_quick_reasons(
        [], [(SKILL, 40), (NOT_LOOKING, 30), (JUNIOR, 20), (PRICE, 1)]
    )
    assert [r.key for r in picked] == ["missing_skill", "not_looking", "too_junior"]
    assert {r.source for r in picked} == {"team"}


def test_short_history_is_filled_from_the_team_without_repeats():
    picked = pick_quick_reasons([(PRICE, 2)], [(PRICE, 50), (SKILL, 40), (JUNIOR, 30)])
    assert [(r.key, r.source) for r in picked] == [
        ("too_expensive", "mine"),
        ("missing_skill", "team"),
        ("too_junior", "team"),
    ]


def test_reasons_with_a_description_or_not_ours_never_make_the_shortcut():
    picked = pick_quick_reasons(
        [
            ("Inne (rejected)", 500),
            ("hm_already_interviewed", 400),
            ("client_chose_other", 300),
            ("client_no_reason", 200),
            ("Kandydat nieosiągalny", 100),
            (SKILL, 1),
        ],
        [],
    )
    assert [r.key for r in picked] == ["missing_skill"]


def test_every_shortcut_key_is_a_reason_we_pick_without_description():
    for key in QUICK_KEY_BY_TEMPLATE_NAME.values():
        reason = close_reasons.BY_KEY[key]
        assert close_reasons.RECRUITER in reason.who
        assert key not in {"other", "hm_already_interviewed"}


def test_window_is_thirty_days_of_the_company_calendar():
    start = window_start(date(2026, 11, 23))
    assert start.date() == date(2026, 10, 25)
    # 25.10.2026 to dzień zmiany czasu: o północy jeszcze czas letni (UTC+2).
    assert start.utcoffset() == timedelta(hours=2)
    assert window_start(date(2026, 12, 15)).utcoffset() == timedelta(hours=1)
    assert (start.hour, start.minute) == (0, 0)


# ── Trasa (z bazą) ──────────────────────────────────────────────────────────


async def _user(role: UserRole) -> tuple[dict, int]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"quick-reject-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Quick"),
            name=f"Quick Reject {tag}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        uid = user.id
    return {"Authorization": f"Bearer {create_access_token(uid, role.value)}"}, uid


async def _reason_id(db, name: str) -> int:
    reason_id = await db.scalar(
        select(RejectionReason.id)
        .where(
            RejectionReason.name == name,
            RejectionReason.category == TerminalType.rejected,
        )
        .limit(1)
    )
    assert reason_id is not None, f"brak powodu {name} w szablonach"
    return reason_id


async def _rejections(
    moved_by: int,
    rows: list[tuple[str, int]],
    *,
    ended_by: str = "recruiter",
    days_ago: int = 1,
) -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"QuickReject-{tag}")
        db.add(client)
        await db.flush()
        job = Job(title=f"QR-{tag}", status=JobStatus.published, client_id=client.id)
        db.add(job)
        await db.flush()
        moved_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
        for name, count in rows:
            reason_id = await _reason_id(db, name)
            for i in range(count):
                candidate = Candidate(
                    name="Quick",
                    lastname=f"Reject-{tag}-{i}",
                    email=f"qr-{tag}-{name[:4]}-{i}@example.com",
                )
                db.add(candidate)
                await db.flush()
                db.add(
                    CandidateStage(
                        candidate_id=candidate.id,
                        job_id=job.id,
                        stage=PipelineStage.rejected,
                        moved_at=moved_at,
                        moved_by=moved_by,
                        rejection_reason_id=reason_id,
                        ended_by=ended_by,
                    )
                )
        await db.commit()


@pytest.mark.asyncio
async def test_route_counts_own_rejections_of_the_last_thirty_days(
    app_client: AsyncClient,
):
    headers, me = await _user(UserRole.recruiter)
    await _rejections(me, [(SKILL, 4), (JUNIOR, 3), (PRICE, 2), (NOT_LOOKING, 1)])
    # Klient odrzucił — nie my; i wiersze sprzed okna — nie wchodzą.
    await _rejections(me, [(NOT_LOOKING, 9)], ended_by="client")
    await _rejections(me, [(NOT_LOOKING, 9)], days_ago=40)

    resp = await app_client.get(URL, headers=headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reasons"] == [
        {"key": "missing_skill", "count": 4, "source": "mine"},
        {"key": "too_junior", "count": 3, "source": "mine"},
        {"key": "too_expensive", "count": 2, "source": "mine"},
    ]
    assert body["since"] == window_start().date().isoformat()


@pytest.mark.asyncio
async def test_person_without_history_gets_the_team_top(app_client: AsyncClient):
    _, colleague = await _user(UserRole.recruiter)
    await _rejections(colleague, [(SKILL, 3)])
    headers, _me = await _user(UserRole.recruiter)

    resp = await app_client.get(URL, headers=headers)

    assert resp.status_code == 200, resp.text
    reasons = resp.json()["reasons"]
    assert 1 <= len(reasons) <= 3
    assert {r["source"] for r in reasons} == {"team"}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.automation, UserRole.trainee, UserRole.user])
async def test_role_that_cannot_reject_gets_no_shortcut_and_no_move(
    app_client: AsyncClient, role: UserRole
):
    headers, _ = await _user(role)

    reasons = await app_client.get(URL, headers=headers)
    move = await app_client.post(
        "/api/pipeline/move",
        headers=headers,
        json={"candidate_id": 1, "job_id": 1, "stage": "rejected"},
    )

    assert reasons.status_code == 403, reasons.text
    assert move.status_code == 403, move.text
