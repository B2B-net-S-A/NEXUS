"""Unit tests for the saved-search alert scanner helpers (pure functions —
no DB / no ASGI client needed)."""

import pytest

from app.tasks.saved_search_alerts import (
    build_base_params,
    build_link,
    polish_candidates,
)


class TestBuildBaseParams:
    def test_forces_paging_and_sort(self):
        params = build_base_params({"q": "python"})
        assert params["page_size"] == 100
        assert params["sort"] == "newest"
        assert params["q"] == "python"
        # Page number / updated_after are added by the pager, not here.
        assert "page" not in params
        assert "updated_after" not in params

    def test_drops_ui_extras_watermarks_and_nulls(self):
        stored = {
            "q": "java",
            "include_match_stats": True,
            "include_active_recruitments": True,
            "include_last_activity": True,
            "match_threshold": 35,
            "profile_id": 2,
            "page": 7,
            "page_size": 20,
            "sort": "name",
            "id_after": 5,
            "updated_after": "2026-01-01T00:00:00Z",
            "location": None,
        }
        params = build_base_params(stored)
        for key in (
            "include_match_stats",
            "include_active_recruitments",
            "include_last_activity",
            "match_threshold",
            "profile_id",
            "id_after",
            "updated_after",
            "location",
        ):
            assert key not in params
        # Scanner-owned keys win over stored values.
        assert params["sort"] == "newest"
        assert params["page_size"] == 100

    def test_keeps_list_params_for_repeated_query_encoding(self):
        params = build_base_params(
            {"status": ["active", "passive"], "skills_any": ["python|java"]}
        )
        assert params["status"] == ["active", "passive"]
        assert params["skills_any"] == ["python|java"]


class TestPolishCandidates:
    @pytest.mark.parametrize(
        ("n", "expected"),
        [
            (1, "1 nowy kandydat"),
            (2, "2 nowi kandydaci"),
            (4, "4 nowi kandydaci"),
            (5, "5 nowych kandydatów"),
            (12, "12 nowych kandydatów"),
            (14, "14 nowych kandydatów"),
            (22, "22 nowi kandydaci"),
            (100, "100 nowych kandydatów"),
        ],
    )
    def test_plural_forms(self, n, expected):
        assert polish_candidates(n) == expected


class TestBuildLink:
    def test_with_stored_querystring(self):
        link = build_link({"qs": "q=python&status=active"}, search_id=7)
        assert link == "/candidates?q=python&status=active&ss=7"

    def test_without_querystring(self):
        assert build_link({}, search_id=7) == "/candidates?ss=7"
        assert build_link(None, search_id=7) == "/candidates?ss=7"
        assert build_link({"qs": ""}, search_id=7) == "/candidates?ss=7"


class _FakeResponse:
    def __init__(self, n: int):
        self._n = n

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"items": [{"id": i} for i in range(self._n)]}


class _FakeClient:
    def __init__(self, sizes: list[int]):
        self.sizes = list(sizes)
        self.pages: list[int] = []

    async def get(self, _url, *, params, headers):
        self.pages.append(params["page"])
        return _FakeResponse(self.sizes.pop(0))


class TestReplayMatchItems:
    """Runda 8 (R8-N10-3): pager mówi, czy obejrzał ogon."""

    @pytest.mark.asyncio
    async def test_complete_when_last_page_is_short(self):
        from app.tasks.saved_search_alerts import _replay_match_items

        client = _FakeClient([100, 100, 3])
        items, truncated = await _replay_match_items(client, "t", {}, max_pages=5)
        assert (len(items), truncated, client.pages) == (203, False, [1, 2, 3])

    @pytest.mark.asyncio
    async def test_truncated_when_cap_reached(self):
        from app.tasks.saved_search_alerts import _replay_match_items

        client = _FakeClient([100, 100, 100])
        items, truncated = await _replay_match_items(client, "t", {}, max_pages=2)
        assert (len(items), truncated) == (200, True)

    def test_default_cap_covers_whole_database(self):
        from app.tasks import saved_search_alerts as mod

        # 20 stron = 2000 trafień dawało niepełną linię bazową (fałszywe alerty).
        assert mod._MAX_PAGES * mod._PAGE_SIZE >= 100_000
