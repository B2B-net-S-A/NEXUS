"""Provider-agnostic signing contract.

The in-house QES rail (drop Autenti) standardises every signing backend behind
one :class:`SignatureProvider` Protocol so the API/sender/sweeper code never
branches on the concrete provider. Implementations:

- :class:`app.services.signing.szafir_sdk_provider.SzafirSdkProvider` — KIR
  Szafir SDK, card/token/mobile, client-side PAdES (pas główny).
- :class:`app.services.signing.mszafir_provider.MszafirOneShotProvider` — KIR
  mSzafir One Shot, cloud one-time cert (pas zapasowy).
- :class:`app.services.signing.upload_validate_provider.UploadValidateProvider`
  — Option B: signer uploads their own-signed PAdES.
- :class:`app.services.signing.autenti_provider.AutentiProvider` — legacy
  aggregator (deprecated; keeps its own dedicated router/webhook flow).

Plan: ``docs/in-house-qes-signature-plan.md`` §3, §7.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover — avoid runtime/circular import
    from app.models.document_signature import DocumentSignature


class SigningProviderError(Exception):
    """Base error for the signing provider layer."""


class SigningProviderNotConfigured(SigningProviderError):
    """Provider lacks credentials/assets → surfaced to the API as HTTP 503.

    Raised by KIR-backed providers when ``SIGNING_ENABLED`` is on but the
    Szafir/mSzafir credentials (Faza 0 onboarding) are still empty.
    """


@dataclass(frozen=True)
class ProviderRef:
    """Opaque reference returned by :meth:`SignatureProvider.initiate`."""

    provider: str
    ref: Optional[str] = None
    signing_session_id: Optional[str] = None
    redirect_url: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SignedArtifact:
    """A completed, signed PDF + provider-reported metadata."""

    pdf_bytes: bytes
    signature_level: Optional[str] = None
    identity_provider: Optional[str] = None


@dataclass(frozen=True)
class ValidationReport:
    """Outcome of validating a PAdES signature against the EU Trusted List."""

    is_qes: bool
    signature_level: Optional[str] = None
    signed_by: Optional[str] = None
    indication: Optional[str] = None
    sub_indication: Optional[str] = None
    # Number of *approval* signatures embedded in the PDF (document timestamps
    # excluded). ``None`` when the validator could not determine it — callers
    # MUST treat ``None`` conservatively (i.e. not "both parties signed").
    signature_count: Optional[int] = None
    # Human-friendly signer names (one per approval signature), best-effort.
    signers: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def both_parties_signed(self) -> bool:
        """True only when we positively detect ≥2 approval signatures.

        For a B2B contract this means the consultant AND our company-side
        representative have both signed → the contract is fully executed.
        Conservative on ``None`` (unknown count → not both).
        """
        return (self.signature_count or 0) >= 2

    def as_db_report(self) -> dict[str, Any]:
        """Shape persisted to ``document_signatures.validation_report`` JSONB."""
        return {
            "is_qes": self.is_qes,
            "signature_level": self.signature_level,
            "signed_by": self.signed_by,
            "indication": self.indication,
            "sub_indication": self.sub_indication,
            "signature_count": self.signature_count,
            "signers": self.signers,
            "raw": self.raw,
        }


@runtime_checkable
class SignatureProvider(Protocol):
    """One signing backend. Stateless — construct per-request via the registry."""

    name: str

    async def initiate(self, sig: "DocumentSignature", pdf: bytes) -> ProviderRef:
        """Begin signing for ``sig`` over the rendered ``pdf``.

        Szafir SDK: a no-op reference (signing happens client-side via the
        minted link). mSzafir: starts a cloud session and returns a
        ``redirect_url`` for identity verification.
        """
        ...

    async def finalize(
        self, sig: "DocumentSignature", payload: dict[str, Any]
    ) -> SignedArtifact:
        """Complete signing and return the signed PDF.

        Szafir SDK / upload: ``payload['signed_pdf']`` holds the client-signed
        bytes. mSzafir: fetches the signed PDF from the cloud session.
        """
        ...

    async def validate(self, signed_pdf: bytes) -> ValidationReport:
        """Validate a signed PAdES — authoritative "is this QES?" verdict."""
        ...
