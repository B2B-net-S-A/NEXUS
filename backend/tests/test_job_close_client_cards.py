"""Zamknięcie rekrutacji kończy pary u klienta (B5, 08.11.2026)."""

from __future__ import annotations

import importlib.util
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.job import JobCloseReason
from app.models.recruitment_pipeline import CandidateStage
from app.services.job_close_client_cards import (
    CLIENT_SIDE_COLUMNS,
    preview_payload,
    reason_key_for,
)
from app.services.job_closed_notices import Recipient, WaitingPerson, notice_text
from app.services.rejection_reason_labels import (
    CLIENT_NO_RESPONSE,
    CLIENT_NOT_A_VERDICT,
    REQUEST_CLOSED,
    rejection_reason_label,
)
from scripts.close_client_cards_backfill import moved_at_for, parse_reasons
from tests.test_job_close import _create_draft_job, _seed_candidate_in_job

_BACKEND = Path(__file__).resolve().parents[1]
_ENTRYPOINT = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
_MIGRATION_PATH = _BACKEND / "alembic" / "versions" / "0662_client_close_reasons.py"


def _migration():
    spec = importlib.util.spec_from_file_location("m0662", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _shape(text: str) -> str:
    glued = re.sub(r"[\"']\s*\n\s*[\"']", "", text)
    return " ".join(glued.replace('\\"', '"').split())


def test_entrypoint_mirrors_the_migration():
    seed = " ".join(_migration().SEED_CLIENT_CLOSE_REASONS.split())
    assert seed in _shape(_ENTRYPOINT)
    assert "'candidate', 'recruiter', 'delivery_lead', 'client', 'client_silent'" in (
        _ENTRYPOINT
    )


def test_seed_is_one_shot_and_downgrade_refuses_live_rows():
    module = _migration()
    assert "RETURNING key" in module.SEED_CLIENT_CLOSE_REASONS
    assert "TRUE, FALSE, 'manual'" in module.SEED_CLIENT_CLOSE_REASONS
    for key in (REQUEST_CLOSED, CLIENT_NO_RESPONSE):
        assert f"'{key}'" in module.SEED_CLIENT_CLOSE_REASONS
        assert f"'{key}'" in module.REFUSE_WITH_LIVE_ROWS
    assert "client_silent" in module.REFUSE_WITH_LIVE_ROWS


@pytest.mark.parametrize(
    ("key", "label"),
    [
        (REQUEST_CLOSED, "Request zamknięty"),
        (CLIENT_NO_RESPONSE, "Klient nie odpowiedział"),
    ],
)
def test_labels(key: str, label: str):
    assert rejection_reason_label(key) == label
    assert key in CLIENT_NOT_A_VERDICT


@pytest.mark.parametrize(
    ("reason", "key"),
    [
        ("competitor", "client_chose_other"),
        ("budget", REQUEST_CLOSED),
        (JobCloseReason.competitor, "client_chose_other"),
        ("filled_by_us", None),
        ("duplicate", None),
        ("client_ghosted", None),
        ("no_activity", None),
        ("nonsense", None),
    ],
)
def test_only_competitor_and_budget_end_client_cards(reason: Any, key: Any):
    assert reason_key_for(reason) == key


def test_contract_column_is_not_client_side():
    assert CLIENT_SIDE_COLUMNS == ("cv_sent", "client_interview")


def test_preview_says_how_many_and_no_mail():
    payload = preview_payload(
        {1: "cv_sent", 2: "cv_sent", 3: "client_interview"}, "competitor"
    )
    assert payload is not None
    assert payload["people"] == 3
    assert payload["columns"] == {"cv_sent": 2, "client_interview": 1}
    assert payload["reason_label"] == "Klient wybrał kogoś innego"
    assert "3 osoby są u klienta" in payload["message"]
    assert "nie dostaną maila" in payload["message"]


def test_preview_is_none_for_other_reasons_or_nobody():
    assert preview_payload({1: "cv_sent"}, "filled_by_us") is None
    assert preview_payload({}, "competitor") is None


def _recipient(*ids: int) -> Recipient:
    return Recipient(
        7,
        "Rekruter",
        tuple(WaitingPerson(i, f"Osoba {i}", "cv_sent") for i in ids),
    )


def test_notice_when_everyone_ended_tells_no_mail_went_out():
    _, message = notice_text(
        _recipient(1, 2),
        job_title="Java",
        client_name="ACME",
        actor_name="DL",
        reason="competitor",
        ended_ids=frozenset({1, 2}),
    )
    assert "NEXUS zakończył jako „przez klienta”" in message
    assert "bez maila do kandydatów" in message
    assert "nadal są w procesie" not in message


def test_notice_without_ending_stays_as_before():
    _, message = notice_text(
        _recipient(1),
        job_title="Java",
        client_name=None,
        actor_name=None,
        reason="duplicate",
    )
    assert "nadal są w procesie" in message


def test_backfill_uses_close_date_unless_the_card_moved_later():
    closed = datetime(2026, 10, 20, 10, tzinfo=timezone.utc)
    assert moved_at_for(closed, closed - timedelta(days=3)) == closed
    later = closed + timedelta(days=1)
    assert moved_at_for(closed, later) == later + timedelta(seconds=1)
    assert moved_at_for(closed, None) == closed


def test_backfill_refuses_reasons_without_a_key():
    assert [r.value for r in parse_reasons(["competitor", " budget"])] == [
        "competitor",
        "budget",
    ]
    with pytest.raises(SystemExit):
        parse_reasons(["filled_by_us"])
    with pytest.raises(SystemExit):
        parse_reasons([])


async def _latest(job_id: int, candidate_id: int) -> tuple[Any, Any, Any]:
    from app.core.database import AsyncSessionLocal
    from app.models.pipeline_template import RejectionReason

    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CandidateStage)
            .where(
                CandidateStage.job_id == job_id,
                CandidateStage.candidate_id == candidate_id,
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
        reason = (
            await db.scalar(
                select(RejectionReason.name).where(
                    RejectionReason.id == row.rejection_reason_id
                )
            )
            if row.rejection_reason_id
            else None
        )
        return getattr(row.stage, "value", row.stage), row.ended_by, reason


@pytest.mark.asyncio
async def test_close_competitor_ends_client_cards_only(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    job_id = await _create_draft_job(
        app_client, app_auth_headers, f"pytest-b5-{uuid.uuid4().hex[:6]}"
    )
    sent = await _seed_candidate_in_job(job_id, "new", "cv_sent")
    interview = await _seed_candidate_in_job(
        job_id, "new", "cv_sent", "client_interview"
    )
    internal = await _seed_candidate_in_job(job_id, "new", "verified")
    contract = await _seed_candidate_in_job(job_id, "new", "cv_sent", "acceptance")

    warned = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": "competitor"},
        headers=app_auth_headers,
    )
    assert warned.status_code == 409, warned.text
    client_end = warned.json()["detail"]["client_end"]
    assert client_end["people"] == 2
    assert client_end["columns"] == {"cv_sent": 1, "client_interview": 1}
    assert "nie zamyka kart" not in warned.json()["detail"]["message"]

    closed = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={
            "reason": "competitor",
            "acknowledge_active_cards": True,
            "end_client_cards": True,
        },
        headers=app_auth_headers,
    )
    assert closed.status_code == 200, closed.text

    for candidate_id in (sent, interview):
        assert await _latest(job_id, candidate_id) == (
            "rejected",
            "client",
            "client_chose_other",
        )
    assert (await _latest(job_id, internal))[0] == "verified"
    assert (await _latest(job_id, contract))[0] == "acceptance"


@pytest.mark.asyncio
async def test_close_budget_uses_request_closed_reason(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    job_id = await _create_draft_job(
        app_client, app_auth_headers, f"pytest-b5-budget-{uuid.uuid4().hex[:6]}"
    )
    sent = await _seed_candidate_in_job(job_id, "new", "cv_sent")
    closed = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={
            "reason": "budget",
            "notes": "Klient anulował projekt",
            "acknowledge_active_cards": True,
            "end_client_cards": True,
        },
        headers=app_auth_headers,
    )
    assert closed.status_code == 200, closed.text
    assert await _latest(job_id, sent) == ("rejected", "client", REQUEST_CLOSED)


@pytest.mark.asyncio
async def test_close_without_the_choice_leaves_cards(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    job_id = await _create_draft_job(
        app_client, app_auth_headers, f"pytest-b5-no-{uuid.uuid4().hex[:6]}"
    )
    sent = await _seed_candidate_in_job(job_id, "new", "cv_sent")
    closed = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": "competitor", "acknowledge_active_cards": True},
        headers=app_auth_headers,
    )
    assert closed.status_code == 200, closed.text
    assert (await _latest(job_id, sent))[0] == "cv_sent"


@pytest.mark.asyncio
async def test_filled_by_us_never_ends_cards_even_if_asked(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    job_id = await _create_draft_job(
        app_client, app_auth_headers, f"pytest-b5-won-{uuid.uuid4().hex[:6]}"
    )
    sent = await _seed_candidate_in_job(job_id, "new", "cv_sent")
    warned = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": "filled_by_us"},
        headers=app_auth_headers,
    )
    assert warned.status_code == 409
    assert warned.json()["detail"]["client_end"] is None
    closed = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={
            "reason": "filled_by_us",
            "acknowledge_active_cards": True,
            "end_client_cards": True,
        },
        headers=app_auth_headers,
    )
    assert closed.status_code == 200, closed.text
    assert (await _latest(job_id, sent))[0] == "cv_sent"


@pytest.mark.asyncio
async def test_ended_by_client_silent_passes_the_database_check() -> None:
    """0662 dopisuje `client_silent` do CHECK-a: inaczej automat wywróci zapis."""
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        check = await db.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_candidate_stages_ended_by'"
            )
        )
    assert "client_silent" in check
