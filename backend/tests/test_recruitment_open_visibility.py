"""Rekrutacje i kandydatów widzą wszyscy; stawki do klienta nie widzi rekruter.

Decyzje Artura z 23.09.2026:

* notatki i wszystkie elementy panelu rekrutacji i kandydata widzi każda rola
  wewnętrzna, bez przypisania do zespołu rekrutacji; zapis też („każdy może
  wszystko"), zostają wyłącznie bramki ról,
* czat rekrutacji i czat kandydata czyta i pisze każdy,
* stawki DO KLIENTA nie widzą rekruter, sourcer i TAC (osoba z dodatkową rolą
  zarządczą widzi), zapisuje ją wyłącznie Delivery Lead albo admin,
* stawkę KANDYDATA widzą wszyscy.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import true

from app.api.candidate_access import (
    user_can_read_client_rate,
    user_can_write_client_rate,
)
from app.api.candidates import _candidate_history_response_for_user
from app.api.pipeline import _stage_response
from app.api.recruitment_access import ensure_job_membership, job_scope_clause
from app.core.database import AsyncSessionLocal
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole


def _user(role: UserRole, *extra: UserRole) -> User:
    return User(
        id=900_000 + len(extra),
        email=f"{role.value}@example.com",
        name=role.value,
        role=role,
        roles=[role.value, *(r.value for r in extra)],
        is_active=True,
    )


# ── Reguła stawki do klienta ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "role",
    [UserRole.recruiter, UserRole.sourcer, UserRole.tac, UserRole.user],
)
def test_recruiting_roles_do_not_read_the_client_rate(role: UserRole) -> None:
    assert user_can_read_client_rate(_user(role)) is False


@pytest.mark.parametrize(
    "role",
    [
        UserRole.admin,
        UserRole.head_of_recruitment,
        UserRole.delivery_lead,
        UserRole.talent_community_manager,
        UserRole.finance,
    ],
)
def test_management_and_finance_read_the_client_rate(role: UserRole) -> None:
    assert user_can_read_client_rate(_user(role)) is True


def test_a_recruiter_who_is_also_a_delivery_lead_reads_the_client_rate() -> None:
    assert user_can_read_client_rate(_user(UserRole.recruiter, UserRole.delivery_lead))


def test_only_admin_and_delivery_lead_write_the_client_rate() -> None:
    owner = _user(UserRole.recruiter)
    job = Job(id=1, title="x", recruiter_id=owner.id, created_by=owner.id)
    # Właściciel rekrutacji nie zapisuje już stawki (do 23.09 zapisywał).
    assert user_can_write_client_rate(owner, job) is False
    for role in (
        UserRole.head_of_recruitment,
        UserRole.talent_community_manager,
        UserRole.tac,
        UserRole.finance,
        UserRole.sourcer,
    ):
        assert user_can_write_client_rate(_user(role), job) is False, role
    assert user_can_write_client_rate(_user(UserRole.admin), job) is True
    assert user_can_write_client_rate(_user(UserRole.delivery_lead), job) is True


def _stage_with_rates() -> CandidateStage:
    return CandidateStage(
        id=1,
        candidate_id=2,
        job_id=3,
        stage=PipelineStage.cv_sent,
        moved_at=datetime.now(timezone.utc),
        expected_rate_value=Decimal("150"),
        expected_rate_unit="hourly",
        expected_rate_currency="PLN",
        client_rate_value=Decimal("190"),
        client_rate_unit="hourly",
        client_rate_currency="PLN",
    )


def test_board_card_hides_client_rate_from_a_recruiter_but_keeps_candidate_rate() -> (
    None
):
    payload = _stage_response(_stage_with_rates(), viewer=_user(UserRole.recruiter))
    assert payload["client_rate_value"] is None
    assert payload["client_rate_unit"] is None
    assert payload["expected_rate_value"] == Decimal("150")


def test_board_card_shows_client_rate_to_a_delivery_lead() -> None:
    payload = _stage_response(_stage_with_rates(), viewer=_user(UserRole.delivery_lead))
    assert payload["client_rate_value"] == Decimal("190")


def test_board_card_without_a_viewer_is_redacted() -> None:
    payload = _stage_response(_stage_with_rates(), viewer=None)
    assert payload["client_rate_value"] is None


def _history() -> dict:
    return {
        "jobs": [
            {
                "job_id": 3,
                "client_rate": {"value": 190.0, "unit": "hourly", "currency": "PLN"},
                "expected_rate": {"value": 150.0, "unit": "hourly", "currency": "PLN"},
            }
        ],
        "contracts": [{"contract_id": 7, "rate_client": 200, "rate_candidate": 160}],
    }


def test_profile_history_for_a_recruiter_shows_candidate_rate_only() -> None:
    out = _candidate_history_response_for_user(_history(), _user(UserRole.recruiter))
    job = out["jobs"][0]
    assert job["client_rate"] is None
    assert job["expected_rate"] == {"value": 150.0, "unit": "hourly", "currency": "PLN"}
    assert "rate_client" not in out["contracts"][0]
    assert out["can_read_client_rate"] is False
    assert out["can_write_client_rate"] is False


def test_profile_history_for_head_of_recruitment_shows_client_rate() -> None:
    out = _candidate_history_response_for_user(
        _history(), _user(UserRole.head_of_recruitment)
    )
    assert out["jobs"][0]["client_rate"]["value"] == 190.0
    assert out["can_read_client_rate"] is True
    # Kwoty KONTRAKTÓW zostają przy dostępie finansowym, jak dotąd.
    assert "rate_client" not in out["contracts"][0]


def test_profile_history_for_finance_shows_everything() -> None:
    out = _candidate_history_response_for_user(_history(), _user(UserRole.finance))
    assert out["jobs"][0]["client_rate"]["value"] == 190.0
    assert out["contracts"][0]["rate_client"] == 200


# ── Bramka zespołu otwarta dla ról wewnętrznych ─────────────────────────────


@pytest.mark.parametrize("role", [UserRole.recruiter, UserRole.sourcer, UserRole.tac])
async def test_recruiting_roles_pass_the_team_gate_without_membership(
    role: UserRole,
) -> None:
    # Bez sesji bazy: bramka przepuszcza rolę wewnętrzną przed jakimkolwiek
    # zapytaniem o członkostwo.
    await ensure_job_membership(None, _user(role), 123)  # type: ignore[arg-type]
    assert job_scope_clause(_user(role), Job.id) is true()


def test_personal_views_still_count_assignment() -> None:
    clause = job_scope_clause(_user(UserRole.recruiter), Job.id, oversight_bypass=False)
    assert clause is not true()


def test_legacy_viewer_is_still_scoped_to_membership() -> None:
    assert job_scope_clause(_user(UserRole.user), Job.id) is not true()


# ── Ścieżka HTTP: rekruter spoza zespołu ────────────────────────────────────


async def _login(app_client: AsyncClient, role: UserRole) -> tuple[dict[str, str], int]:
    from app.core.security import hash_password

    unique = uuid.uuid4().hex[:8]
    email = f"open-vis-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Vis"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Open Vis {role.value}",
            role=role,
            roles=[role.value],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        uid = user.id
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, uid


async def _seed_job_candidate_stage() -> tuple[int, int]:
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import JobStatus
    from app.models.note import Note

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"OpenVisClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.flush()
        job = Job(
            title=f"OpenVis-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        cand = Candidate(
            name="Open",
            lastname=f"Vis-{uuid.uuid4().hex[:6]}",
            email=f"open-vis-{uuid.uuid4().hex[:8]}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([job, cand])
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.cv_sent,
                moved_at=datetime.now(timezone.utc),
                expected_rate_value=Decimal("150"),
                expected_rate_unit="hourly",
                expected_rate_currency="PLN",
                client_rate_value=Decimal("190"),
                client_rate_unit="hourly",
                client_rate_currency="PLN",
            )
        )
        db.add(
            Note(
                candidate_id=cand.id,
                job_id=job.id,
                content="Notatka z rekrutacji, w której nie jestem",
            )
        )
        await db.commit()
        return job.id, cand.id


def _card(board: dict, candidate_id: int) -> dict:
    for column in board["columns"]:
        for item in column["items"]:
            if item["candidate_id"] == candidate_id:
                return item
    raise AssertionError(f"brak karty kandydata {candidate_id}")


async def test_non_member_recruiter_sees_board_notes_and_history_without_client_rate(
    app_client: AsyncClient,
) -> None:
    headers, _ = await _login(app_client, UserRole.recruiter)
    job_id, cand_id = await _seed_job_candidate_stage()

    board = await app_client.get(f"/api/pipeline/kanban/{job_id}", headers=headers)
    assert board.status_code == 200, board.text
    card = _card(board.json(), cand_id)
    assert card["client_rate_value"] is None
    assert Decimal(str(card["expected_rate_value"])) == Decimal("150")

    stages = await app_client.get(
        f"/api/pipeline/history/{cand_id}/{job_id}", headers=headers
    )
    assert stages.status_code == 200, stages.text
    assert all(row["client_rate_value"] is None for row in stages.json())

    notes = await app_client.get(
        "/api/notes", params={"job_id": job_id}, headers=headers
    )
    assert notes.status_code == 200, notes.text
    assert "Notatka z rekrutacji" in notes.text

    history = await app_client.get(
        f"/api/candidates/{cand_id}/history", headers=headers
    )
    assert history.status_code == 200, history.text
    body = history.json()
    job = next(j for j in body["jobs"] if j["job_id"] == job_id)
    assert job["client_rate"] is None
    assert job["expected_rate"]["value"] == 150.0
    assert body["can_read_client_rate"] is False

    rate = await app_client.patch(
        f"/api/candidates/{cand_id}/recruitments/{job_id}/client-rate",
        json={"rate_value": 200, "rate_unit": "hourly"},
        headers=headers,
    )
    assert rate.status_code == 403, rate.text


async def test_non_member_recruiter_reads_and_writes_both_chats(
    app_client: AsyncClient,
) -> None:
    headers, _ = await _login(app_client, UserRole.recruiter)
    job_id, cand_id = await _seed_job_candidate_stage()

    for base in (f"/api/jobs/{job_id}/chat", f"/api/candidates/{cand_id}/chat"):
        posted = await app_client.post(
            f"{base}/messages",
            json={"content": "Pytanie spoza zespołu"},
            headers=headers,
        )
        assert posted.status_code in (200, 201), posted.text
        listed = await app_client.get(f"{base}/messages", headers=headers)
        assert listed.status_code == 200, listed.text
        assert "Pytanie spoza zespołu" in listed.text


async def test_chat_of_a_missing_job_is_404(app_client: AsyncClient) -> None:
    headers, _ = await _login(app_client, UserRole.recruiter)
    resp = await app_client.get("/api/jobs/999999999/chat/messages", headers=headers)
    assert resp.status_code == 404, resp.text


async def test_delivery_lead_sees_client_rate_on_the_board(
    app_client: AsyncClient,
) -> None:
    headers, _ = await _login(app_client, UserRole.delivery_lead)
    job_id, cand_id = await _seed_job_candidate_stage()

    board = await app_client.get(f"/api/pipeline/kanban/{job_id}", headers=headers)
    assert board.status_code == 200, board.text
    assert Decimal(str(_card(board.json(), cand_id)["client_rate_value"])) == Decimal(
        "190"
    )
