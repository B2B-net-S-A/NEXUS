"""Tests for `scripts/reembed_collections.py --only-missing`.

The interesting surface here is the Qdrant scroll that decides *what does not
need re-embedding*. Getting it wrong is expensive and silent in both
directions: truncate the scroll early and the script re-embeds thousands of
already-indexed rows (full Voyage spend, no error); loop on a repeated offset
and it never terminates.

DB-free — the scroll client is faked.
"""

from __future__ import annotations

import asyncio

import pytest

from scripts import reembed_collections


class _FakePoint:
    def __init__(self, pid: int) -> None:
        self.id = pid


class _FakeClient:
    """Minimal Qdrant stand-in that paginates like the real scroll API."""

    def __init__(self, ids: list[int], page: int = 3, **_kwargs) -> None:
        self._ids = ids
        self._page = page
        self.calls = 0

    def scroll(self, *, collection_name, limit, offset, with_payload, with_vectors):
        self.calls += 1
        start = 0 if offset is None else int(offset)
        chunk = self._ids[start : start + self._page]
        nxt = start + self._page
        # Real client returns None for next_page_offset on the last page.
        return [_FakePoint(i) for i in chunk], (nxt if nxt < len(self._ids) else None)


def _install(monkeypatch, client):
    import qdrant_client

    monkeypatch.setattr(qdrant_client, "QdrantClient", lambda **_kw: client)


def test_scroll_collects_every_page(monkeypatch):
    client = _FakeClient(list(range(10)), page=3)
    _install(monkeypatch, client)

    got = asyncio.run(reembed_collections._qdrant_point_ids("c"))

    assert got == set(range(10))
    assert client.calls == 4  # 3+3+3+1


def test_scroll_handles_exactly_full_last_page(monkeypatch):
    """Boundary: when the final page is exactly `page` long the real client
    still reports a next offset only if more points follow."""
    client = _FakeClient(list(range(9)), page=3)
    _install(monkeypatch, client)

    assert asyncio.run(reembed_collections._qdrant_point_ids("c")) == set(range(9))


def test_scroll_of_empty_collection_is_empty_not_an_error(monkeypatch):
    client = _FakeClient([], page=3)
    _install(monkeypatch, client)

    assert asyncio.run(reembed_collections._qdrant_point_ids("c")) == set()


def test_ids_are_ints_so_set_difference_against_db_ids_works(monkeypatch):
    """Qdrant can hand back ids as strings; a str/int mismatch would make the
    difference match nothing and quietly re-embed the entire collection."""

    class _StrIdClient(_FakeClient):
        def scroll(self, **kwargs):
            points, nxt = super().scroll(**kwargs)
            return [_FakePoint(str(p.id)) for p in points], nxt

    client = _StrIdClient([1, 2, 3], page=2)
    _install(monkeypatch, client)

    got = asyncio.run(reembed_collections._qdrant_point_ids("c"))
    assert got == {1, 2, 3}
    assert all(isinstance(i, int) for i in got)
    # The operation the script actually performs.
    assert [cid for cid in [1, 2, 3, 4] if cid not in got] == [4]


@pytest.mark.parametrize("total,page", [(1, 10), (10, 1), (100, 7)])
def test_scroll_terminates_for_various_page_sizes(monkeypatch, total, page):
    client = _FakeClient(list(range(total)), page=page)
    _install(monkeypatch, client)

    assert asyncio.run(reembed_collections._qdrant_point_ids("c")) == set(range(total))


# ── Orphan pruning ───────────────────────────────────────────────────────────
# Deletion carries a different risk from writing: a bug here removes vectors of
# LIVE candidates, and nothing in the app would report it — search would just
# quietly stop returning those people.


class _RecordingClient(_FakeClient):
    """Fake that also records what would be deleted."""

    def __init__(self, ids, page=1000, **kw):
        super().__init__(ids, page=page, **kw)
        self.deleted: list[int] = []

    def delete(self, *, collection_name, points_selector, wait):
        self.deleted.extend(points_selector.points)


def _install_recording(monkeypatch, client):
    import qdrant_client
    import qdrant_client.models as qm

    monkeypatch.setattr(qdrant_client, "QdrantClient", lambda **_kw: client)

    class _Sel:
        def __init__(self, points, shard_key=None):
            self.points = list(points)

    monkeypatch.setattr(qm, "PointIdsList", _Sel)
    return client


def test_delete_submits_every_id_in_chunks(monkeypatch):
    client = _install_recording(monkeypatch, _RecordingClient([]))
    n = asyncio.run(reembed_collections._delete_qdrant_points("c", list(range(2500))))
    assert n == 2500
    assert client.deleted == list(range(2500))  # nothing dropped at chunk seams


def test_delete_of_nothing_touches_qdrant_not_at_all(monkeypatch):
    client = _install_recording(monkeypatch, _RecordingClient([]))
    assert asyncio.run(reembed_collections._delete_qdrant_points("c", [])) == 0
    assert client.deleted == []
