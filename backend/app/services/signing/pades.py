"""PAdES validation + (Faza 5) archival timestamp via pyHanko.

In the in-house QES rail the cryptographic *signing* is done outside NEXUS
(the consultant signs offline with their own qualified tool, then uploads the
signed PDF — Option B; or KIR Szafir/mSzafir for the embedded pasy). pyHanko's
role here is **validation** on the PDF we receive back.

Division of labour (both open-source, **zero KIR dependency**):
- **pyHanko** (this module) — fast, local, network-free *pre-check*: parses the
  PDF, extracts the embedded signature, verifies cryptographic integrity and
  reports the signer. It does NOT, by itself, assert eIDAS QES (that needs the
  EU Trusted List).
- **EU DSS** (`app.services.signing.validation.ValidationService`, Java sidecar)
  — the **authoritative** "is this QES per eIDAS?" verdict against the EU LOTL.

``pyhanko`` is verified compatible with the repo's ``cryptography==44.0.0`` pin
at ``pyhanko[etsi]==0.34.1`` (newer pyHanko needs cryptography>=48). Imported
lazily so unrelated paths don't pay the cost.

Plan: ``docs/in-house-qes-signature-plan.md`` §4, §7.
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

logger = logging.getLogger(__name__)


async def validate_pades_local(signed_pdf: bytes) -> dict[str, Any]:
    """Local PAdES integrity pre-check (NON-authoritative for QES).

    Parses the signed PDF, validates the first embedded signature's
    cryptographic integrity and reports the signer DN. ``is_qes`` is left
    ``False`` here on purpose — asserting eIDAS qualification requires the EU
    Trusted List, which is the EU DSS sidecar's job
    (:class:`ValidationService`). This gives the caller signer identity +
    integrity even when DSS is unavailable, without ever *claiming* QES.

    Returns a dict shaped like the DSS report subset:
    ``{is_qes, valid, intact, trusted, signed_by, signature_level, indication}``.

    Raises:
        RuntimeError: pyhanko not installed.
    """
    try:
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import async_validate_pdf_signature
        from pyhanko_certvalidator import ValidationContext
    except ImportError as exc:  # pragma: no cover — env without pyhanko
        raise RuntimeError(
            "pyhanko is not installed — add 'pyhanko[etsi]==0.34.1' to "
            "backend/requirements.txt before using local PAdES validation."
        ) from exc

    reader = PdfFileReader(BytesIO(signed_pdf))
    embedded = list(reader.embedded_signatures)
    if not embedded:
        return {
            "is_qes": False,
            "valid": False,
            "intact": False,
            "trusted": False,
            "signed_by": None,
            "signature_level": None,
            "indication": "NO_SIGNATURE",
        }

    # No EU Trusted List roots here → integrity/structure only, soft-fail on
    # revocation, no network. Authoritative trust comes from DSS.
    vc = ValidationContext(allow_fetching=False, revocation_mode="soft-fail")
    status = await async_validate_pdf_signature(
        embedded[0], signer_validation_context=vc
    )

    signed_by = None
    for attr in ("signing_cert",):
        cert = getattr(status, attr, None)
        if cert is not None:
            subj = getattr(cert, "subject", None)
            signed_by = getattr(subj, "human_friendly", None) or (
                str(subj) if subj else None
            )
            break

    return {
        # Conservative: local path never asserts QES — that's DSS's verdict.
        "is_qes": False,
        "valid": bool(getattr(status, "bottom_line", False)),
        "intact": bool(getattr(status, "intact", False)),
        "trusted": bool(getattr(status, "trusted", False)),
        "signed_by": signed_by,
        "signature_level": None,
        "indication": "PRE_CHECK_ONLY",
    }


def add_archival_timestamp(signed_pdf: bytes) -> bytes:
    """Add a PAdES B-LTA archival document timestamp (Faza 5).

    Re-stamps long-lived contracts before their existing timestamps expire so
    the signature stays provably valid for the (potentially decades-long) IP
    retention horizon. pyHanko ``PdfTimeStamper`` against a qualified TSA.

    Raises:
        NotImplementedError: lands in Faza 5 (needs a qualified TSA endpoint).
    """
    raise NotImplementedError(
        "add_archival_timestamp: B-LTA re-stamping lands in Faza 5 (qualified TSA)."
    )
