"""Pas zapasowy — KIR mSzafir One Shot (cloud one-time cert).

For a consultant WITHOUT their own qualified certificate. ``initiate`` starts a
cloud One Shot session (identity via bank/mObywatel) and returns a redirect URL
for the signing page; ``finalize`` fetches the cloud-signed PAdES and validates
it. The KIR API calls live in :class:`MszafirClient` and are stubbed until
Faza 0 onboarding confirms the API shape.

Plan: ``docs/in-house-qes-signature-plan.md`` §3, §4 (pas zapasowy).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services.signing.mszafir_client import MszafirClient
from app.services.signing.provider import (
    ProviderRef,
    SignedArtifact,
    SigningProviderError,
    ValidationReport,
)
from app.services.signing.validation import ValidationService

if TYPE_CHECKING:  # pragma: no cover
    from app.models.document_signature import DocumentSignature


class MszafirOneShotProvider:
    name = "mszafir_oneshot"

    async def initiate(self, sig: "DocumentSignature", pdf: bytes) -> ProviderRef:
        client = MszafirClient()  # raises SigningProviderNotConfigured → 503
        result = await client.start_one_shot(
            pdf,
            signer_email=sig.signer_email,
            return_url="",  # filled by the public endpoint with the /sign return URL
        )
        return ProviderRef(
            provider=self.name,
            signing_session_id=result.get("session_id"),
            redirect_url=result.get("redirect_url"),
            extra=result,
        )

    async def finalize(
        self, sig: "DocumentSignature", payload: dict[str, Any]
    ) -> SignedArtifact:
        session_id = payload.get("session_id") or sig.signing_session_id
        if not session_id:
            raise SigningProviderError("mszafir.finalize: signing_session_id required")
        client = MszafirClient()
        signed = await client.fetch_signed(str(session_id))
        report = await self.validate(signed)
        return SignedArtifact(
            pdf_bytes=signed,
            signature_level=report.signature_level,
            identity_provider=payload.get("identity_provider", "mobywatel"),
        )

    async def validate(self, signed_pdf: bytes) -> ValidationReport:
        return await ValidationService().validate(signed_pdf)
