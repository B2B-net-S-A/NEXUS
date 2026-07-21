"""HMAC-SHA256 verification for CloudTalk inbound webhooks.

CloudTalk signs every webhook body with the shared secret configured in
dashboard → Integrations → Webhooks → Signing secret. The signature arrives
in the ``X-CloudTalk-Signature`` header as a hex digest. We refuse the
webhook on mismatch (HTTP 401) — never "trust unsigned".

Unlike Autenti (RS256 JWT against JWKS), CloudTalk uses a simple shared
secret + body HMAC.

Replay protection (M6-P0.12): when the request carries an
``X-CloudTalk-Timestamp`` header, the timestamp is folded into the signed
material (``hmac(secret, f"{timestamp}.{body}")``, Stripe-style) and the
caller rejects the request when the timestamp is outside a small freshness
window (see :func:`timestamp_is_fresh`). Binding the timestamp into the HMAC
means a captured request cannot be replayed under a fresh timestamp, and the
freshness window means the original timestamp expires — together they close
the replay hole that ``calls.cloudtalk_call_id`` UNIQUE (INSERT-only dedup)
does not. The scheme is backward compatible: with no timestamp header the
legacy body-only signature is used so the integration keeps working on
CloudTalk plans that sign the body only.
"""

from __future__ import annotations

import hashlib
import hmac
import time


def verify_signature(
    body: bytes,
    signature_header: str,
    secret: str,
    *,
    timestamp: str | None = None,
) -> bool:
    """Constant-time compare expected HMAC against ``signature_header``.

    Empty inputs return False — fail closed. Strips whitespace and accepts
    optional ``sha256=`` prefix (CloudTalk has been observed to send both
    forms across plan tiers).

    When ``timestamp`` is provided the signed material is
    ``f"{timestamp}.{body}"``; otherwise the legacy body-only material is used.
    Freshness of ``timestamp`` is NOT checked here — the caller enforces it via
    :func:`timestamp_is_fresh` so the pure signature check stays side-effect
    free and deterministic.
    """
    if not secret or not signature_header:
        return False

    cleaned = signature_header.strip()
    if cleaned.lower().startswith("sha256="):
        cleaned = cleaned[7:]

    if timestamp is None:
        signed_material = body
    else:
        signed_material = timestamp.encode("utf-8") + b"." + body

    expected = hmac.new(
        secret.encode("utf-8"), signed_material, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, cleaned)


def timestamp_is_fresh(
    timestamp: str,
    tolerance_seconds: int,
    *,
    now: float | None = None,
) -> bool:
    """Return True iff ``timestamp`` (unix seconds) is within tolerance of now.

    Malformed / empty values fail closed (return False). ``tolerance_seconds``
    is the maximum allowed absolute skew in either direction (callers use
    ±300s). This is the freshness half of replay protection: combined with the
    timestamp being bound into the HMAC in :func:`verify_signature`, a replayed
    request is rejected once its timestamp ages past the window.
    """
    try:
        ts = float(str(timestamp).strip())
    except (TypeError, ValueError):
        return False
    reference = time.time() if now is None else now
    return abs(reference - ts) <= tolerance_seconds
