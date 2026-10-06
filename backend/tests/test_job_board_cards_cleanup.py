"""Karty scrapera — poprawki z audytu 06.10.2026 (PR 1).

* Q6: wynik w notatce automatu z HTML-em między dwukropkiem a liczbą
  (``score:&nbsp;71``) — bez tego karta wypadała jako
  ``automatch_note_unreadable`` z jednorazowej operacji;
* R7: propozycja z przeniesionej karty niesie datę otwarcia procesu, nie dzień
  przeniesienia (inaczej 1 160 osób naraz w kaflu „Nowi z ogłoszeń (7 dni)”);
* tryb ``delete``: karty na rekrutacjach ZAMKNIĘTYCH znikają drogą „Usuń
  z rekrutacji”, bez propozycji;
* zapis wymaga próby po starcie procesu i ``expected`` równego liczbie par.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.services import job_board_cards_to_proposals as conversion
from tests.test_job_board_proposals import (
    _qualifies,
    _scraper_world,
    _seed_admin,
    _world,
)

# ── bez bazy ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "content",
    [
        "Auto-match score: 71/100",
        "<p>Auto-match score:&nbsp;71/100</p>",
        "Auto-match score:&#160;71/100",
        "Auto-match score: 71/100",
        "Auto-match score: <strong>71</strong>/100",
    ],
)
def test_score_regex_sql_accepts_html_whitespace(content):
    # Wzorzec SQL (ARE Postgresa) czytany Pythonem: te same konstrukcje.
    assert re.search(conversion._SCORE_REGEX_SQL, content)
    assert conversion.entry_meta_from_note(content)["score"] == 71


def test_score_regex_sql_rejects_missing_number():
    assert not re.search(conversion._SCORE_REGEX_SQL, "Auto-match score: brak (X)")


def test_delete_mode_inverts_job_rule_and_skips_score():
    reasons = [r for r, _ in conversion.static_disqualifiers("delete")]
    assert reasons[0] == "job_not_closed"
    assert "job_not_eligible" not in reasons
    assert "automatch_note_unreadable" not in reasons
    assert "notes" in reasons and "stage_not_single_posting" in reasons
    convert = [r for r, _ in conversion.static_disqualifiers("convert")]
    assert "job_not_eligible" in convert and "job_not_closed" not in convert
    with pytest.raises(ValueError):
        conversion.static_disqualifiers("drop")


def test_dry_run_must_be_younger_than_the_process():
    after_start = conversion.PROCESS_STARTED_AT + timedelta(seconds=1)
    assert conversion.dry_run_is_fresh(
        {"finished_at": after_start.isoformat()}, now=after_start
    )
    before_start = conversion.PROCESS_STARTED_AT - timedelta(seconds=1)
    assert not conversion.dry_run_is_fresh(
        {"finished_at": before_start.isoformat()}, now=after_start
    )
    assert not conversion.dry_run_is_fresh(
        {"finished_at": after_start.isoformat()},
        now=after_start + timedelta(days=8),
    )
    assert not conversion.dry_run_is_fresh(None)
    assert not conversion.dry_run_is_fresh({"finished_at": "nie-data"})


def test_reserve_blocks_a_second_apply():
    assert conversion.reserve("delete")
    try:
        assert not conversion.reserve("delete")
        assert conversion.is_running("delete")
        assert not conversion.is_running("convert")
    finally:
        conversion.release("delete")
    assert not conversion.is_running("delete")


# ── z bazą (CI) ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scraper_note_with_nbsp_qualifies(app_client):
    _, _, _, _, process_id, _ = await _scraper_world(
        note=(
            "<p>Źródło: Pracuj.pl — oferta: X</p>"
            "<p>Auto-match score:&nbsp;71/100 (Jan Testowy)</p>"
        )
    )
    assert await _qualifies(process_id)


@pytest.mark.asyncio
async def test_moved_proposal_keeps_the_card_date(app_client):
    from app.core.database import AsyncSessionLocal
    from app.models.job_proposal import JobProposal
    from app.models.user import User

    actor_id, job_id, cand_id, process_id = await _world()
    opened = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE recruitment_processes SET opened_at = :o WHERE id = :p"),
            {"o": opened, "p": process_id},
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        actor = await db.get(User, actor_id)
        report = await conversion.apply(db, actor=actor, only_process_ids={process_id})
    assert report["counts"]["moved"] == 1, report
    async with AsyncSessionLocal() as db:
        proposal = await db.scalar(
            select(JobProposal).where(
                JobProposal.job_id == job_id, JobProposal.candidate_id == cand_id
            )
        )
        assert proposal.first_seen_at == opened


async def _qualifies_for_delete(process_id: int) -> bool:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        rules = await conversion.load_disqualifiers(db, "delete")
        row = (
            await db.execute(
                text(conversion.qualifying_sql(rules, one_pair=True)),
                {"process_id": process_id},
            )
        ).first()
        return row is not None


@pytest.mark.asyncio
async def test_delete_mode_removes_card_from_closed_job_without_proposal(app_client):
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.candidate_stage_removal import CandidateStageRemoval
    from app.models.job_proposal import JobProposal
    from app.models.recruitment_pipeline import CandidateStage
    from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
    from app.models.user import User

    actor_id, job_id, cand_id, process_id = await _world()
    # Opublikowana rekrutacja nie jest celem trybu „delete”.
    assert not await _qualifies_for_delete(process_id)
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE jobs SET status = 'closed' WHERE id = :id"), {"id": job_id}
        )
        await db.commit()
    assert await _qualifies_for_delete(process_id)
    assert not await _qualifies(process_id)

    async with AsyncSessionLocal() as db:
        actor = await db.get(User, actor_id)
        report = await conversion.apply(
            db, actor=actor, mode="delete", only_process_ids={process_id}
        )
    assert report["counts"]["deleted"] == 1, report
    assert report["mode"] == "delete"

    async with AsyncSessionLocal() as db:
        stages = (
            await db.scalars(
                select(CandidateStage).where(
                    CandidateStage.candidate_id == cand_id,
                    CandidateStage.job_id == job_id,
                )
            )
        ).all()
        assert stages == []
        process = await db.get(RecruitmentProcess, process_id)
        assert process.status == ProcessStatus.voided
        assert (
            await db.scalar(
                select(JobProposal.id).where(
                    JobProposal.job_id == job_id,
                    JobProposal.candidate_id == cand_id,
                    JobProposal.source == "job_board",
                )
            )
            is None
        )
        removal = await db.scalar(
            select(CandidateStageRemoval).where(
                CandidateStageRemoval.candidate_id == cand_id,
                CandidateStageRemoval.job_id == job_id,
            )
        )
        assert removal.reason == conversion.DELETE_REMOVAL_REASON
        activity = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "candidate",
                Activity.entity_id == cand_id,
                Activity.action == "removed_from_recruitment",
            )
        )
        assert activity is not None and activity.details["job_id"] == job_id
        details = await db.scalar(
            text("SELECT value FROM app_settings WHERE key = :k"),
            {"k": conversion.DELETE_DETAILS_KEY},
        )
        assert any(e["process_id"] == process_id for e in details["deleted"])
        actor = await db.get(User, actor_id)
        again = await conversion.apply(
            db, actor=actor, mode="delete", only_process_ids={process_id}
        )
    assert again["targets"] == 0


@pytest.mark.asyncio
async def test_apply_requires_matching_expected(app_client):
    from fastapi import HTTPException

    from app.api import admin_job_board_cards as route
    from app.core.database import AsyncSessionLocal

    admin = SimpleNamespace(id=await _seed_admin())
    async with AsyncSessionLocal() as db:
        await route.convert_integration_cards(
            current_user=admin, dry_run=True, mode="delete", expected=None, db=db
        )
    async with AsyncSessionLocal() as db:
        targets = await conversion.count_targets(db, "delete")
        for wrong in (None, targets + 1):
            with pytest.raises(HTTPException) as exc:
                await route.convert_integration_cards(
                    current_user=admin,
                    dry_run=False,
                    mode="delete",
                    expected=wrong,
                    db=db,
                )
            assert exc.value.status_code == 409
    assert not conversion.is_running("delete")
