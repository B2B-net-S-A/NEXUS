"""In-house QES signing rail (drop Autenti, single-vendor KIR).

Provider-agnostic signing: one :class:`SignatureProvider` Protocol with
implementations for KIR Szafir SDK (card, client-side), KIR mSzafir One Shot
(cloud), an upload-and-validate lane, and the deprecated Autenti wrapper.
Validation ("is this QES?") is delegated to the EU DSS sidecar with a pyHanko
local fallback.

See ``docs/in-house-qes-signature-plan.md``.

Public surface:
- :func:`get_provider` — resolve a provider by name.
- :class:`SignatureProvider` Protocol + :class:`ProviderRef`,
  :class:`SignedArtifact`, :class:`ValidationReport` dataclasses.
- :class:`ValidationService` — DSS-backed QES validation.
- :func:`render_contract_pdf` — provider-agnostic HTML→PDF.
"""

from app.services.signing.pdf_renderer import render_contract_pdf
from app.services.signing.provider import (
    ProviderRef,
    SignatureProvider,
    SignedArtifact,
    SigningProviderError,
    SigningProviderNotConfigured,
    ValidationReport,
)
from app.services.signing.registry import get_provider, known_providers
from app.services.signing.validation import ValidationService

__all__ = [
    "ProviderRef",
    "SignatureProvider",
    "SignedArtifact",
    "SigningProviderError",
    "SigningProviderNotConfigured",
    "ValidationReport",
    "ValidationService",
    "get_provider",
    "known_providers",
    "render_contract_pdf",
]
