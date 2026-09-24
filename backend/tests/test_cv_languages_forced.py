"""Generator v3: wybór „Tylko jedna wersja" / „Obie" (``languages``).

Kontrakty:

- ``both`` przy regule wymuszającej JEDEN język = 422 PRZED naliczeniem kwoty;
- ``both`` u klienta bez automatu drugiej wersji = worker robi obie, a pakiet
  centralny wymaga obu (ponowienie dorobi brakującą);
- ``one`` u klienta dwujęzycznego = sama wersja główna (``primary_only``);
- wybór równy zachowaniu reguły NIE zmienia snapshotu zadania — ręczna
  generacja bez ``languages`` zostaje bajt w bajt jak dotąd.
"""

# ruff: noqa: F811  (fixture `pv_client` importowana z sąsiedniego pliku)
from __future__ import annotations

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

import app.models  # noqa: F401
from app.api import cv_generator_b2b as api
from app.core.config import settings
from app.services.cv_generator_b2b.client_rules import CvRuleSnapshot
from tests.test_cv_auto_generate import _world
from tests.test_cv_auto_generate_central_policies import (
    _BILINGUAL,
    _documents,
    _generate_manually,
    _publish_policy,
    _run_worker,
    _stub_generation,
    _worker_harness,
)
from tests.test_pending_gate_removed import pv_client  # noqa: F401


def _rule(**overrides) -> CvRuleSnapshot:
    values = dict(
        filename_pattern=None,
        spaces_to_underscores=False,
        cv_language=None,
        requires_en_copy=False,
        requires_rodo_consent_block=False,
        auto_second_language=False,
    )
    values.update(overrides)
    return CvRuleSnapshot(**values)


# ── czysta reguła ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "rule, requested, expected",
    [
        (None, "both", "both"),
        (None, "one", "all"),
        (_rule(), "both", "both"),
        (_rule(), "one", "all"),
        (_rule(requires_en_copy=True, auto_second_language=True), "both", "all"),
        (
            _rule(requires_en_copy=True, auto_second_language=True),
            "one",
            "primary_only",
        ),
        (_rule(), "all", "all"),
        (_rule(), "primary_only", "primary_only"),
    ],
)
def test_form_choice_maps_to_the_worker_mode(rule, requested, expected):
    assert api._worker_languages(rule, "pl", requested) == expected


@pytest.mark.parametrize("forced", ["pl", "en"])
def test_both_is_refused_when_the_client_forces_one_language(forced):
    with pytest.raises(HTTPException) as caught:
        api._worker_languages(_rule(cv_language=forced), forced, "both")
    assert caught.value.status_code == 422
    assert "Obie" in caught.value.detail


def test_forced_second_language_never_overrides_a_forced_language():
    assert api._second_language(_rule(), "pl", force=True) == "en"
    assert api._second_language(_rule(), "en", force=True) == "pl"
    assert api._second_language(None, "pl", force=True) == "en"
    assert api._second_language(_rule(cv_language="pl"), "pl", force=True) is None
    # Bez wymuszenia — jak dotąd: tylko automat reguły.
    assert api._second_language(_rule(), "pl") is None


# ── przyjęcie żądania (prawdziwa wspólna ścieżka) ───────────────────────────


@pytest.mark.asyncio
async def test_both_with_forced_language_is_refused_before_any_charge(
    pv_client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "CV_CENTRAL_POLICIES_ENABLED", True)
    monkeypatch.setattr(api.limiter, "enabled", False)
    world = await _world()
    await _publish_policy(monkeypatch, world, cv_language="en")
    seen = _stub_generation(monkeypatch, world)

    response = await _generate_manually(pv_client, world, languages="both")
    assert response.status_code == 422, response.text
    assert "Obie" in response.json()["detail"]
    assert seen["charges"] == [] and seen["persisted"] == []
    assert await _documents(world) == []


@pytest.mark.asyncio
async def test_both_on_a_single_language_client_requires_both_in_the_package(
    pv_client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "CV_CENTRAL_POLICIES_ENABLED", True)
    monkeypatch.setattr(api.limiter, "enabled", False)
    world = await _world()
    await _publish_policy(monkeypatch, world)
    seen = _stub_generation(monkeypatch, world)

    response = await _generate_manually(pv_client, world, languages="both")
    assert response.status_code == 202, response.text
    [job] = seen["persisted"]
    assert job["inputs"]["languages"] == "both"
    [row] = await _documents(world)
    assert row.central_policy["required_languages"] == ["pl", "en"]


@pytest.mark.asyncio
async def test_one_on_a_bilingual_client_generates_only_the_primary(
    pv_client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "CV_CENTRAL_POLICIES_ENABLED", True)
    monkeypatch.setattr(api.limiter, "enabled", False)
    world = await _world()
    await _publish_policy(monkeypatch, world, **_BILINGUAL)
    seen = _stub_generation(monkeypatch, world)

    response = await _generate_manually(pv_client, world, languages="one")
    assert response.status_code == 202, response.text
    [job] = seen["persisted"]
    assert job["inputs"]["languages"] == "primary_only"
    # Pakiet nadal wymaga obu wersji — ponowienie dorobi drugą.
    [row] = await _documents(world)
    assert row.central_policy["required_languages"] == ["pl", "en"]


@pytest.mark.asyncio
async def test_default_snapshot_is_unchanged_by_the_new_fields(
    pv_client: AsyncClient, monkeypatch
):
    """Bez ``languages`` / ``position`` / ``champion_profile`` snapshot ma
    dokładnie dotychczasowe klucze (plus podpięcie szkicu przy etapie)."""
    monkeypatch.setattr(settings, "CV_CENTRAL_POLICIES_ENABLED", True)
    monkeypatch.setattr(api.limiter, "enabled", False)
    world = await _world()
    await _publish_policy(monkeypatch, world, **_BILINGUAL)
    seen = _stub_generation(monkeypatch, world)

    response = await _generate_manually(pv_client, world)
    assert response.status_code == 202, response.text
    [job] = seen["persisted"]
    assert set(job["inputs"]) == {
        "quota_user_id",
        "source",
        "rule_snapshot",
        "candidate_id",
        "stage_id",
        "language",
        "blind_cv",
        "user_id",
        "content_mode",
        "client_id",
        "project_ref",
        "consent_screenshot",
        "attach_stage_draft",
    }


# ── worker ──────────────────────────────────────────────────────────────────


async def test_worker_with_both_renders_the_second_language_without_the_rule(
    monkeypatch,
):
    _bilingual_rule, rendered, second_quota, pending = _worker_harness(
        monkeypatch, first_ready=False
    )
    await _run_worker(_rule(), languages="both")
    assert [call["language"] for call in rendered] == ["pl", "en"]
    assert second_quota.await_count == 1 and pending.await_count == 1


async def test_worker_without_both_keeps_a_single_language_client_single(
    monkeypatch,
):
    _bilingual_rule, rendered, second_quota, pending = _worker_harness(
        monkeypatch, first_ready=False
    )
    await _run_worker(_rule())
    assert [call["language"] for call in rendered] == ["pl"]
    second_quota.assert_not_awaited()
