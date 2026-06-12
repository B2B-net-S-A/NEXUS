"""HMAC-SHA256 verification for jambonz → NEXUS webhook callbacks.

The algorithm is identical to CloudTalk's (constant-time HMAC-SHA256), so this
is a thin wrapper that reuses :func:`app.services.cloudtalk.webhook_verify.
verify_signature` with the dialer's own shared secret. Kept as a separate symbol
so the dialer never reaches into the CloudTalk namespace at call sites.
"""

from __future__ import annotations

from app.services.cloudtalk.webhook_verify import verify_signature


def verify_dialer_signature(body: bytes, signature_header: str, secret: str) -> bool:
    """Return True iff ``signature_header`` is a valid HMAC-SHA256 of ``body``.

    Fails closed on empty secret or header (see the underlying implementation).
    """
    return verify_signature(body, signature_header, secret)
