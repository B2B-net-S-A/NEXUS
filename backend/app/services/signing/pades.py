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
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)


def count_approval_signatures(reader: Any) -> tuple[Optional[int], list[str]]:
    """Count APPROVAL signatures + collect signer subjects from a signed PDF.

    Network-free, no async validation. Counts only approval signatures
    (signature dict ``/Type == /Sig``), excluding PAdES document timestamps
    (``/Type == /DocTimeStamp``, ``/SubFilter == /ETSI.RFC3161``). For a B2B
    contract ``>= 2`` approval signatures means both the consultant AND our
    company-side representative have signed → the contract is fully executed.

    API verified against ``pyhanko[etsi]==0.34.1``:
    ``EmbeddedPdfSignature.sig_object_type`` (``self.sig_object.get('/Type',
    '/Sig')``; pyHanko itself branches on this) and
    ``EmbeddedPdfSignature.signer_cert.subject.human_friendly`` (reads the cert
    straight from the embedded CMS — no network, no validation context).

    Returns ``(approval_count, signer_names)``; degrades to ``(None, [])`` on
    ANY error — never raises. ``None`` count ⇒ callers treat as "not both
    parties signed" (conservative).
    """
    try:
        try:
            embedded = list(reader.embedded_signatures)
        except Exception:  # noqa: BLE001 — malformed/encrypted/hybrid-xref PDF
            logger.warning(
                "pyhanko: could not enumerate embedded_signatures", exc_info=True
            )
            return None, []

        approval_count = 0
        signer_names: list[str] = []
        for emb in embedded:
            # Discriminate approval signature (/Sig) vs document timestamp.
            obj_type: Optional[str] = None
            try:
                obj_type = str(emb.sig_object_type)
            except Exception:  # noqa: BLE001
                try:
                    raw_type = emb.sig_object.get("/Type", None)
                    obj_type = str(raw_type) if raw_type is not None else "/Sig"
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "pyhanko: could not read sig /Type; skipping one",
                        exc_info=True,
                    )
                    continue

            subfilter: Optional[str] = None
            try:
                sf = emb.sig_object.get("/SubFilter", None)
                subfilter = str(sf) if sf is not None else None
            except Exception:  # noqa: BLE001
                subfilter = None

            if obj_type == "/DocTimeStamp" or subfilter == "/ETSI.RFC3161":
                continue  # PAdES document timestamp — not an approval signature
            if obj_type != "/Sig":
                continue  # unknown subtype — conservative: do not count

            approval_count += 1

            # Signer subject — straight from the embedded CMS, no network.
            name: Optional[str] = None
            try:
                cert = emb.signer_cert
                subj = getattr(cert, "subject", None)
                if subj is not None:
                    name = getattr(subj, "human_friendly", None) or str(subj)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "pyhanko: could not extract signer_cert subject", exc_info=True
                )
                name = None
            signer_names.append(name or "<nieznany sygnatariusz>")

        return approval_count, signer_names
    except Exception:  # noqa: BLE001 — last-resort guard, never break validation
        logger.warning("pyhanko: count_approval_signatures failed", exc_info=True)
        return None, []


async def validate_pades_local(signed_pdf: bytes) -> dict[str, Any]:
    """Local PAdES integrity pre-check (NON-authoritative for QES).

    Parses the signed PDF, validates the first embedded signature's
    cryptographic integrity and reports the signer DN. ``is_qes`` is left
    ``False`` here on purpose — asserting eIDAS qualification requires the EU
    Trusted List, which is the EU DSS sidecar's job
    (:class:`ValidationService`). This gives the caller signer identity +
    integrity even when DSS is unavailable, without ever *claiming* QES.

    Returns a dict shaped like the DSS report subset:
    ``{is_qes, valid, intact, trusted, signed_by, signature_level, indication,
    signature_count, signers}``. ``signature_count``/``signers`` count only
    approval signatures (document timestamps excluded) so the caller can detect
    a fully-executed (both-parties-signed) contract.

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

    # pyHanko parse + signature enumeration is sync CPU work — offload it so
    # the signing request path does not block the event loop.
    def _parse_signatures() -> tuple[int, list[str], list]:
        reader = PdfFileReader(BytesIO(signed_pdf))
        count, names = count_approval_signatures(reader)
        return count, names, list(reader.embedded_signatures)

    approval_count, signer_names, embedded = await run_in_threadpool(_parse_signatures)
    if not embedded:
        return {
            "is_qes": False,
            "valid": False,
            "intact": False,
            "trusted": False,
            "signed_by": None,
            "signature_level": None,
            "indication": "NO_SIGNATURE",
            "signature_count": 0,
            "signers": [],
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
        "signature_count": approval_count,
        "signers": signer_names,
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
