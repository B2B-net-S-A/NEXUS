"""Etapy-odznaki Tablicy (22.09.2026): kto może ustawić „DZ ✓" i gdzie
istnieje „Gotowy do Cpro". Reguła nazw musi zgadzać się z frontem —
oba czytają `frontend/src/lib/__fixtures__/board-stage-cases.json`."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.user import UserRole
from app.services import board_stage_badges as badges

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "frontend/src/lib/__fixtures__/board-stage-cases.json"
)
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_dz_and_cpro_names_agree_with_the_frontend(case: dict) -> None:
    assert badges.is_dz_stage(case["name"]) is (case["badge"] == "dz")
    assert badges.is_cpro_stage(case["name"]) is (case["badge"] == "cpro")


def _user(*roles: UserRole) -> SimpleNamespace:
    return SimpleNamespace(has_any_role=lambda *wanted: any(r in roles for r in wanted))


@pytest.mark.parametrize(
    "role", [UserRole.admin, UserRole.delivery_lead, UserRole.head_of_recruitment]
)
def test_dz_badge_is_allowed_for_dl_hor_and_admin(role: UserRole) -> None:
    badges.ensure_badge_stage_allowed(
        _user(role), stage_name="Przepuszczony przez DZ", client_id=None
    )


def test_dz_badge_is_refused_for_a_recruiter() -> None:
    with pytest.raises(HTTPException) as err:
        badges.ensure_badge_stage_allowed(
            _user(UserRole.recruiter), stage_name="Przepuszczony przez DZ", client_id=1
        )
    assert err.value.status_code == 403


def test_cpro_badge_exists_only_for_nordea(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "77")
    recruiter = _user(UserRole.recruiter)
    badges.ensure_badge_stage_allowed(
        recruiter, stage_name="NORDEA: Wysłać do Cpro", client_id=77
    )
    assert badges.cpro_enabled_for_client(77) is True
    assert badges.cpro_enabled_for_client(15) is False
    with pytest.raises(HTTPException) as err:
        badges.ensure_badge_stage_allowed(
            recruiter, stage_name="Wysłać do Cpro", client_id=15
        )
    assert err.value.status_code == 422


def test_ordinary_stages_are_not_gated() -> None:
    for name in ("Zweryfikowany", "Screening", "Umowa podpisana", "Onboarding"):
        badges.ensure_badge_stage_allowed(
            _user(UserRole.recruiter), stage_name=name, client_id=None
        )
