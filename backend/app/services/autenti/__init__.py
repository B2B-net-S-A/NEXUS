"""Autenti e-signature integration.

Wraps Autenti Public API v2 ("Bespin") with OAuth2 client_credentials,
HTML→PDF rendering, document process orchestration and JWT-signed webhook
verification.

Public surface:
- :class:`AutentiClient` — REST wrapper, async context manager.
- :class:`AutentiConfig` — env-loaded configuration dataclass.
- :func:`render_contract_pdf` — server-side HTML→PDF (WeasyPrint).
- Exception hierarchy: :class:`AutentiError`, :class:`AutentiAuthError`,
  :class:`AutentiNotFoundError`, :class:`AutentiRateLimitError`,
  :class:`AutentiWebhookError`.

Phases 2–5 add :mod:`.sender`, :mod:`.webhook_verify`, :mod:`.webhook_handler`.
"""

from app.services.autenti.client import (
    AutentiAuthError,
    AutentiClient,
    AutentiConfig,
    AutentiError,
    AutentiNotFoundError,
    AutentiRateLimitError,
    AutentiWebhookError,
)
from app.services.autenti.pdf_renderer import render_contract_pdf

__all__ = [
    "AutentiAuthError",
    "AutentiClient",
    "AutentiConfig",
    "AutentiError",
    "AutentiNotFoundError",
    "AutentiRateLimitError",
    "AutentiWebhookError",
    "render_contract_pdf",
]
