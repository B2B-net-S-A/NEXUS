"""Generator v3: auto-CV dla PKO BP pod centralnymi regułami — prawdziwy Postgres.

- brak zrzutu zgody NIE jest powodem pominięcia: dokument powstaje, a jego
  pobranie blokuje ``cv_consent_gate`` do czasu dołączenia zgody;
- numer zapytania wynika z rekrutacji (numer ZOB) i trafia do generacji
  oraz stempla polityki — ten sam, który sprawdza gotowość pakietu;
- bez centralnych reguł zrzut zgody jest wymogiem generacji — automat pomija.
"""

from __future__ import annotations

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.job import Job
from app.services import cv_auto_generate as auto
from app.services import cv_consent_gate
from tests.test_cv_auto_generate import _events, _world
from tests.test_cv_auto_generate_central_policies import (
    _assert_skipped,
    _documents,
    _publish_policy,
    _run_automation,
    _stub_generation,
)

PKO = dict(
    cv_language="pl",
    requires_rodo_consent_block=True,
    require_project_ref=True,
    filename_pattern="ZOB-{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}",
)


async def _with_reference(world: dict, title: str) -> None:
    async with AsyncSessionLocal() as db:
        (await db.get(Job, world["job_id"])).title = title
        await db.commit()


async def test_pko_auto_cv_is_generated_without_consent_and_blocked_at_download(
    monkeypatch,
):
    monkeypatch.setattr(settings, "CV_CENTRAL_POLICIES_ENABLED", True)
    world = await _world()
    await _with_reference(world, "Java Developer ZOB 4521")
    await _publish_policy(monkeypatch, world, **PKO)
    seen = _stub_generation(monkeypatch, world)

    queued = await _run_automation(world)
    assert queued is not None
    [job] = seen["persisted"]
    assert job["inputs"]["project_ref"] == "4521"
    assert job["inputs"]["consent_screenshot"] is None
    assert seen["charges"] == [world["user_id"]]
    [row] = await _documents(world)
    assert row.origin == "auto"
    assert row.central_policy["project_ref"] == "4521"
    assert row.central_policy["requires_rodo_consent_block"] is True
    # Pobranie czeka na zgodę.
    assert cv_consent_gate.consent_missing(row) is True
    assert [e.action for e in await _events(world["job_id"])] == [auto.ACTION_STARTED]


async def test_pko_without_a_reference_is_still_skipped(monkeypatch):
    monkeypatch.setattr(settings, "CV_CENTRAL_POLICIES_ENABLED", True)
    world = await _world()
    await _publish_policy(monkeypatch, world, **PKO)
    seen = _stub_generation(monkeypatch, world)

    assert await _run_automation(world) is None
    await _assert_skipped(world, seen, reason="client_rule_inputs_missing")


async def test_without_central_policies_consent_is_a_generation_input(monkeypatch):
    monkeypatch.setattr(settings, "CV_CENTRAL_POLICIES_ENABLED", True)
    world = await _world()
    await _with_reference(world, "Java Developer ZOB 4521")
    await _publish_policy(monkeypatch, world, **PKO)
    monkeypatch.setattr(settings, "CV_CENTRAL_POLICIES_ENABLED", False)
    seen = _stub_generation(monkeypatch, world)

    assert await _run_automation(world) is None
    await _assert_skipped(world, seen, reason="consent_screenshot_required")
