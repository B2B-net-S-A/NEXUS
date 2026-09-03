"""Regression contract for notification delivery after a section revocation."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api import notifications, ws
from app.models.notification import NotificationType
from app.models.user import User, UserRole
from app.services.notification_access import (
    notification_visibility_predicate,
    unmapped_notification_types,
    user_can_receive_notification,
    user_can_receive_realtime_event,
)
from app.services.section_permissions import ProductSection


def _user(**access: str) -> User:
    user = User(
        id=741852,
        email="notification-section@example.com",
        name="Notification Section",
        role=UserRole.recruiter,
        roles=[UserRole.recruiter.value],
        is_active=True,
    )
    user.effective_section_access = {
        section.value: access.get(section.value, "none") for section in ProductSection
    }
    return user


def test_every_notification_type_has_an_explicit_access_rule() -> None:
    assert unmapped_notification_types() == frozenset()


def test_old_rows_follow_current_effective_section_not_historic_role() -> None:
    revoked = _user()

    assert not user_can_receive_notification(
        revoked,
        NotificationType.job_deadline_7d,
        related_entity_type="job",
        link="/jobs/7",
    )
    assert not user_can_receive_notification(
        revoked,
        NotificationType.contract_ending,
        related_entity_type="contract",
        link="/contracts/9",
    )
    assert user_can_receive_notification(
        revoked,
        NotificationType.password_changed_by_admin,
    )

    sql = str(
        notification_visibility_predicate(revoked).compile(
            compile_kwargs={"literal_binds": True}
        )
    )
    assert "job_deadline_7d" not in sql
    assert "contract_ending" not in sql
    assert "password_changed_by_admin" in sql


def test_contextual_chat_and_note_notifications_use_exact_product_section() -> None:
    sourcing_only = _user(sourcing="read")
    pipeline_only = _user(pipeline="read")
    delivery_only = _user(delivery="read")

    assert user_can_receive_notification(
        sourcing_only,
        NotificationType.job_chat_message,
        related_entity_type="candidate_chat_message",
        link="/candidates/1?tab=chat",
    )
    assert not user_can_receive_notification(
        sourcing_only,
        NotificationType.job_chat_message,
        related_entity_type="job_chat_message",
        link="/jobs/1?tab=chat",
    )
    assert user_can_receive_notification(
        pipeline_only,
        NotificationType.job_chat_message,
        related_entity_type="job_chat_message",
        link="/jobs/1?tab=chat",
    )
    assert not user_can_receive_notification(
        pipeline_only,
        NotificationType.note_mention,
        related_entity_type="note",
        link="/contracts/1?tab=notes",
    )
    assert user_can_receive_notification(
        delivery_only,
        NotificationType.note_mention,
        related_entity_type="note",
        link="/contracts/1?tab=notes",
    )

    sourcing_sql = str(
        notification_visibility_predicate(sourcing_only).compile(
            compile_kwargs={"literal_binds": True}
        )
    )
    pipeline_sql = str(
        notification_visibility_predicate(pipeline_only).compile(
            compile_kwargs={"literal_binds": True}
        )
    )
    assert "related_entity_type = 'candidate_chat_message'" in sourcing_sql
    assert "related_entity_type != 'candidate_chat_message'" in pipeline_sql


def test_list_count_and_read_mutations_share_one_visibility_predicate() -> None:
    for endpoint in (
        notifications.list_notifications,
        notifications.get_unread_count,
        notifications.mark_as_read,
        notifications.mark_all_read,
    ):
        assert "_notification_visibility(current_user)" in inspect.getsource(endpoint)


def test_realtime_event_policy_blocks_revoked_sections() -> None:
    revoked = _user()
    pipeline = _user(pipeline="read")
    event = {
        "type": "notification",
        "data": {
            "notification_type": NotificationType.job_deadline_7d.value,
            "related_entity_type": "job",
            "link": "/jobs/7",
        },
    }

    assert not user_can_receive_realtime_event(revoked, event)
    assert user_can_receive_realtime_event(pipeline, event)
    assert not user_can_receive_realtime_event(revoked, {"type": "kpi_nudge"})


@pytest.mark.asyncio
async def test_connection_manager_drops_denied_notification_before_ws_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ws.ConnectionManager()
    socket = MagicMock()
    socket.send_json = AsyncMock()
    socket.close = AsyncMock()
    manager._connections[741852] = [socket]
    manager._auth_tokens[socket] = "valid-token"
    monkeypatch.setattr(ws, "_authenticate_ws_token", AsyncMock(return_value=_user()))

    await manager.notify_user(
        741852,
        {
            "type": "notification",
            "data": {
                "notification_type": NotificationType.job_deadline_7d.value,
                "link": "/jobs/7",
            },
        },
    )

    socket.send_json.assert_not_awaited()
