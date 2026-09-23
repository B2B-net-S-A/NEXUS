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


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_badge_kind_agrees_with_the_frontend(case: dict) -> None:
    assert badges.stage_badge_kind(case["name"]) == case["badge"]


def _sd(id_: int, name: str, enum: str | None, terminal: bool = False):
    return SimpleNamespace(
        id=id_, name=name, legacy_enum_value=enum, is_terminal=terminal
    )


# Szablon „Default B2B" z produkcji (rekrutacje bez własnego szablonu).
DEFAULT_B2B = [
    _sd(10763, "Ogłoszenia", "posting"),
    _sd(1, "Nowi / Analiza CV", "new"),
    _sd(3, "Screening", "screening"),
    _sd(13, "Zweryfikowany", "verified"),
    _sd(823, "Przepuszczony przez DZ", "interview"),
    _sd(824, "Wysłać do Cpro", None),
    _sd(5, "CV Wysłane", "cv_sent"),
    _sd(752, "Preparation Meeting", None),
    _sd(6, "Interview Klient", "client_interview"),
    _sd(7, "Akceptacja", "acceptance"),
    _sd(753, "Umowa wysłana", None),
    _sd(1032, "Umowa podpisana", None),
    _sd(10, "Zatrudniony", "hired", terminal=True),
    _sd(9, "Onboarding", "onboarding"),
    _sd(11, "Odrzucony", "rejected", terminal=True),
    _sd(12, "Wycofany", "withdrawn", terminal=True),
]


@pytest.mark.parametrize(
    ("traffit_name", "enum", "expected"),
    [
        # Etapy szablonu Traffita „B2B" → kolumna tablicy „Default B2B".
        ("Kandydat Zweryfikowany", "verified", 13),
        ("Przepuszczony przez DZ", "interview", 823),
        ("NORDEA: Wysłać do Cpro", "screening", 824),
        ("Wysłany do Klienta", "cv_sent", 5),
        # Do 23.09.2026 te pięć (kod `interview`) dostawało „DZ ✓".
        ("Interview - Prep", "interview", 752),
        ("Prep - Followup", "interview", 752),
        ("Weryfikacja techniczna / Pre-Interview", "interview", 752),
        ("Kandydat przygotowany do spotkania z klientem", "interview", 752),
        ("Po Interview", "interview", 6),
        ("Interview u klienta", "client_interview", 6),
        ("Zaakceptowany (#41)", "acceptance", 7),
        ("Współpraca zakończona", "withdrawn", 12),
    ],
)
def test_traffit_stages_land_on_the_column_of_their_meaning(
    traffit_name: str, enum: str, expected: int
) -> None:
    target = badges.foreign_stage_target(traffit_name, enum, DEFAULT_B2B)
    assert target is not None and target.id == expected


def test_unknown_interview_stage_never_becomes_dz() -> None:
    # Obcy etap z kodem `interview` bez znanego znaczenia nie jest „DZ ✓” —
    # idzie do kubełka „poza szablonem” zamiast udawać zatwierdzenie.
    assert (
        badges.foreign_stage_target("Rozmowa techniczna", "interview", DEFAULT_B2B)
        is None
    )
    # Wiersz BEZ etapu zostaje przy starej regule (sam kod).
    assert badges.foreign_stage_target(None, "interview", DEFAULT_B2B).id == 823
