"""HMAC-SHA256 verification for CloudTalk inbound webhooks.

CloudTalk signs every webhook body with the shared secret configured in
dashboard → Integrations → Webhooks → Signing secret. The signature arrives
in the ``X-CloudTalk-Signature`` header as a hex digest. We refuse the
webhook on mismatch (HTTP 401) — never "trust unsigned".

Unlike Autenti (RS256 JWT against JWKS), CloudTalk uses a simple shared
secret + body HMAC. Replay protection is provided one layer up by the
``calls.cloudtalk_call_id`` UNIQUE constraint (dedup-by-id idempotency).
"""

from __future__ import annotations

import hashlib
import hmac


def verify_signature(body: bytes, signature_header: str, secret: str) -> bool:
    """Constant-time compare expected HMAC against ``signature_header``.

    Empty inputs return False — fail closed. Strips whitespace and accepts
    optional ``sha256=`` prefix (CloudTalk has been observed to send both
    forms across plan tiers).
    """
    if not secret or not signature_header:
        return False

    cleaned = signature_header.strip()
    if cleaned.lower().startswith("sha256="):
        cleaned = cleaned[7:]

    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, cleaned)
