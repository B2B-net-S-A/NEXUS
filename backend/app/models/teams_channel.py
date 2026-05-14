"""Teams notification channel — Phase 7.6 of the M365 plan.

One row per configured Microsoft Teams channel that receives Adaptive Card
notifications for key ATS events. Application-only Graph auth (client
credentials flow) is used to post messages — see
``app.services.teams_notifications.send_to_channel``.

The `notification_types` JSONB array gates which events trigger a send so
admins can route, e.g., contract-signed notifications to a "Hot Deals"
channel and candidate-added to a separate "ATS Activity" channel.
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class TeamsNotificationChannel(Base, TimestampMixin):
    """A Microsoft Teams channel registered to receive ATS event cards."""

    __tablename__ = "teams_notification_channels"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Display name shown in the Settings UI (e.g. "ATS Deals", "Hot Pipeline").
    workspace_label: Mapped[str] = mapped_column(String(120), nullable=False)

    # Microsoft Graph team + channel identifiers. UNIQUE pair — admins can't
    # register the same channel twice.
    team_id: Mapped[str] = mapped_column(String(255), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # List of notification type keys this channel subscribes to. Stored as
    # JSONB so the trigger query can use the @> containment operator to find
    # all channels matching the event type in a single index scan.
    notification_types: Mapped[List[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Per-channel mute. Settings kill-switch (TEAMS_NOTIFICATIONS_ENABLED)
    # disables the integration globally; this column lets an admin pause a
    # single channel without losing its configuration.
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    created_by_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
    )

    # TimestampMixin already provides these — restated here so type checkers
    # see the Mapped annotation.
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    created_by = relationship("User", foreign_keys=[created_by_user_id])

    def __repr__(self) -> str:
        return (
            f"<TeamsNotificationChannel id={self.id} label={self.workspace_label!r} "
            f"team={self.team_id} channel={self.channel_id} enabled={self.enabled}>"
        )
