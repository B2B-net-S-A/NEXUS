"""Reguła „kto widzi listę” (0520) — część czysta, bez bazy.

Trasy na żywej bazie: ``test_candidate_lists_api.py``.
"""

from __future__ import annotations

from app.models.talent_pool import TalentPool
from app.services import talent_pool_visibility as visibility


def _pool(*, personal: bool, team: bool, owner: int | None = 7) -> TalentPool:
    return TalentPool(
        name="x", is_personal=personal, team_visible=team, created_by=owner
    )


def test_company_pool_is_public_even_with_team_visible_false() -> None:
    # Pula firmowa nie ma „Tylko ja” — flaga liczy się tylko przy osobistej.
    pool = _pool(personal=False, team=False)
    assert visibility.is_public(pool)
    assert visibility.is_visible_to(pool, None)


def test_personal_team_list_is_visible_to_everyone() -> None:
    assert visibility.is_visible_to(_pool(personal=True, team=True), 99)


def test_private_list_only_for_owner() -> None:
    pool = _pool(personal=True, team=False, owner=7)
    assert not visibility.is_public(pool)
    assert visibility.is_visible_to(pool, 7)
    assert not visibility.is_visible_to(pool, 8)
    assert not visibility.is_visible_to(pool, None)


def test_private_list_without_owner_is_visible_to_nobody() -> None:
    assert not visibility.is_visible_to(
        _pool(personal=True, team=False, owner=None), None
    )


def test_visible_clause_mentions_owner_only_when_viewer_known() -> None:
    anonymous = str(visibility.visible_clause(None))
    viewer = str(visibility.visible_clause(5))
    assert "created_by" not in anonymous
    assert "created_by" in viewer
