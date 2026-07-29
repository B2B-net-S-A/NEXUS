"""Unit tests for the scheduled Traffit sync.

Covers the pure scheduling decisions, the delta-filter builder, the notes
promotion SQL shaping, and the TraffitClient X-Request-Filter behaviour
(including the HTTP-400 → full-scan fallback) via an httpx MockTransport.
No DB or network required.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx

from app.services.traffit.client import TraffitClient, TraffitConfig
from app.services.traffit.importer import (
    _PROMOTE_NOTES_SQL,
    TraffitImporter,
    WithdrawnReasonFallback,
)
from app.tasks.traffit_sync import should_run_daily, should_run_full

UTC = timezone.utc


# ── Scheduling decisions ─────────────────────────────────────────────────────


def test_daily_first_run_fires_immediately_regardless_of_hour():
    # No watermark → run now even before the configured hour (activation).
    early = datetime(2026, 6, 17, 0, 30, tzinfo=UTC)
    assert should_run_daily(early, None, hour_utc=2) is True


def test_daily_recent_run_is_blocked():
    now = datetime(2026, 6, 17, 3, 0, tzinfo=UTC)
    assert should_run_daily(now, now - timedelta(hours=2), hour_utc=2) is False


def test_daily_stale_run_after_hour_fires():
    now = datetime(2026, 6, 17, 3, 0, tzinfo=UTC)
    assert should_run_daily(now, now - timedelta(hours=25), hour_utc=2) is True


def test_daily_before_hour_blocked_when_not_first_run():
    now = datetime(2026, 6, 17, 1, 0, tzinfo=UTC)
    assert should_run_daily(now, now - timedelta(hours=25), hour_utc=2) is False


def test_full_only_on_configured_weekday():
    # 2026-06-21 is a Sunday (weekday 6).
    sunday = datetime(2026, 6, 21, 3, 0, tzinfo=UTC)
    wednesday = datetime(2026, 6, 17, 3, 0, tzinfo=UTC)
    assert should_run_full(sunday, None, weekday=6, hour_utc=2) is True
    assert should_run_full(wednesday, None, weekday=6, hour_utc=2) is False


def test_full_recent_run_blocked():
    sunday = datetime(2026, 6, 21, 3, 0, tzinfo=UTC)
    assert (
        should_run_full(sunday, sunday - timedelta(days=1), weekday=6, hour_utc=2)
        is False
    )


# ── Delta filter builder ─────────────────────────────────────────────────────


def test_delta_filter_none_when_no_since():
    assert TraffitImporter._delta_filter("updated_at", None) is None


def test_delta_filter_is_day_granular():
    since = datetime(2026, 6, 15, 14, 30, tzinfo=UTC)
    assert TraffitImporter._delta_filter("created_at", since) == {
        "created_at": {"value": "2026-06-15", "comparison": ">="}
    }


# ── Notes promotion SQL ──────────────────────────────────────────────────────


def test_promote_notes_sql_shape():
    # All Traffit note-bearing action types are selected.
    for action in (
        "traffit:Notatka",
        "traffit:Email",
        "traffit:Reply",
        "traffit:Rozmowa telefoniczna",
        "traffit:Spotkanie",
    ):
        assert action in _PROMOTE_NOTES_SQL
    # source_ref stamp + idempotency guard present.
    assert "'traffit:activity:' || a.external_id" in _PROMOTE_NOTES_SQL
    assert "NOT EXISTS" in _PROMOTE_NOTES_SQL


def test_promote_notes_since_clause_substitution():
    full = _PROMOTE_NOTES_SQL.replace("/*SINCE*/", "")
    delta = _PROMOTE_NOTES_SQL.replace("/*SINCE*/", "AND a.created_at >= :since")
    assert "/*SINCE*/" not in full and "/*SINCE*/" not in delta
    assert ":since" not in full
    assert "a.created_at >= :since" in delta


# ── TraffitClient X-Request-Filter ───────────────────────────────────────────


def _make_client(handler) -> TraffitClient:
    config = TraffitConfig(tenant="t", client_id="c", client_secret="s", throttle_rps=0)
    client = TraffitClient(config)
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client._token = "tok"
    client._token_expires_at = datetime.now(UTC) + timedelta(days=1)
    return client


async def test_get_paginated_sends_filter_header():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200, json=[{"id": 1}], headers={"X-Result-Total-Pages": "1"}
        )

    client = _make_client(handler)
    flt = {"updated_at": {"value": "2026-06-15", "comparison": ">="}}
    items = [
        x async for x in client.get_paginated("/employees/", page_size=100, filter_=flt)
    ]
    await client._http.aclose()

    assert items == [{"id": 1}]
    assert captured[0].headers["X-Request-Filter"] == json.dumps(flt)


async def test_get_paginated_falls_back_to_full_scan_on_400():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if "X-Request-Filter" in request.headers:
            return httpx.Response(400, text="filter rejected")
        return httpx.Response(
            200, json=[{"id": 2}], headers={"X-Result-Total-Pages": "1"}
        )

    client = _make_client(handler)
    flt = {"updated_at": {"value": "2026-06-15", "comparison": ">="}}
    items = [
        x async for x in client.get_paginated("/employees/", page_size=100, filter_=flt)
    ]
    await client._http.aclose()

    # Falls back and still yields data; first attempt had the filter (400),
    # retry dropped it.
    assert items == [{"id": 2}]
    assert "X-Request-Filter" in captured[0].headers
    assert "X-Request-Filter" not in captured[1].headers


# ── Watermark stats summary ──────────────────────────────────────────────────


def test_summarize_keeps_truncated_error_samples():
    # Bez sampli watermark mówi tylko "errors: N" — treść błędu przepada wraz
    # z logami kontenera po restarcie (prod nie ma trwałych logów). PR 0
    # integracji dwukierunkowej wymaga diagnozowalności z admin statusu.
    from app.tasks.traffit_sync import _summarize

    pd = {
        "processed": 100,
        "errors": 2,
        "error_samples": ["boom " * 100, "upsert stage ext=42: IntegrityError(...)"],
        "started_at": "2026-07-16T00:00:00",  # non-whitelisted → dropped
    }
    out = _summarize(pd)
    assert out["errors"] == 2
    assert len(out["error_samples"]) == 2
    assert all(len(s) <= 200 for s in out["error_samples"])
    assert "started_at" not in out


def test_summarize_omits_error_samples_when_clean():
    from app.tasks.traffit_sync import _summarize

    out = _summarize({"processed": 5, "errors": 0, "error_samples": []})
    assert "error_samples" not in out


def test_summarize_caps_sample_count_at_ten():
    from app.tasks.traffit_sync import _summarize

    out = _summarize({"errors": 20, "error_samples": [f"e{i}" for i in range(20)]})
    assert len(out["error_samples"]) == 10


# ── Pipelines: withdrawn wymaga rejection_reason (constraint 0068) ───────────


def test_fallback_reason_only_for_withdrawn():
    # ck_candidate_stages_withdrawn_requires_reason: stage='withdrawn' ⇒
    # rejection_reason_id NOT NULL. Bez fallbacku każdy ruch Traffit "wait"
    # padał na constraincie → stałe błędy fazy pipelines i permanentny
    # checks.traffit=degraded.
    fallback = WithdrawnReasonFallback(
        by_job={10: 77, 11: 78}, by_stage_def={20: 88}, default_id=99
    )
    fb = TraffitImporter._fallback_rejection_reason_id
    assert fb("withdrawn", 10, None, fallback) == 77
    assert fb("withdrawn", 11, None, fallback) == 78
    # Job bez template'u (99,6% prodowej bazy) NIE może już zwracać None —
    # spadamy na template definicji etapu, a w ostateczności na domyślny.
    # Szczegóły warstw: tests/test_traffit_pipelines_withdrawn_fallback.py.
    assert fb("withdrawn", 999, 20, fallback) == 88
    assert fb("withdrawn", None, None, fallback) == 99


def test_fallback_reason_never_for_other_stages():
    fallback = WithdrawnReasonFallback(
        by_job={10: 77}, by_stage_def={20: 88}, default_id=99
    )
    fb = TraffitImporter._fallback_rejection_reason_id
    for stage in ("rejected", "hired", "screening", "interview", "cv_sent"):
        assert fb(stage, 10, 20, fallback) is None, stage


def test_pipelines_upsert_carries_rejection_reason_and_never_clobbers():
    # Tripwire na SQL: INSERT musi nieść rejection_reason_id, a DO UPDATE
    # musi COALESCE'ować z ISTNIEJĄCĄ wartością (fallback nie może nadpisać
    # powodu wybranego przez rekrutera ani z rejection_backfill).
    import inspect

    # SQL mieszka w `_upsert_stage_row`, fallback liczy `import_pipelines`.
    upsert_src = inspect.getsource(TraffitImporter._upsert_stage_row)
    assert ":rejection_reason_id" in upsert_src
    assert "candidate_stages.rejection_reason_id" in upsert_src
    assert "_fallback_rejection_reason_id" in inspect.getsource(
        TraffitImporter.import_pipelines
    )
