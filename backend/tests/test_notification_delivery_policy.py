"""Policy boundaries without a provider, database or real email transmission."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from app.services import notification_delivery as delivery

NOW = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)


def enabled_policy(kind="chat_unread", now=NOW):
    return delivery.DeliveryPolicy.from_value(
        delivery.updated_value(
            delivery.DeliveryPolicy(),
            enabled=True,
            toggles={kind: True},
            now=now,
        )
    )


@pytest.mark.parametrize(
    "raw", [None, {}, {"enabled": True}, {"enabled": "true", "types": []}]
)
def test_missing_or_incomplete_policy_cannot_send(raw):
    policy = delivery.DeliveryPolicy.from_value(raw)
    assert not policy.effective_enabled
    assert not policy.allows("chat_unread", NOW)


def test_activation_excludes_old_backlog_but_allows_new_events():
    policy = enabled_policy()
    assert not policy.allows("chat_unread", NOW - timedelta(days=113))
    assert not policy.allows("chat_unread", NOW - timedelta(microseconds=1))
    assert policy.allows("chat_unread", NOW)
    assert not policy.allows("mentions", NOW)
    assert not policy.allows("chat_unread", None)


def test_global_reenable_does_not_replay_disabled_period():
    first = enabled_policy()
    off = delivery.DeliveryPolicy.from_value(
        delivery.updated_value(
            first, enabled=False, toggles={}, now=NOW + timedelta(minutes=1)
        )
    )
    assert not off.allows("chat_unread", NOW)
    second = delivery.DeliveryPolicy.from_value(
        delivery.updated_value(
            off, enabled=True, toggles={}, now=NOW + timedelta(hours=1)
        )
    )
    assert not second.allows("chat_unread", NOW + timedelta(minutes=30))
    assert second.allows("chat_unread", NOW + timedelta(hours=1))


def test_type_reenable_advances_only_that_type_cutoff():
    initial = delivery.DeliveryPolicy.from_value(
        delivery.updated_value(
            delivery.DeliveryPolicy(),
            enabled=True,
            toggles={"chat_unread": True, "mentions": True},
            now=NOW,
        )
    )
    off = delivery.DeliveryPolicy.from_value(
        delivery.updated_value(
            initial,
            enabled=True,
            toggles={"chat_unread": False},
            now=NOW + timedelta(minutes=1),
        )
    )
    later = NOW + timedelta(hours=1)
    on = delivery.DeliveryPolicy.from_value(
        delivery.updated_value(
            off, enabled=True, toggles={"chat_unread": True}, now=later
        )
    )
    assert not on.allows("chat_unread", NOW + timedelta(minutes=10))
    assert on.allows("mentions", NOW + timedelta(minutes=10))
    assert on.allows("chat_unread", later)


def test_ordinary_save_cannot_move_activation_boundary():
    first = enabled_policy()
    updated = delivery.DeliveryPolicy.from_value(
        delivery.updated_value(
            first,
            enabled=True,
            toggles={"chat_unread": True},
            now=NOW + timedelta(days=1),
        )
    )
    assert updated.cutoff_for("chat_unread") == NOW


def test_request_cannot_enable_security_or_supply_a_backdated_cutoff():
    from app.api.settings import NotificationDeliveryUpdate

    for payload in (
        {"enabled": True, "send_not_before": "2000-01-01T00:00:00Z"},
        {"enabled": True, "types": [{"id": "password_reset", "email_enabled": False}]},
        {"enabled": True, "types": [{"id": "chat_unread", "email_enabled": True}] * 2},
        {"enabled": "true"},
    ):
        with pytest.raises(ValidationError):
            NotificationDeliveryUpdate.model_validate(payload)


def test_sync_gate_fails_closed_without_calling_sender(monkeypatch):
    def fail():
        raise RuntimeError("DB unavailable")

    monkeypatch.setattr(delivery, "load_policy_sync", fail)
    send = Mock(return_value=True)
    assert not delivery.guarded_send("chat_unread", NOW, send)
    send.assert_not_called()
    assert delivery.last_send_policy_blocked()


def test_sync_gate_rechecks_after_admin_disables(monkeypatch):
    snapshots = iter([enabled_policy(), delivery.DeliveryPolicy()])
    monkeypatch.setattr(delivery, "load_policy_sync", lambda: next(snapshots))
    send = Mock(return_value=True)
    assert delivery.guarded_send("chat_unread", NOW, send)
    assert not delivery.guarded_send("chat_unread", NOW, send)
    assert send.call_count == 1


def _pin_disabled_policy(monkeypatch, *modules) -> None:
    async def disabled(_db):
        return delivery.DeliveryPolicy()

    monkeypatch.setattr(delivery, "load_policy", disabled)
    monkeypatch.setattr(delivery, "load_policy_sync", lambda: delivery.DeliveryPolicy())
    for module in modules:
        monkeypatch.setattr(module, "load_policy", disabled, raising=False)


async def test_disabled_chat_and_deadline_do_not_touch_provider(monkeypatch):
    from app.tasks import chat_email_fallback as chat, job_deadline_alerts as deadline

    db = SimpleNamespace(scalar=AsyncMock(return_value=None))
    # Polityka „wyłączona" podana wprost: test mówi o zachowaniu przy wyłączonej
    # wysyłce, więc nie może zależeć od tego, co w tym procesie zostawił
    # wcześniejszy test (w sicie PR-ów #1724 i poprzednim padał od kolejności).
    _pin_disabled_policy(monkeypatch, chat, deadline)
    channel = AsyncMock(side_effect=AssertionError("provider must not be checked"))
    monkeypatch.setattr(chat, "_channel_waiting", channel)
    monkeypatch.setattr(deadline, "get_system_sender_connection", channel)
    assert await chat._process_one_pass(db) == 0
    assert await deadline._dispatch_emails(db) == 0
    channel.assert_not_called()


async def test_disabled_delivery_alert_does_not_touch_provider(monkeypatch):
    from app.services import dl_alerts
    from app.services.m365 import system_mail

    monkeypatch.setattr(dl_alerts.settings, "DL_ALERTS_ENABLED", True)
    monkeypatch.setattr(dl_alerts.settings, "DL_ALERT_EMAIL_ENABLED", True)
    connection = AsyncMock(side_effect=AssertionError("delegated must also be blocked"))
    monkeypatch.setattr(system_mail, "get_system_sender_connection", connection)
    assert (
        await dl_alerts.send_pending_alert_emails(
            SimpleNamespace(scalar=AsyncMock(return_value=None))
        )
        == 0
    )
    connection.assert_not_called()


async def test_stage_inapp_still_works_while_routine_email_is_off(monkeypatch):
    from app.services import stage_notification_emitter as emitter

    _pin_disabled_policy(monkeypatch, emitter)
    monkeypatch.setattr(
        emitter,
        "resolve_recipients",
        AsyncMock(
            return_value=[
                SimpleNamespace(user_id=1, notify_inapp=True, notify_email=True)
            ]
        ),
    )
    monkeypatch.setattr(emitter, "_client_name", AsyncMock(return_value=None))
    inapp = AsyncMock()
    mail_user = AsyncMock(side_effect=AssertionError("must not start email work"))
    monkeypatch.setattr(emitter, "_send_inapp", inapp)
    monkeypatch.setattr(emitter, "_user_by_id", mail_user)
    candidate = SimpleNamespace(id=1, name="Test", lastname="Person")
    sent = await emitter.notify_stage_change(
        SimpleNamespace(scalar=AsyncMock(return_value=None)),
        new_stage=SimpleNamespace(id=1, moved_at=NOW),
        previous_stage=None,
        job=SimpleNamespace(id=1),
        candidate=candidate,
        mover=None,
        stage_display_name="Etap",
    )
    assert sent == 1
    inapp.assert_awaited_once()
    mail_user.assert_not_called()


async def test_mentions_still_push_inapp_while_routine_email_is_off(monkeypatch):
    from app.services import mention_dispatch as mentions

    db = SimpleNamespace(scalar=AsyncMock(return_value=None))
    context = AsyncMock()
    context.__aenter__.return_value = db
    monkeypatch.setattr(mentions, "AsyncSessionLocal", lambda: context)
    user = SimpleNamespace(id=1, email="test@example.invalid")
    monkeypatch.setattr(
        mentions, "filter_notification_recipients", AsyncMock(return_value=[user])
    )
    push = AsyncMock()
    monkeypatch.setattr(mentions.ws_manager, "notify_user", push)
    send = Mock(side_effect=AssertionError("mail must be blocked"))
    monkeypatch.setattr(mentions, "send_mention_email", send)
    notif = SimpleNamespace(
        id=1, title="Title", message="Message", link="/jobs/1", created_at=NOW
    )
    assert (
        await mentions.send_mention_side_effects(
            [(user, notif)],
            author_name="Author",
            snippet="Message",
            deep_link_path="/jobs/1",
            context_label="Note",
            notification_title="Title",
        )
        == 0
    )
    push.assert_awaited_once()
    send.assert_not_called()


def test_security_email_is_independent_of_routine_policy(monkeypatch):
    from app.services import email

    monkeypatch.setattr(delivery, "load_policy_sync", lambda: delivery.DeliveryPolicy())
    sender = Mock(return_value=True)
    monkeypatch.setattr(email, "send_email", sender)
    assert email.send_password_reset_email(
        to_email="test@example.invalid",
        recipient_name="Test",
        reset_url="https://example.invalid/reset",
    )
    sender.assert_called_once()


async def test_policy_block_is_not_mistaken_for_previous_uncertain_graph_post(
    monkeypatch,
):
    from app.tasks import chat_email_fallback as chat
    from app.services.m365 import app_mail

    monkeypatch.setattr(chat.settings, "M365_APP_MAIL_ENABLED", True)
    monkeypatch.setattr(delivery, "load_policy_sync", lambda: delivery.DeliveryPolicy())
    monkeypatch.setattr(app_mail, "last_delivery_uncertain", lambda: True)
    user = SimpleNamespace(email="test@example.invalid", name="Test")
    notif = SimpleNamespace(title="Title", message="Message", link="/", created_at=NOW)
    assert not await chat._send_chat_email(user, notif)


@pytest.mark.parametrize("role,expected", [("admin", 200), ("recruiter", 403)])
async def test_settings_read_and_write_are_admin_only(monkeypatch, role, expected):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.api import settings as settings_api
    from app.api.deps import require_onboarded_user
    from app.core.database import get_db
    from app.models.user import User, UserRole

    app = FastAPI()
    app.include_router(settings_api.router, prefix="/api/settings")
    user = User(id=123, role=UserRole(role), roles=[role], is_active=True)
    app.dependency_overrides[require_onboarded_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: object()
    view = AsyncMock(return_value={"enabled": False})
    save = AsyncMock()
    monkeypatch.setattr(delivery, "admin_view", view)
    monkeypatch.setattr(delivery, "save_policy", save)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.get("/api/settings/notification-delivery")
        ).status_code == expected
        response = await client.put(
            "/api/settings/notification-delivery", json={"enabled": False, "types": []}
        )
        assert response.status_code == expected
    if role == "admin":
        save.assert_awaited_once()
        assert save.call_args.kwargs["admin_id"] == 123
    else:
        save.assert_not_called()
        view.assert_not_called()


@pytest.mark.parametrize("history_available", [True, False])
async def test_catalog_off_preserves_real_provider_and_channel_information(
    monkeypatch, history_available
):
    from app.services.m365 import app_mail, mail_circuit, system_mail
    from app.tasks import app_mail_monitor

    monkeypatch.setattr(delivery.settings, "M365_APP_MAIL_ENABLED", True)
    monkeypatch.setattr(
        delivery.settings, "M365_MAIL_SENDER_UPN", "app@example.invalid"
    )
    monkeypatch.setattr(app_mail, "is_configured", lambda: True)
    state = {
        "attempts": 4,
        "consecutive_failures": 4,
        "last_failure_code": "http_403",
        "last_failure_at": NOW.timestamp(),
    }
    monkeypatch.setattr(
        mail_circuit,
        "snapshot",
        Mock(return_value=state)
        if history_available
        else Mock(side_effect=RuntimeError("unavailable")),
    )
    monkeypatch.setattr(
        system_mail,
        "get_system_sender_connection",
        AsyncMock(return_value=SimpleNamespace(mailbox_upn="system@example.invalid")),
    )
    monkeypatch.setattr(
        app_mail_monitor,
        "snapshot_queue",
        AsyncMock(
            return_value={
                "pending_retry": 0,
                "ready_candidates_upper_bound": 0,
                "uncertain": 0,
                "legacy_suppressed": 4,
                "scope": "chat_unread",
            }
        ),
    )
    result = await delivery.admin_view(
        SimpleNamespace(
            scalar=AsyncMock(return_value=None), get=AsyncMock(return_value=None)
        )
    )
    assert result["enabled"] is False
    assert result["provider"]["observed_status"] == (
        "degraded" if history_available else "unknown"
    )
    assert result["provider"]["failure_code"] == (
        "http_403" if history_available else "monitoring_state_unavailable"
    )
    assert result["backlog"]["scope"] == "chat_unread"
    types = {item["id"]: item for item in result["types"]}
    assert len(types) == 10
    assert types["kpi_weekly_report"]["channels"] == ["email"]
    assert types["board_monthly_report"]["channels"] == ["email"]
    assert all(not types[kind]["effective_enabled"] for kind in delivery.ROUTINE_KINDS)
    assert types["chat_unread"]["sender"] == "app@example.invalid"
    assert types["chat_unread"]["channels"] == ["in_app", "email"]
    assert types["delivery_alert"]["channels"] == ["client_panel", "email"]
    assert types["job_deadline"]["sender"] == "system@example.invalid"
    assert types["job_deadline"]["provider_kind"] == "graph_delegated"
    assert types["job_deadline"]["provider_status"] == "unknown"
    assert types["password_reset"]["effective_enabled"] is True
    assert types["password_reset"]["editable"] is False
    assert "external_monitoring" in {item["id"] for item in result["excluded_channels"]}
