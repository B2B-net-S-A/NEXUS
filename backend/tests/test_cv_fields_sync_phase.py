"""Faza ``candidates_cv_fields`` w nocnym syncu — kontrakty.

Domyka lukę świeżości po Fali 3: nowe/zmienione CV dostają pola strukturalne
w tę samą noc, w którą przyszły. Kontrakty, które muszą przeżyć:
- pełny bieg nie dokłada własnego okna (no-op z notatką, gdy nic nie czeka),
  ale domyka okna, których delta nie skończyła w budżecie (runda 6 audytu);
- selekcja = okno `updated_at` biegu ∩ scope filter (tekst + puste pola);
- ``backfill_cv_fields(candidate_ids=[])`` nie dotyka bazy i nie płaci.
"""

import pytest

from app.services.cv_field_backfill import backfill_cv_fields


class _NoopSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_backfill_with_empty_ids_touches_nothing():
    class ExplodingDb:
        def __getattr__(self, name):  # każda interakcja z DB = porażka testu
            raise AssertionError(f"backfill dotknął DB przez .{name}")

    stats = await backfill_cv_fields(ExplodingDb(), candidate_ids=[])
    assert stats["processed"] == 0 and stats["stopped_reason"] is None


def _fake_backfill(calls, *, stop_at=None, reason="limit"):
    """Backfill, który „przetwarza" okno do `stop_at` (last_id) i staje."""

    async def fake(
        db,
        *,
        after_id=0,
        updated_since=None,
        updated_before=None,
        limit=None,
        progress=None,
        **kw,
    ):
        calls.append(
            {
                "after_id": after_id,
                "since": updated_since,
                "until": updated_before,
                "limit": limit,
            }
        )
        stats = progress if progress is not None else {}
        stats.setdefault("processed", 0)
        stats["stopped_reason"] = None
        if stop_at is not None and len(calls) == 1:
            stats["processed"] += limit
            stats["last_id"] = stop_at
            stats["stopped_reason"] = reason
            return stats
        stats["processed"] += 1
        stats["stopped_reason"] = "done"
        return stats

    return fake
