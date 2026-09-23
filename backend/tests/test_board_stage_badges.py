"""Etapy szablonu a 8 kolumn Tablicy (24.09.2026): QC CV (dawniej „DZ”)
bez reguły roli, kolejka Cpro tylko u Nordei. Reguła nazw musi zgadzać się
z frontem — oba czytają `frontend/src/lib/__fixtures__/board-stage-cases.json`."""

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


def _is_qc_host(case: dict) -> bool:
    # Gospodarz kolumny QC CV nie ma znacznika — rozpoznaje go kolumna.
    return case["column"] == "cv_qc" and case["badge"] is None


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_qc_and_cpro_names_agree_with_the_frontend(case: dict) -> None:
    assert badges.is_qc_stage(case["name"]) is _is_qc_host(case)
    assert badges.is_cpro_stage(case["name"]) is (case["badge"] == "cpro")


@pytest.mark.parametrize(
    "name", ["QC CV", "qc cv", "Przepuszczony przez DZ", "Kontrola CV (QC)"]
)
def test_qc_stage_names(name: str) -> None:
    assert badges.is_qc_stage(name)
    assert badges.stage_badge_kind(name) == "qc"
    assert badges.board_column_for(name, "interview") == "cv_qc"


@pytest.mark.parametrize("name", ["Akwizycja", "Rozmowa techniczna", "QCA Team"])
def test_qc_is_matched_as_a_whole_word(name: str) -> None:
    assert not badges.is_qc_stage(name)


def _user(*roles: UserRole) -> SimpleNamespace:
    return SimpleNamespace(has_any_role=lambda *wanted: any(r in roles for r in wanted))


@pytest.mark.parametrize(
    "role",
    [
        UserRole.admin,
        UserRole.delivery_lead,
        UserRole.head_of_recruitment,
        UserRole.recruiter,
        UserRole.sourcer,
    ],
)
@pytest.mark.parametrize("stage_name", ["QC CV", "Przepuszczony przez DZ"])
def test_qc_stage_is_open_to_everyone_who_moves_cards(
    role: UserRole, stage_name: str
) -> None:
    # Do 23.09.2026 „DZ ✓" ustawiał wyłącznie DL/HoR — od 24.09 kontrolą jest
    # QC CV liczone przez kod, nie rola osoby, która przesuwa kartę.
    badges.ensure_badge_stage_allowed(_user(role), stage_name=stage_name, client_id=1)


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


# Odznaki z KODU etapu — backend rozpoznaje po nazwie wyłącznie pozostałe.
_ENUM_BADGES = {"posting", "acceptance"}


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_badge_kind_agrees_with_the_frontend(case: dict) -> None:
    if _is_qc_host(case):
        expected = "qc"
    else:
        expected = None if case["badge"] in _ENUM_BADGES else case["badge"]
    assert badges.stage_badge_kind(case["name"]) == expected


def test_column_order_has_eight_columns() -> None:
    assert badges.BOARD_COLUMN_ORDER == (
        "new",
        "screening",
        "verified",
        "cv_qc",
        "cv_sent",
        "client_interview",
        "contract",
        "hired",
    )
    assert badges.CLAIM_COLUMNS == {"new", "screening"}


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_board_column_agrees_with_the_frontend(case: dict) -> None:
    assert (
        badges.board_column_for(case["name"], case["stage"], category=case["category"])
        == case["column"]
    )


def _sd(id_: int, name: str, enum: str | None, terminal: bool = False):
    return SimpleNamespace(
        id=id_, name=name, legacy_enum_value=enum, is_terminal=terminal
    )


# Szablon „Default B2B" z produkcji (rekrutacje bez własnego szablonu) po
# migracji 0361: „Przepuszczony przez DZ" nazywa się „QC CV".
DEFAULT_B2B = [
    _sd(10763, "Ogłoszenia", "posting"),
    _sd(1, "Nowi / Analiza CV", "new"),
    _sd(3, "Screening", "screening"),
    _sd(13, "Zweryfikowany", "verified"),
    _sd(823, "QC CV", "interview"),
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
        # Traffit dalej nazywa etap „DZ" — trafia na „QC CV" po rodzaju.
        ("Przepuszczony przez DZ", "interview", 823),
        ("Screening", "screening", 3),
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


def test_unknown_interview_stage_never_becomes_qc() -> None:
    # Obcy etap z kodem `interview` bez znanego znaczenia nie ląduje w QC CV —
    # idzie do kubełka „poza szablonem” zamiast udawać kontrolę CV.
    assert (
        badges.foreign_stage_target("Rozmowa techniczna", "interview", DEFAULT_B2B)
        is None
    )
    # Wiersz BEZ etapu zostaje przy starej regule (sam kod).
    assert badges.foreign_stage_target(None, "interview", DEFAULT_B2B).id == 823
