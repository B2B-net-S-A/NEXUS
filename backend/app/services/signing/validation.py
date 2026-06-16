"""Authoritative "is this QES?" validation via the EU DSS sidecar.

The European Commission's DSS (``dss-validation-rest``) is the reference
implementation for validating advanced/qualified signatures against the EU
List of Trusted Lists (LOTL). We run it as a Java sidecar (Coolify service,
profile ``signing``) and call it over HTTP from here. When the sidecar URL is
unset we fall back to pyHanko's local trust-chain check (non-authoritative).

Plan: ``docs/in-house-qes-signature-plan.md`` §4, §7, §11 (Faza 4).
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from app.core.config import settings
from app.services.signing.provider import ValidationReport

logger = logging.getLogger(__name__)


class ValidationService:
    """Validate a signed PAdES and return a normalized :class:`ValidationReport`."""

    def __init__(self, dss_url: str | None = None) -> None:
        self._dss_url = (
            dss_url if dss_url is not None else settings.DSS_VALIDATION_URL
        ).strip()

    @property
    def has_dss(self) -> bool:
        return bool(self._dss_url)

    async def validate(self, signed_pdf: bytes) -> ValidationReport:
        """Return the QES verdict for ``signed_pdf``.

        Prefers the DSS sidecar; falls back to pyHanko local check; if neither
        is available, returns an ``is_qes=False`` report flagged ``unavailable``
        so the caller never silently treats an unverified signature as QES.
        """
        if self.has_dss:
            try:
                return await self._validate_via_dss(signed_pdf)
            except Exception as exc:  # pragma: no cover — network/DSS errors
                logger.warning(
                    "DSS validation failed, no authoritative verdict: %s", exc
                )
                return ValidationReport(
                    is_qes=False,
                    indication="INDETERMINATE",
                    sub_indication="DSS_ERROR",
                    raw={"error": str(exc)},
                )
        # No DSS configured — local pyHanko fallback (non-authoritative).
        try:
            from app.services.signing.pades import validate_pades_local

            local = validate_pades_local(signed_pdf)
            return ValidationReport(
                is_qes=bool(local.get("is_qes")),
                signature_level=local.get("signature_level"),
                signed_by=local.get("signed_by"),
                indication=local.get("indication"),
                raw=local,
            )
        except Exception as exc:
            logger.warning("Local PAdES validation unavailable: %s", exc)
            return ValidationReport(
                is_qes=False,
                indication="INDETERMINATE",
                sub_indication="VALIDATOR_UNAVAILABLE",
                raw={"error": str(exc)},
            )

    async def _validate_via_dss(self, signed_pdf: bytes) -> ValidationReport:
        """POST the signed PDF to the DSS REST sidecar and map its report.

        The exact request/response shape of ``dss-validation-rest`` is pinned
        in Faza 4 against the chosen DSS image; this is the integration seam.
        """
        import httpx

        b64 = base64.b64encode(signed_pdf).decode("ascii")
        payload = {
            "signedDocument": {
                "bytes": b64,
                "name": "contract.pdf",
            }
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._dss_url.rstrip('/')}/validateSignature", json=payload
            )
            resp.raise_for_status()
            data = resp.json()
        return self._map_dss_report(data)

    @staticmethod
    def _map_dss_report(data: dict[str, Any]) -> ValidationReport:
        """Map a DSS ``SimpleReport`` into our :class:`ValidationReport`.

        TODO(Faza 4): confirm field paths against the actual DSS report JSON
        (``simpleReport.signatureOrTimestamp[].indication`` /
        ``.signatureLevel`` / ``.signedBy``). Kept defensive for now.
        """
        sig_level = None
        indication = None
        signed_by = None
        try:
            simple = data.get("simpleReport") or data
            sigs = simple.get("signatureOrTimestamp") or simple.get("signature") or []
            if sigs:
                first = sigs[0]
                sig_level = first.get("signatureLevel") or first.get("SignatureLevel")
                indication = first.get("indication") or first.get("Indication")
                signed_by = first.get("signedBy") or first.get("SignedBy")
        except Exception:  # pragma: no cover — defensive mapping
            pass
        level_str = (sig_level or "").upper() if isinstance(sig_level, str) else ""
        is_qes = "QES" in level_str or "QESIG" in level_str
        return ValidationReport(
            is_qes=is_qes,
            signature_level=str(sig_level) if sig_level else None,
            signed_by=str(signed_by) if signed_by else None,
            indication=str(indication) if indication else None,
            raw=data,
        )
