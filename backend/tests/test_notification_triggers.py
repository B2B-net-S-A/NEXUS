"""Smoke tests for `app.services.notification_triggers`.

Pełne integration testy (z seedem kandydatów / calli / interview) wymagają
działającego kontenera postgres + wykonanej migracji 0029. Te testy weryfikują
sam interfejs: importy, sygnatury, domyślny empty-DB path (zero alertów).

W pełnym QA uruchamiaj przez `POST /api/admin/notifications/trigger-check` na
seedowanej bazie (patrz docs/phase13-notifications).
"""

from __future__ import annotations

import inspect

import pytest
import pytest_asyncio

from app.services import notification_triggers as nt


def test_exports_all_triggers():
    names = {
        "check_dl_stage_stale_6h",
        "check_client_feedback_eobd",
        "check_powercalling_kpi",
        "check_candidate_feedback_1h",
        "check_stage_stuck_7d",
        "check_post_interview_t15",
        "check_post_interview_t45",
        "check_post_interview_t2h_escalation",
    }
    for name in names:
        fn = getattr(nt, name)
        assert inspect.iscoroutinefunction(fn), f"{name} musi być async"


def test_run_all_triggers_keys():
    assert inspect.iscoroutinefunction(nt.run_all_triggers)
    sig = inspect.signature(nt.run_all_triggers)
    assert list(sig.parameters.keys()) == ["db", "now"]


def test_emit_signature_is_keyword_only_after_db():
    sig = inspect.signature(nt.emit)
    params = sig.parameters
    # user_id, title, message, ntype, ... są keyword-only (po `*, ` w sygnaturze).
    assert params["user_id"].kind == inspect.Parameter.KEYWORD_ONLY
    assert params["ntype"].kind == inspect.Parameter.KEYWORD_ONLY
    assert params["related_entity_id"].kind == inspect.Parameter.KEYWORD_ONLY


def test_date_as_int_packing():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    moment = datetime(2026, 4, 21, 12, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    assert nt._date_as_int(moment) == 20260421


@pytest_asyncio.fixture
async def empty_db():
    """Connect to the test DB via AsyncSessionLocal (requires DATABASE_URL + migrations)."""
    pytest.importorskip("asyncpg")
    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            yield db
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"DB unavailable for integration test: {exc}")


async def test_all_triggers_return_zero_when_no_data(empty_db):
    """Gdy baza pusta (lub bez pasujących rekordów), każdy trigger emituje 0."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    # Wtorek 21:00 Warsaw — poza oknami KPI/EOBD; stress testuje same queries.
    now = datetime(2026, 4, 21, 21, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    results = await nt.run_all_triggers(empty_db, now)
    # Nie zakładamy że baza jest pusta (test może lecieć na shared instance),
    # ale zwrócony słownik musi mieć wszystkie 5 kluczy z int values.
    assert set(results.keys()) == {
        "dl_stage_stale_6h",
        "stage_stuck_7d",
        "candidate_feedback_1h",
        "powercalling_kpi",
        "client_feedback_eobd",
        "post_interview_t15",
        "post_interview_t45",
        "post_interview_t2h_escalation",
    }
    assert all(isinstance(v, int) and v >= 0 for v in results.values())
    # Time-gated triggers muszą zwrócić 0 o 21:00.
    assert results["powercalling_kpi"] == 0
    assert results["client_feedback_eobd"] == 0
