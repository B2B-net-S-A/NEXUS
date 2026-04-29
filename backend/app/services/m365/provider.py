"""Email provider abstraction (Protocol).

Nexus speaks to exactly one mail/calendar provider today (Microsoft 365), but
the plan calls for Gmail as a second implementation in Phase 3. Keeping this
abstraction means the router, sync loop, and matcher depend on a neutral
interface, not `M365Provider` directly.

The Protocol documents the contract; concrete classes (`M365Provider`) live in
sibling modules and only need to be importable when their provider is in use.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, Optional, Protocol


@dataclass(frozen=True)
class TokenBundle:
    """Result of an OAuth exchange or refresh."""

    access_token: str
    refresh_token: str
    expires_at: datetime
    scopes: list[str]
    tenant_id: str
    mailbox_upn: str


@dataclass(frozen=True)
class MatchResult:
    """Output of matcher.match()."""

    candidate_id: Optional[int]
    method: str  # EmailMatchMethod value
    confidence: Optional[float]


class EmailProvider(Protocol):
    """Minimum surface a mail/calendar provider must expose to Nexus."""

    # ── OAuth ─────────────────────────────────────────────────────────────
    def authorize_url(self, state: str, pkce_verifier: str) -> str: ...

    async def exchange_code(self, code: str, pkce_verifier: str) -> TokenBundle: ...

    async def refresh(self, refresh_token: str) -> TokenBundle: ...

    async def revoke(self, refresh_token: str) -> None: ...

    # ── Messages ──────────────────────────────────────────────────────────
    def list_messages_delta(
        self, delta_link: Optional[str], since: Optional[datetime]
    ) -> AsyncIterator[dict]: ...

    async def get_message(self, message_id: str) -> dict: ...

    async def download_attachment(
        self, message_id: str, attachment_id: str
    ) -> bytes: ...

    async def send_message(
        self, *, to: list[str], cc: list[str], subject: str, body_html: str
    ) -> dict: ...

    async def reply_message(self, message_id: str, *, body_html: str) -> dict: ...

    # ── Calendar ──────────────────────────────────────────────────────────
    def list_events_delta(self, delta_link: Optional[str]) -> AsyncIterator[dict]: ...

    async def create_event(
        self,
        *,
        subject: str,
        body_html: str,
        start: datetime,
        end: datetime,
        attendees: list[str],
        timezone: str,
    ) -> dict: ...

    async def delete_event(self, event_id: str) -> None: ...
