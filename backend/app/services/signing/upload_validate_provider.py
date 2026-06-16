"""Option B — signer uploads a PAdES signed with their own QES tool.

A minority of consultants already hold a qualified signature and prefer to sign
offline with their own tool, then upload the signed PDF. Identical to the
Szafir SDK ``finalize`` path (receive + validate) but reached via an upload
form rather than the embedded component. Shares the same validation module so
the "is QES?" verdict is consistent across pasy.

Plan: ``docs/in-house-qes-signature-plan.md`` §3 (lane wtórny).
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


class UploadValidateProvider:
    name = "upload_validate"

    async def initiate(self, sig: "DocumentSignature", pdf: bytes) -> ProviderRef:
        # Nothing server-side; the upload link is minted by the sender.
        return ProviderRef(provider=self.name)

    async def finalize(
        self, sig: "DocumentSignature", payload: dict[str, Any]
    ) -> SignedArtifact:
        signed = payload.get("signed_pdf")
        if not isinstance(signed, (bytes, bytearray)) or not signed:
            raise SigningProviderError(
                "upload_validate.finalize: payload['signed_pdf'] (uploaded PAdES) required"
            )
        report = await self.validate(bytes(signed))
        return SignedArtifact(
            pdf_bytes=bytes(signed),
            signature_level=report.signature_level,
            identity_provider="self",
        )

    async def validate(self, signed_pdf: bytes) -> ValidationReport:
        return await ValidationService().validate(signed_pdf)
