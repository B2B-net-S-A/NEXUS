"""Pas główny — KIR Szafir SDK (card/token/mobile, client-side PAdES).

The signer uses their **own** qualified certificate via the Szafir SDK Web
Module embedded on the public ``/sign/{token}`` page + the local Szafir Host.
The PAdES signature is produced **client-side**; the signed PDF is POSTed back
to ``/api/public/sign/{token}/submit``. NEXUS never holds a signing key — its
job here is to receive the signed bytes and **validate** them.

So ``initiate`` is a no-op reference (the signing link is minted by the sender)
and ``finalize`` accepts the client-signed PDF and validates it.

Plan: ``docs/in-house-qes-signature-plan.md`` §3, §4 (pas główny).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services.signing.provider import (
    ProviderRef,
    SignedArtifact,
    SigningProviderError,
    ValidationReport,
)
from app.services.signing.validation import ValidationService

if TYPE_CHECKING:  # pragma: no cover
    from app.models.document_signature import DocumentSignature


class SzafirSdkProvider:
    name = "szafir_sdk"

    async def initiate(self, sig: "DocumentSignature", pdf: bytes) -> ProviderRef:
        # Client-side flow: nothing to start server-side. The sender has
        # already minted the SignatureLink and stored the unsigned PDF; the
        # Szafir SDK on the /sign page does the rest.
        return ProviderRef(provider=self.name)

    async def finalize(
        self, sig: "DocumentSignature", payload: dict[str, Any]
    ) -> SignedArtifact:
        signed = payload.get("signed_pdf")
        if not isinstance(signed, (bytes, bytearray)) or not signed:
            raise SigningProviderError(
                "szafir_sdk.finalize: payload['signed_pdf'] (signed PAdES bytes) required"
            )
        report = await self.validate(bytes(signed))
        return SignedArtifact(
            pdf_bytes=bytes(signed),
            signature_level=report.signature_level,
            identity_provider=payload.get("identity_provider", "card"),
        )

    async def validate(self, signed_pdf: bytes) -> ValidationReport:
        return await ValidationService().validate(signed_pdf)
