"""Outlook Actionable Messages — Phase 7.5 of the M365 expansion plan.

Renders the JSON-LD `OpenAction` payload that turns a regular HTML email body
into an Outlook Actionable Message: a "Potwierdzam interview" button that posts
straight to our public confirmation endpoint without the candidate ever leaving
their inbox.

Spec: https://learn.microsoft.com/en-us/outlook/actionable-messages/

Two pieces have to land in the email Microsoft delivers to Outlook:

1. A JSON-LD `<script type="application/ld+json">` block in the HTML body
   describing an `EmailMessage` whose `potentialAction` is an `HttpPOST`
   targeting our public endpoint with the JWT in the URL.
2. The `X-MS-Actionable-Message` internet header (set on the outbound Graph
   payload by the sender — not this module's job).

The JWT carries `{event_id, candidate_id, action: "confirm_interview", exp}`
signed with `M365_STATE_SIGNING_KEY` (re-used from the OAuth state JWT — same
trust boundary, same rotation cadence). 7-day TTL gives a recipient who
schedules far in advance time to revisit the invite.

This module is **pure** — no DB, no HTTP. The sender wraps it; the public
endpoint inverts it. Easy to unit-test.
"""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from jose import JWTError, jwt

from app.core.config import settings


_JWT_ALGORITHM = "HS256"
_JWT_TTL_SECONDS = 7 * 24 * 3600  # 7 days
_JWT_PURPOSE = "interview_confirmation"
_ACTION_CONFIRM_INTERVIEW = "confirm_interview"

# Default endpoint base — overridable via settings.PUBLIC_API_BASE_URL so
# staging/dev runs can point at their own host. Falls back to the prod URL so
# a missing env var doesn't silently break production sends.
_DEFAULT_API_BASE_URL = "https://api.nexus.dynaminds.pl"


class ActionableMessageError(RuntimeError):
    """Raised when token verification or payload validation fails."""


# ── JWT sign/verify ─────────────────────────────────────────────────────────


def _signing_key() -> str:
    return settings.M365_STATE_SIGNING_KEY or settings.SECRET_KEY


def sign_confirmation_token(
    *,
    event_id: int,
    candidate_id: int,
    action: str = _ACTION_CONFIRM_INTERVIEW,
    now: datetime | None = None,
) -> str:
    """Mint a JWT carrying enough state for the public endpoint to validate
    and apply the confirmation. The `purpose` claim guards against token
    cross-use with the M365 OAuth state flow that shares the signing key."""
    now = now or datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "event_id": int(event_id),
        "candidate_id": int(candidate_id),
        "action": action,
        "purpose": _JWT_PURPOSE,
        "iat": now,
        "exp": now + timedelta(seconds=_JWT_TTL_SECONDS),
    }
    return jwt.encode(payload, _signing_key(), algorithm=_JWT_ALGORITHM)


def verify_confirmation_token(token: str) -> dict[str, Any]:
    """Decode + validate a confirmation token. Raises `ActionableMessageError`
    on any failure (bad signature, expired, wrong purpose, missing claims).

    Returns the decoded payload `{event_id, candidate_id, action, ...}`.
    """
    try:
        payload = jwt.decode(token, _signing_key(), algorithms=[_JWT_ALGORITHM])
    except JWTError as exc:
        raise ActionableMessageError(f"token decode failed: {exc}") from exc

    if payload.get("purpose") != _JWT_PURPOSE:
        raise ActionableMessageError("token purpose mismatch")

    for required in ("event_id", "candidate_id", "action"):
        if required not in payload:
            raise ActionableMessageError(f"token missing claim: {required}")

    return payload


# ── Card builder ────────────────────────────────────────────────────────────


def _api_base_url() -> str:
    """Where the Outlook button POSTs to. Microsoft's Actionable Email
    service resolves this URL server-side, so it MUST be the externally
    reachable production URL — not a tunnel/localhost."""
    base = getattr(settings, "PUBLIC_API_BASE_URL", None) or _DEFAULT_API_BASE_URL
    return base.rstrip("/")


def _confirmation_url(token: str) -> str:
    qs = urlencode({"token": token})
    return f"{_api_base_url()}/api/public/interview-confirmation?{qs}"


def build_interview_confirmation_card(
    *,
    event_id: int,
    candidate_id: int,
    button_label: str = "Potwierdzam interview",
    now: datetime | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return `(html_snippet, payload_dict)`.

    `html_snippet` is meant to be concatenated into the email body BEFORE the
    signature. It contains:

    - A JSON-LD `<script type="application/ld+json">` block that Outlook parses
      to render the action button.
    - A visible fallback `<a>` link so non-Outlook clients (Gmail, Apple Mail,
      Outlook mobile in some configurations) still see a clickable confirm.

    `payload_dict` is the raw JSON-LD object so callers (tests, alternative
    renderers) can inspect/serialize it themselves.
    """
    token = sign_confirmation_token(
        event_id=event_id, candidate_id=candidate_id, now=now
    )
    target_url = _confirmation_url(token)

    payload: dict[str, Any] = {
        "@context": "https://schema.org/extensions",
        "@type": "EmailMessage",
        "potentialAction": {
            "@type": "ViewAction",
            "name": button_label,
            "target": target_url,
        },
        "publisher": "NEXUS ATS",
    }

    # The JSON-LD block carries our payload as JSON. We must escape any
    # `</` byte pair so a crafted `button_label` containing `</script>`
    # cannot break out of the surrounding `<script type="application/ld+json">`
    # element. This is the same defence Django uses in `django.utils.html.json_script`.
    # The surrounding fallback link uses `html.escape` on dynamic strings.
    import json

    json_ld = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    safe_label = html.escape(button_label)
    safe_url = html.escape(target_url, quote=True)

    html_snippet = (
        f'<script type="application/ld+json">{json_ld}</script>\n'
        f'<p style="margin:24px 0;">'
        f'<a href="{safe_url}" '
        f'style="display:inline-block;padding:10px 18px;'
        f"background-color:#7c3aed;color:#ffffff;"
        f'text-decoration:none;border-radius:6px;font-weight:600;">'
        f"{safe_label}"
        f"</a></p>"
    )

    return html_snippet, payload


__all__ = [
    "ActionableMessageError",
    "build_interview_confirmation_card",
    "sign_confirmation_token",
    "verify_confirmation_token",
]
