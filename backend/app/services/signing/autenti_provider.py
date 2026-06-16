"""Legacy Autenti provider — deprecated.

Autenti keeps its own dedicated router (``app.api.autenti``), sender
(``app.services.autenti.sender``) and webhook flow (``app.services.autenti``).
This wrapper exists only so the registry can resolve ``provider='autenti'`` for
historical ``document_signatures`` rows; it does NOT re-route Autenti through
the unified rail. New signatures use the KIR providers.

Plan: ``docs/in-house-qes-signature-plan.md`` §3 (AutentiProvider — deprecated).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services.signing.provider import (
    ProviderRef,
    SignedArtifact,
    ValidationReport,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.models.document_signature import DocumentSignature

_DEPRECATED = (
    "AutentiProvider is deprecated — Autenti uses its own dedicated flow in "
    "app.services.autenti / app.api.autenti. New signatures use the KIR providers."
)


class AutentiProvider:
    name = "autenti"

    async def initiate(self, sig: "DocumentSignature", pdf: bytes) -> ProviderRef:
        raise NotImplementedError(_DEPRECATED)

    async def finalize(
        self, sig: "DocumentSignature", payload: dict[str, Any]
    ) -> SignedArtifact:
        raise NotImplementedError(_DEPRECATED)

    async def validate(self, signed_pdf: bytes) -> ValidationReport:
        # Autenti guarantees the level it returns; we don't re-validate legacy rows.
        return ValidationReport(
            is_qes=True, raw={"note": "autenti-legacy, not re-validated"}
        )
