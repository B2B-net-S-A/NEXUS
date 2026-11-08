"""QC-4, QC-5, QC-6 i QC-13 (audyt 08.11.2026)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import delete

from app.api.cv_qc import QcOverrideRequest
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.services import cv_finding_dismissals as dismissals
from app.services import cv_qc as qc
from app.services import dz_review as dz
from tests.test_board_tasks import _cleanup, _seed_world

_AT = datetime(2026, 11, 1, tzinfo=timezone.utc)


# ── QC-5: gotowe powody obejścia ─────────────────────────────────────────────


def _blocked() -> list[dict]:
    return [
        {
            "key": "critical_skills",
            "severity": "blocking",
            "status": "fail",
            "items": [{"key": "critical_skills|kafka|a"}],
        }
    ]


@pytest.mark.parametrize("code", ["confirmed_in_call", "requirement_not_applicable"])
def test_named_reasons_must_point_at_a_blocker(code: str) -> None:
    with pytest.raises(qc.OverrideAboutMissing):
        qc.override_about(_blocked(), [], code)
    assert qc.override_about(_blocked(), ["critical_skills|kafka|a"], code) == [
        "critical_skills|kafka|a"
    ]


def test_short_cv_reason_does_not_point_at_a_blocker() -> None:
    assert qc.override_about(_blocked(), [], "client_short_cv") == []


@pytest.mark.parametrize("reason", ["", "tak", "potwierdził"])
def test_confirmed_in_call_needs_the_candidates_words(reason: str) -> None:
    with pytest.raises(ValidationError):
        QcOverrideRequest(reason_code="confirmed_in_call", reason=reason)


def test_confirmed_in_call_with_words_is_accepted() -> None:
    body = QcOverrideRequest(
        reason_code="confirmed_in_call", reason="Pracował z Kafką 2 lata w banku"
    )
    assert body.reason_code == "confirmed_in_call"


# ── QC-13: „Inny powód” w „To nieprawda” ─────────────────────────────────────


@pytest.mark.parametrize("note", ["x", "bo tak", "a b c"])
def test_other_dismissal_needs_three_words(note: str) -> None:
    with pytest.raises(dismissals.DismissError):
        dismissals.validate_reason("other", note)


def test_other_dismissal_with_three_words_passes() -> None:
    assert dismissals.validate_reason("other", "klient tego nie wymaga") == (
        "other",
        "klient tego nie wymaga",
    )


# ── QC-4: starszy plik B2B ───────────────────────────────────────────────────

_NEW = _AT + timedelta(days=1)
_OLD = _AT - timedelta(days=30)


def test_older_file_is_offered_when_nothing_newer_exists() -> None:
    older = dz.older_b2b_row([(7, "Jan_B2B_Nordea.docx", _OLD, _OLD)], "Nordea", _AT)
    assert older == {
        "document_id": 7,
        "filename": "Jan_B2B_Nordea.docx",
        "at": _OLD.isoformat(),
        "same_client": True,
    }


def test_older_file_of_another_client_says_so() -> None:
    older = dz.older_b2b_row([(7, "Jan_B2B_PKO.docx", _OLD, _OLD)], "Nordea", _AT)
    assert older is not None and older["same_client"] is False


def test_no_offer_when_a_newer_file_exists() -> None:
    rows = [(7, "Jan_B2B.docx", _OLD, _OLD), (8, "Jan_B2B_2.docx", _NEW, _NEW)]
    assert dz.older_b2b_row(rows, "Nordea", _AT) is None


def test_older_cv_keeps_the_pair_held_but_says_what_to_do() -> None:
    data = qc.QcInput(
        must=[],
        nice=[],
        blocks=[],
        has_cv=False,
        bold_known=False,
        original_text="",
        experience=None,
        older_document={
            "document_id": 7,
            "filename": "Jan_B2B_Nordea.docx",
            "at": "2026-09-12T10:00:00+00:00",
            "same_client": True,
        },
    )
    checks = qc.compute_checks(data)
    cv = checks[0]
    assert cv["key"] == "cv_present" and cv["status"] == "manual"
    item = cv["items"][0]
    assert item["fix"] == "use_older_cv" and item["document"]["document_id"] == 7
    assert "12.09" in item["detail"] and "u tego klienta" in item["detail"]
    passed, blocking, _ = qc.summarize(checks)
    assert passed is False and blocking == 1


def test_no_older_file_is_still_a_plain_missing_cv() -> None:
    checks = qc.compute_checks(
        qc.QcInput(
            must=[],
            nice=[],
            blocks=[],
            has_cv=False,
            bold_known=False,
            original_text="",
            experience=None,
        )
    )
    assert checks[0]["status"] == "fail"


# ── QC-6: wskazanie ról wygasa po zmianie oryginału ──────────────────────────


async def _manual(world: dict, fp: str | None) -> None:
    details: dict = {"job_id": world["job_id"], "requirement": "Kafka", "roles": []}
    if fp is not None:
        details["original_fp"] = fp
    async with AsyncSessionLocal() as db:
        db.add(
            Activity(
                entity_type="candidate",
                entity_id=world["candidate_id"],
                action=qc.MANUAL_ROLES_ACTION,
                details=details,
            )
        )
        await db.commit()


async def _checks(world: dict, fp: str | None) -> dict:
    async with AsyncSessionLocal() as db:
        return await qc.manual_role_checks(
            db, world["candidate_id"], world["job_id"], original_fp=fp
        )


async def _wipe(world: dict) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(Activity).where(
                Activity.entity_id == world["candidate_id"],
                Activity.action == qc.MANUAL_ROLES_ACTION,
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_manual_roles_expire_when_the_original_changes() -> None:
    world = await _seed_world()
    try:
        await _manual(world, "orig-a")
        assert qc.manual_role_key("Kafka") in await _checks(world, "orig-a")
        assert await _checks(world, "orig-b") == {}
    finally:
        await _wipe(world)
        await _cleanup(world, [])


@pytest.mark.asyncio
async def test_entries_from_before_the_fingerprint_still_count() -> None:
    world = await _seed_world()
    try:
        await _manual(world, None)
        assert qc.manual_role_key("Kafka") in await _checks(world, "orig-b")
    finally:
        await _wipe(world)
        await _cleanup(world, [])


def test_original_fingerprint_ignores_whitespace_only_changes() -> None:
    assert qc.original_fingerprint("Jan  Kowalski\nJava") == qc.original_fingerprint(
        "Jan Kowalski Java"
    )
    assert qc.original_fingerprint("Jan Kowalski Java") != qc.original_fingerprint(
        "Jan Kowalski Kotlin"
    )
    assert qc.original_fingerprint("") is None


# ── QC-7: niesprawdzone krytyczne zostają u rekrutera ────────────────────────


def test_passed_with_manual_items_is_not_in_the_queue() -> None:
    from app.services import dl_send_queue as queue

    since = _AT - timedelta(days=5)
    today = (_AT + timedelta(days=1)).date()
    held = queue.readiness_of(
        since=since,
        qc_status="passed",
        ok_at=since,
        today=today,
        manual_items=["Kafka"],
    )
    assert held.ready is False
    plain = queue.readiness_of(
        since=since, qc_status="passed", ok_at=since, today=today
    )
    assert plain.ready is True
    # Rekruter przesunął mimo to: przepuszczenie trafia do kolejki.
    pushed = queue.readiness_of(
        since=since,
        qc_status="overridden",
        ok_at=since,
        today=today,
        manual_items=["Kafka"],
    )
    assert pushed.ready is True


def test_item_fields_survive_the_api_response_model() -> None:
    """Model odpowiedzi odcinał `document` i `candidate_gap`: „Użyj tego CV”
    nie miało czego wczytać, a okno QC nie wiedziało o luce kandydata."""
    from app.api.cv_qc import QcItem

    item = QcItem(
        document={"document_id": 7, "filename": "a.docx", "at": None},
        candidate_gap=True,
    ).model_dump()
    assert item["document"]["document_id"] == 7 and item["candidate_gap"] is True
