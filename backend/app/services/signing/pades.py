"""PAdES validation + (Faza 5) archival timestamp via pyHanko.

In the in-house QES rail the cryptographic *signing* is done by KIR (Szafir SDK
client-side, or mSzafir in the cloud) — pyHanko's role here is **validation**:
a fast trust-chain pre-check on the signed PDF we receive back. The
authoritative "is this QES per eIDAS?" verdict comes from the EU DSS sidecar
(:mod:`app.services.signing.validation`); pyHanko is the cheap first pass and
the local fallback when DSS is unavailable.

``pyhanko`` is a heavy dependency with native crypto — imported lazily so test
collection and unrelated code paths don't pay for it. Until ``pyhanko`` is
added to ``requirements.txt`` (Faza 3) these helpers raise a clear error.

Plan: ``docs/in-house-qes-signature-plan.md`` §4, §7.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _require_pyhanko() -> Any:
    try:
        import pyhanko  # noqa: WPS433  (intentional lazy import)
    except ImportError as exc:  # pragma: no cover — env without pyhanko
        raise RuntimeError(
            "pyhanko is not installed — add it to backend/requirements.txt "
            "(Faza 3) before using PAdES validation."
        ) from exc
    return pyhanko


def validate_pades_local(signed_pdf: bytes) -> dict[str, Any]:
    """Fast local trust-chain check of a signed PAdES (NON-authoritative).

    Returns a dict shaped like the DSS report subset so callers can treat
    local and DSS results uniformly. The ``is_qes`` flag from this path is a
    best-effort pre-check only — eIDAS QES determination needs the DSS sidecar
    (LOTL/Trusted-List + service-status-at-signing-time), which pyHanko's
    author explicitly warns it does not fully implement.

    Raises:
        RuntimeError: pyhanko not installed.
    """
    _require_pyhanko()
    # TODO(Faza 3): implement with pyhanko.sign.validation —
    #   from pyhanko.sign.validation import validate_pdf_signature
    #   from pyhanko_certvalidator import ValidationContext (+ EU trust roots)
    #   embedded = ... ; status = validate_pdf_signature(embedded, vc)
    # Map status.trusted / .valid / .signing_cert into the dict below.
    raise NotImplementedError(
        "validate_pades_local: pyHanko trust-chain validation lands in Faza 3."
    )


def add_archival_timestamp(signed_pdf: bytes) -> bytes:
    """Add a PAdES B-LTA archival document timestamp (Faza 5).

    Re-stamps long-lived contracts before their existing timestamps expire so
    the signature stays provably valid for the (potentially decades-long) IP
    retention horizon.

    Raises:
        RuntimeError: pyhanko not installed.
    """
    _require_pyhanko()
    # TODO(Faza 5): pyhanko PdfTimeStamper against a qualified TSA (KIR).
    raise NotImplementedError(
        "add_archival_timestamp: B-LTA re-stamping lands in Faza 5."
    )
