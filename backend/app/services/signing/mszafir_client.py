"""KIR mSzafir One Shot API client (pas zapasowy).

Cloud one-time qualified certificate for a signer WITHOUT their own cert:
identity is verified by bank / mObywatel / e-dowód, the cert is issued for the
moment of signing, and the PDF is signed in KIR's cloud.

The concrete API shape (endpoints, auth, request/response) is confirmed during
Faza 0 KIR onboarding — see ``docs/qes-faza0-kir-outreach.md`` questions 13-18.
Until then the methods raise :class:`SigningProviderNotConfigured` (no creds)
or ``NotImplementedError`` (creds present but wiring pending KIR docs), so the
flow degrades to a clean 503 rather than a fabricated call.

Plan: ``docs/in-house-qes-signature-plan.md`` §4, §7.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from app.core.config import settings
from app.services.signing.provider import SigningProviderNotConfigured

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MszafirConfig:
    base_url: str
    api_key_id: str
    api_key_secret: str

    @classmethod
    def from_settings(cls) -> "MszafirConfig":
        base = (settings.QTSP_MSZAFIR_BASE_URL or "").strip()
        kid = (settings.QTSP_MSZAFIR_API_KEY_ID or "").strip()
        secret = (settings.QTSP_MSZAFIR_API_KEY_SECRET or "").strip()
        if not (settings.QTSP_MSZAFIR_ENABLED and base and kid and secret):
            raise SigningProviderNotConfigured(
                "mSzafir One Shot not configured (QTSP_MSZAFIR_* empty / disabled). "
                "Complete Faza 0 KIR onboarding to enable the cloud signing pas."
            )
        return cls(base_url=base.rstrip("/"), api_key_id=kid, api_key_secret=secret)


class MszafirClient:
    """Thin async client around the mSzafir One Shot API."""

    def __init__(self, config: Optional[MszafirConfig] = None) -> None:
        # Raises SigningProviderNotConfigured if creds missing (→ 503).
        self._config = config or MszafirConfig.from_settings()

    async def start_one_shot(
        self, pdf: bytes, *, signer_email: str, return_url: str
    ) -> dict[str, Any]:
        """Start a One Shot session → returns session id + identity redirect URL.

        TODO(Faza 0/3): wire to the real mSzafir endpoint once KIR confirms the
        API (Q15-Q17). Expected to return ``{session_id, redirect_url}``.
        """
        raise NotImplementedError(
            "MszafirClient.start_one_shot: pending KIR mSzafir API docs (Faza 0)."
        )

    async def get_status(self, session_id: str) -> dict[str, Any]:
        """Poll a One Shot session status."""
        raise NotImplementedError(
            "MszafirClient.get_status: pending KIR mSzafir API docs (Faza 0)."
        )

    async def fetch_signed(self, session_id: str) -> bytes:
        """Download the signed PAdES once the session completes."""
        raise NotImplementedError(
            "MszafirClient.fetch_signed: pending KIR mSzafir API docs (Faza 0)."
        )
