"""Regression tests for the NEXUS read-only viewer boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.models.user import UserRole


def _viewer() -> SimpleNamespace:
    return SimpleNamespace(
        id=77,
        email="viewer@example.com",
        get_all_roles=lambda: {UserRole.user},
    )


@pytest.mark.asyncio
async def test_viewer_branded_cv_get_renders_without_initializing_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import candidate_stage_cv as api

    csv = SimpleNamespace(
        id=8,
        candidate_stage_id=9,
        candidate_id=10,
        job_id=11,
        branded_status="none",
        branded_draft_html=None,
        branded_template=None,
        branded_language=None,
        branded_updated_at=None,
        branded_updated_by=None,
        branded_finalized_at=None,
        branded_finalized_by=None,
        branded_snapshot_filename=None,
    )
    db = SimpleNamespace(add=Mock(), commit=AsyncMock(), refresh=AsyncMock())
    monkeypatch.setattr(api, "_load_csv_for_stage", AsyncMock(return_value=csv))
    monkeypatch.setattr(
        api,
        "_load_candidate_and_job",
        AsyncMock(return_value=(SimpleNamespace(), None)),
    )
    monkeypatch.setattr(api, "_generate_cv_html", Mock(return_value="<p>preview</p>"))

    response = await api.get_branded_cv(9, _viewer(), db)

    assert response.status == "draft"
    assert response.content_html == "<p>preview</p>"
    assert response.rendered_from_default is True
    assert csv.branded_status == "none"
    assert csv.branded_draft_html is None
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_viewer_contract_get_renders_without_initializing_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import contracts as api

    contract = SimpleNamespace(
        id=21,
        contract_type=SimpleNamespace(value="b2b"),
        draft_content_html=None,
        draft_template_id=None,
        draft_updated_at=None,
        draft_updated_by=None,
    )
    template = SimpleNamespace(
        id=22,
        name="Default",
        contract_type="b2b",
        is_default=True,
    )
    db = SimpleNamespace(add=Mock(), flush=AsyncMock(), scalar=AsyncMock())
    monkeypatch.setattr(
        api, "_load_contract_with_relations", AsyncMock(return_value=contract)
    )
    monkeypatch.setattr(
        api, "_list_templates_for_contract_type", AsyncMock(return_value=[template])
    )
    monkeypatch.setattr(
        api, "_render_draft_body", Mock(return_value="<p>preview</p>")
    )

    response = await api.get_contract_draft(21, _viewer(), db)

    assert response.content_html == "<p>preview</p>"
    assert response.template_id == 22
    assert response.rendered_from_default is True
    assert contract.draft_content_html is None
    assert contract.draft_template_id is None
    db.add.assert_not_called()
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_viewer_champion_profile_get_does_not_mark_notifications_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import jobs as api

    job = SimpleNamespace(id=31, title="Security", champion_profile={"ok": True})
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=job),
        execute=AsyncMock(),
        commit=AsyncMock(),
    )

    response = await api.get_champion_profile(31, _viewer(), db)

    assert response["champion_profile"] == {"ok": True}
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_viewer_marketplace_list_never_creates_singleton_or_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import marketplace as api

    list_candidates = AsyncMock(return_value=([], 0))
    monkeypatch.setattr(api, "list_marketplace_candidates", list_candidates)
    db = SimpleNamespace(commit=AsyncMock())

    response = await api.list_candidates(
        current_user=_viewer(),
        db=db,
        page=1,
        page_size=50,
        q=None,
        source_event=None,
    )

    assert response.total == 0
    assert list_candidates.await_args.kwargs["create_pool_if_missing"] is False
    db.commit.assert_not_awaited()
