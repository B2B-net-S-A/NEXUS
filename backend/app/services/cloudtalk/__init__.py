"""CloudTalk telephony integration (Phase CloudTalk.1+).

Public surface:
- :class:`CloudTalkClient` — async REST client (Basic Auth, retry, backoff)
- :func:`verify_signature` — HMAC-SHA256 webhook signature check
- :func:`timestamp_is_fresh` — freshness window check for webhook replay guard
- Exceptions: :class:`CloudTalkError`, :class:`CloudTalkAuthError`,
  :class:`CloudTalkRateLimitError`

Reference: https://my.cloudtalk.io/api (auth + endpoints per dashboard).
"""

from app.services.cloudtalk.client import (
    CloudTalkAuthError,
    CloudTalkClient,
    CloudTalkConfig,
    CloudTalkError,
    CloudTalkRateLimitError,
)
from app.services.cloudtalk.webhook_verify import (
    timestamp_is_fresh,
    verify_signature,
)

__all__ = [
    "CloudTalkClient",
    "CloudTalkConfig",
    "CloudTalkError",
    "CloudTalkAuthError",
    "CloudTalkRateLimitError",
    "verify_signature",
    "timestamp_is_fresh",
]
