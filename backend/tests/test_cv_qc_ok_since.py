"""QC-1 i QC-3 (audyt 08.11.2026): czas oczekiwania i pozycje „sprawdź ręcznie”."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.cv_qc_run import CvQcRun
from app.services import cv_qc as qc
from tests.test_board_tasks import _cleanup, _seed_world

_PASSING = [
    {
        "key": "dates",
        "label": "Daty",
        "severity": "warning",
        "status": "pass",
        "summary": "OK",
        "items": [],
    }
]
_FAILING = [{**_PASSING[0], "severity": "blocking", "status": "fail"}]


async def _old_run(world: dict, *, fp: str, passed: bool, at: datetime) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CvQcRun(
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                cv_fingerprint=fp,
                passed=passed,
                blocking_failed=0 if passed else 1,
                warnings_count=0,
                result={
                    "checks": _PASSING if passed else _FAILING,
                    "qc_version": "qc-truth-4",
                },
                created_at=at,
            )
        )
        await db.commit()


async def _store(world: dict, *, fp: str, checks: list[dict]) -> None:
    async with AsyncSessionLocal() as db:
        await qc._store_run(
            db,
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            stage_id=None,
            fp=fp,
            checks=checks,
            cv_source="branded_draft",
            user_id=None,
        )
        await db.commit()


async def _ok_at(world: dict) -> datetime | None:
    pair = (world["candidate_id"], world["job_id"])
    async with AsyncSessionLocal() as db:
        return (await qc.pair_statuses(db, [pair]))[pair]["ok_at"]


async def _wipe(world: dict) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CvQcRun).where(CvQcRun.candidate_id == world["candidate_id"])
        )
        await db.commit()


@pytest.mark.asyncio
async def test_next_passing_run_of_the_same_cv_keeps_the_waiting_time() -> None:
    """Otwarcie przeglądu DL po zmianie reguł nie zmienia „czeka 3 dni”."""
    world = await _seed_world()
    three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
    try:
        await _old_run(world, fp="cv-a", passed=True, at=three_days_ago)
        await _store(world, fp="cv-a", checks=_PASSING)
        assert await _ok_at(world) == three_days_ago
        # Kolejny przebieg czyta już `ok_since` z poprzedniego, nie jego datę.
        await _store(
            world,
            fp="cv-a",
            checks=[{**_PASSING[0], "summary": "Inny wynik, ta sama para"}],
        )
        assert await _ok_at(world) == three_days_ago
    finally:
        await _wipe(world)
        await _cleanup(world, [])


@pytest.mark.asyncio
async def test_new_cv_starts_the_waiting_time_again() -> None:
    world = await _seed_world()
    three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
    try:
        await _old_run(world, fp="cv-a", passed=True, at=three_days_ago)
        await _store(world, fp="cv-b", checks=_PASSING)
        ok_at = await _ok_at(world)
        assert ok_at is not None and ok_at > three_days_ago + timedelta(days=2)
    finally:
        await _wipe(world)
        await _cleanup(world, [])


@pytest.mark.asyncio
async def test_run_after_a_failed_one_starts_the_waiting_time_again() -> None:
    """Czas poprawek rekrutera się nie liczy (`pair_statuses`)."""
    world = await _seed_world()
    three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
    try:
        await _old_run(world, fp="cv-a", passed=False, at=three_days_ago)
        await _store(world, fp="cv-a", checks=_PASSING)
        ok_at = await _ok_at(world)
        assert ok_at is not None and ok_at > three_days_ago + timedelta(days=2)
    finally:
        await _wipe(world)
        await _cleanup(world, [])


def test_manual_items_count_requirements_not_checks() -> None:
    critical = "Umiejętności krytyczne są w CV i opisane w rolach"
    assert qc.manual_items(
        ["critical_skills"], [critical], ["Kafka", "AWS", "Kafka", "Terraform"]
    ) == ["Kafka", "AWS", "Terraform"]


def test_manual_items_name_the_consent_and_keep_other_checks() -> None:
    assert qc.manual_items(
        ["client_rules", "no_unsupported"],
        ["Reguły klienta", "Nic spoza oryginału"],
        [],
    ) == [qc.CONSENT_MANUAL_ITEM, "Nic spoza oryginału"]


def test_manual_items_keep_the_check_when_no_role_is_known() -> None:
    """Odczyt bez ról: nie ma czego wymienić, zostaje nazwa sprawdzenia."""
    assert qc.manual_items(["critical_skills"], ["Krytyczne"], []) == ["Krytyczne"]


def test_requirement_patterns_refresh_after_a_dictionary_change() -> None:
    """W2: wzorce w cache procesu nie mogą przeżyć zmiany słownika."""
    from app.services import dz_review as dz
    from tests.taxonomy_fixture import hydrated_taxonomy

    assert not any(p.search("Plughwork") for p in dz._patterns("Xyzzy"))
    with hydrated_taxonomy({"Xyzzy": ("devops", ("plughwork",))}):
        assert any(p.search("Plughwork") for p in dz._patterns("Xyzzy"))
    assert not any(p.search("Plughwork") for p in dz._patterns("Xyzzy"))


def _action_setup(monkeypatch, stored_fp: str, version: str = qc.QC_VERSION) -> list:
    """W3: fałszywe źródła i przebieg; ``evaluate`` tylko liczy wywołania."""
    calls: list = []
    src = SimpleNamespace(
        generated={"source": "branded_draft"},
        blocks=[],
        candidate=SimpleNamespace(id=1),
        job=SimpleNamespace(id=2),
    )
    latest = SimpleNamespace(
        cv_fingerprint=stored_fp,
        result={"qc_version": version, "checks": [{"key": "stored"}]},
    )

    async def load(db, stage):
        return src

    async def run(db, candidate_id, job_id):
        return latest

    async def evaluate(db, stage, *, src=None):
        calls.append(src)
        return src, [{"key": "live"}], ""

    monkeypatch.setattr(qc, "_load_sources", load)
    monkeypatch.setattr(qc, "_latest_run", run)
    monkeypatch.setattr(qc, "fingerprint", lambda blocks: "cv-a")
    monkeypatch.setattr(qc, "evaluate", evaluate)
    return calls


@pytest.mark.asyncio
async def test_action_validates_on_the_saved_run_of_the_same_cv(monkeypatch) -> None:
    calls = _action_setup(monkeypatch, "cv-a")
    _, checks = await qc._action_checks(None, None)
    assert checks == [{"key": "stored"}] and calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored_fp", "version"), [("cv-b", qc.QC_VERSION), ("cv-a", "qc-truth-4")]
)
async def test_action_counts_live_when_cv_or_rules_changed(
    monkeypatch, stored_fp: str, version: str
) -> None:
    calls = _action_setup(monkeypatch, stored_fp, version)
    _, checks = await qc._action_checks(None, None)
    assert checks == [{"key": "live"}] and len(calls) == 1
