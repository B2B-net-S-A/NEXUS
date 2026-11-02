"""Wysłani do klienta a to, co pokazał system (decyzja Artura z 02.11.2026)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_autofill_pool import JobAutofillPool
from app.services import sent_vs_system as svs


@pytest.mark.parametrize(
    "source, meta, expected",
    [
        ("system", {"system_view": {"view": "top20"}}, "system"),
        ("proposal", None, "proposal"),
        ("reassign", None, "reassign"),
        ("added_manual", {"system_view": {"view": "r21_40"}}, "r21_40"),
        ("added_manual", {"kind": "off_limits"}, "no_snapshot"),
        ("added_manual", None, "no_snapshot"),
        (None, {"system_view": {"view": "nieznane"}}, "no_snapshot"),
        ("added_manual", {"system_view": {"view": "proposal"}}, "no_snapshot"),
    ],
)
def test_category_trusts_source_then_snapshot(source, meta, expected):
    assert svs.category(source, meta, svs.MEASURED_SINCE) == expected


@pytest.mark.parametrize("source", ["system", "proposal", "reassign", "added_manual"])
def test_cards_from_before_the_measurement_never_count_as_shown(source):
    earlier = svs.MEASURED_SINCE - timedelta(seconds=1)
    assert (
        svs.category(source, {"system_view": {"view": "top20"}}, earlier)
        == "no_snapshot"
    )
    assert svs.category(source, None, None) == "no_snapshot"


def test_summary_percentages_skip_people_from_before_the_measurement():
    rows = [
        (1, "system"),
        (1, "top20"),
        (1, "below_pool"),
        (2, "outside_base"),
        (2, "no_snapshot"),
        (2, "no_snapshot"),
    ]
    out = svs.summarize(rows, {1: "A", 2: "B"})
    assert out["total"] == 6
    assert out["measured"] == 4
    assert out["shown_pct"] == 25.0
    assert out["outside_base_pct"] == 25.0
    assert out["missed_pct"] == 50.0
    assert [j["job_id"] for j in out["worst_jobs"]] == [1]
    assert out["worst_jobs"][0]["missed"] == 2


def test_summary_of_nothing_has_no_percentages():
    out = svs.summarize([], {})
    assert out["total"] == 0
    assert out["shown_pct"] is None
    assert out["segments"] == []


def test_view_keeps_other_entry_meta_fields():
    assert svs.with_system_view({"kind": "x"}, {"view": "top20"}) == {
        "kind": "x",
        "system_view": {"view": "top20"},
    }
    assert svs.with_system_view({"kind": "x"}, None) == {"kind": "x"}
    assert svs.with_system_view(None, None) is None


@pytest.mark.asyncio
async def test_system_views_place_people_by_pool_and_mark_new_ones():
    tag = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"SVS client {tag}")
        db.add(client)
        await db.flush()
        job = Job(title=f"SVS {tag}", client_id=client.id, status=JobStatus.published)
        old = now - timedelta(days=100)
        people = [
            Candidate(name="Wysoko", lastname=f"1-{tag}", created_at=old),
            Candidate(name="Daleko", lastname=f"2-{tag}", created_at=old),
            Candidate(name="Nowa", lastname=f"3-{tag}", created_at=now),
        ]
        fillers = [
            Candidate(name="Pula", lastname=f"{i}-{tag}", created_at=old)
            for i in range(25)
        ]
        db.add_all([job, *people, *fillers])
        await db.flush()
        db.add_all(
            [
                JobAutofillPool(
                    job_id=job.id,
                    candidate_id=people[0].id,
                    score=90,
                    run_id="r",
                    evidence={},
                ),
                JobAutofillPool(
                    job_id=job.id,
                    candidate_id=people[1].id,
                    score=50,
                    run_id="r",
                    evidence={},
                ),
                *[
                    JobAutofillPool(
                        job_id=job.id,
                        candidate_id=f.id,
                        score=70,
                        run_id="r",
                        evidence={},
                    )
                    for f in fillers
                ],
            ]
        )
        await db.flush()
        views = await svs.system_views(db, job, people, now=now)
        await db.rollback()
    assert views[people[0].id] == {"view": "top20", "position": 1, "pool_size": 27}
    assert views[people[1].id]["view"] == "r21_40"
    assert views[people[1].id]["position"] == 27
    assert views[people[2].id] == {"view": "outside_base"}


@pytest.mark.asyncio
async def test_snapshot_failure_does_not_block_the_add(monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("awaria")

    monkeypatch.setattr(svs, "system_views", boom)
    async with AsyncSessionLocal() as db:
        job = Job(title="SVS awaria", status=JobStatus.published, id=-1)
        assert (
            await svs.snapshot_for_add(
                db, job, [object()], now=datetime.now(timezone.utc)
            )
            == {}
        )
