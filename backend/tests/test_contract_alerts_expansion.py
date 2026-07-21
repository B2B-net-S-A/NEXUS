"""Smoke tests for contract_alerts expansion — 90d threshold + equipment + client
order — plus P1-NOTIFY-01: episode-aware ending dedup + Slack 2xx-only accounting."""

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

from app.tasks.contract_alerts import THRESHOLDS_DAYS

_TODAY = date.today()


def test_90d_threshold_present():
    assert 90 in THRESHOLDS_DAYS
    # Ordered from longest horizon to shortest is not required, but 7 should
    # remain the tightest threshold.
    assert 7 in THRESHOLDS_DAYS
    assert min(THRESHOLDS_DAYS) == 7
    assert max(THRESHOLDS_DAYS) == 90


async def test_alerts_cycle_stats_keys_include_expansion():
    """run_contract_alerts_cycle should expose keys for the new triggers."""
    from app.tasks.contract_alerts import run_contract_alerts_cycle

    stats = await run_contract_alerts_cycle()
    # Only the *shape* is asserted — actual counts depend on DB data.
    for key in (
        "promoted_ending",
        "promoted_ended",
        "notifications_created",
        "compliance_alerts",
        "equipment_return_alerts",
        "client_order_alerts",
        "slack_sent",
    ):
        assert key in stats


# ── P1-NOTIFY-01: episode-aware ending dedup ─────────────────────────────────


def test_end_date_from_title_parses_new_and_ignores_legacy():
    """The deadline parser reads ``[Nd|<date>]`` and ignores legacy ``[Nd]`` titles."""
    from app.tasks.contract_alerts import _end_date_from_title

    assert _end_date_from_title("[30d|2026-09-01] Kontrakt #5 wygasa") == "2026-09-01"
    assert _end_date_from_title("[7d|2026-01-15] Kontrakt #9 wygasa") == "2026-01-15"
    # Legacy titles carry no deadline → None, so they never suppress a fresh episode.
    assert _end_date_from_title("[30d] Kontrakt #5 wygasa") is None
    assert _end_date_from_title(None) is None
    assert _end_date_from_title("no brackets here") is None


async def _seed_staff_user() -> int:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    u = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        staff = User(
            email=f"alert-{u}@example.com",
            password_hash=hash_password("x"),
            name="DL",
            role=UserRole.delivery_lead,
            is_active=True,
        )
        db.add(staff)
        await db.commit()
        return staff.id


async def test_prefilter_is_episode_aware():
    """A ``[30d|E1]`` notification marks only the ``(cid, E1)`` episode as notified.

    The buggy pre-filter keyed on contract_id alone, so once a contract had any
    ``[30d]`` notification it was suppressed forever. Episode-aware, a bulk-extend to
    a new deadline E2 leaves ``(cid, E2)`` fresh and re-arms the alert.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.notification import Notification, NotificationType
    from app.tasks.contract_alerts import _contract_ids_already_notified

    # A high, effectively-unique contract id so the assertions are isolated from any
    # other rows in the shared test DB.
    cid = 900_000_000 + (uuid.uuid4().int % 10_000_000)
    e1 = (_TODAY + timedelta(days=10)).isoformat()  # prior deadline
    e2 = (_TODAY + timedelta(days=30)).isoformat()  # extended deadline
    staff_id = await _seed_staff_user()
    async with AsyncSessionLocal() as db:
        db.add(
            Notification(
                user_id=staff_id,
                title=f"[30d|{e1}] Kontrakt #{cid} wygasa",
                message="x",
                link=f"/contracts/{cid}",
                notification_type=NotificationType.contract_ending,
            )
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        already = await _contract_ids_already_notified(db, 30)

    assert (cid, e1) in already, "the prior episode must count as already-notified"
    assert (cid, e2) not in already, "a new deadline must stay fresh (re-arms)"


async def test_claim_alert_rearms_on_new_deadline():
    """The atomic ledger is episode-keyed: a new end_date re-arms the same threshold."""
    from app.core.database import AsyncSessionLocal
    from app.tasks.contract_alerts import _claim_alert

    cid = 900_000_000 + (uuid.uuid4().int % 10_000_000)
    e1 = (_TODAY + timedelta(days=10)).isoformat()
    e2 = (_TODAY + timedelta(days=30)).isoformat()
    async with AsyncSessionLocal() as db:
        assert await _claim_alert(db, f"ending:30:{cid}:{e1}") is True
        assert await _claim_alert(db, f"ending:30:{cid}:{e1}") is False
        # A different deadline is a new episode → the claim succeeds again (re-arms).
        assert await _claim_alert(db, f"ending:30:{cid}:{e2}") is True
        await db.commit()


# ── P1-NOTIFY-01: Slack summary counts only 2xx as sent ──────────────────────


class _FakeSlackClient:
    """Async-context httpx.AsyncClient stand-in returning a fixed status code."""

    def __init__(self, status_code: int):
        self._status_code = status_code

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, *args, **kwargs):
        import httpx

        # A request must be attached for Response.raise_for_status() to work.
        return httpx.Response(self._status_code, request=httpx.Request("POST", url))


async def test_slack_summary_returns_false_on_non_2xx(monkeypatch):
    """A 4xx/5xx webhook response must return False so slack_sent stays 0."""
    from app.tasks import contract_alerts

    monkeypatch.setattr(contract_alerts.httpx, "AsyncClient", _FakeSlackClient(500))
    events = [(30, SimpleNamespace(id=1, end_date=_TODAY))]
    ok = await contract_alerts._post_slack_summary("http://hook.example", events)
    assert ok is False


async def test_slack_summary_returns_true_on_2xx(monkeypatch):
    from app.tasks import contract_alerts

    monkeypatch.setattr(contract_alerts.httpx, "AsyncClient", _FakeSlackClient(200))
    events = [(30, SimpleNamespace(id=1, end_date=_TODAY))]
    ok = await contract_alerts._post_slack_summary("http://hook.example", events)
    assert ok is True
