"""Czy podpis w PDF-ie jest kwalifikowany — pyHanko z listą zaufanych dostawców UE.

Decyzja Artura 21.10.2026: na pilotaż pyHanko w backendzie (bez nowego
kontenera), EU DSS jako drugie zdanie dopiero, gdy pilotaż pokaże rozbieżności.
Interfejs jak ``ValidationService`` (``authoritative`` + ``validate``), więc
zamiana to jedna zmienna ``B2B_ESIGN_VALIDATOR``.

Jak to działa:

1. Lista list UE (LOTL) i listy krajowe z ``ec.europa.eu`` — pyHanko sprawdza
   ich podpisy kluczami wbudowanymi w bibliotekę. Pamięć procesu, odświeżenie
   co ``REFRESH_HOURS``; nieudane odświeżenie zostawia poprzednią listę, a bez
   żadnej listy walidator nie jest autorytatywny (``verdict`` odmawia).
2. Każdy podpis zatwierdzający (bez znaczników czasu dokumentu) przechodzi
   pełną walidację ścieżki certyfikatu z zaufaniem z listy UE i sprawdzeniem
   unieważnienia (OCSP/CRL z sieci).
3. Kwalifikowany = certyfikat kwalifikowany do podpisu (``qct_esign``), klucz
   na kwalifikowanym urządzeniu (QSCD, także zdalnym — SimplySign, mSzafir)
   — wtedy poziom ``QESig``; inaczej ``AdESig``.
4. Zmiany po podpisie: dozwolone tylko kolejne podpisy i dane do długiej
   ważności (poziom ≤ wypełnianie formularza). Dopisanie treści po podpisie
   = podpis „nie przeszedł”.

Do sprawdzenia przed pilotażem na prawdziwych plikach (Certum, KIR, mObywatel).
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import time
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Optional

from app.services.signing.pades import approval_signatures
from app.services.signing.provider import ValidationReport

logger = logging.getLogger(__name__)

REFRESH_HOURS = 12
_FETCH_TIMEOUT_S = 120

_registry: Any = None
_loaded_at: float = 0.0
_lock = asyncio.Lock()


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:  # pragma: no cover — obraz bez certifi
        return ssl.create_default_context()


async def _fetch_registry() -> Any:
    import aiohttp
    from pyhanko.sign.validation.qualified import eutl_fetch

    connector = aiohttp.TCPConnector(ssl=_ssl_context())
    timeout = aiohttp.ClientTimeout(total=_FETCH_TIMEOUT_S)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as client:
        registry, errors = await eutl_fetch.lotl_to_registry(None, client)
    if errors:
        # Pojedyncza lista krajowa z błędem nie przekreśla pozostałych.
        logger.warning("[b2b_esign] lista zaufanych UE: %d błędów list", len(errors))
    return registry


async def trusted_registry(*, now: float | None = None) -> Any:
    """Rejestr dostawców z listy UE albo ``None``, gdy nie da się go mieć."""
    global _registry, _loaded_at
    clock = time.monotonic() if now is None else now
    fresh = _registry is not None and clock - _loaded_at < REFRESH_HOURS * 3600
    if fresh:
        return _registry
    async with _lock:
        if _registry is not None and clock - _loaded_at < REFRESH_HOURS * 3600:
            return _registry
        try:
            _registry = await _fetch_registry()
            _loaded_at = clock
        except Exception as exc:  # noqa: BLE001 — sieć, parsowanie, podpis listy
            logger.warning("[b2b_esign] nie pobrano listy zaufanych UE: %s", exc)
        return _registry


def level_of(qualification: Any) -> str:
    """``QESig`` tylko dla certyfikatu kwalifikowanego do podpisu z kluczem na QSCD."""
    from pyhanko.sign.validation.qualified.q_status import (
        QcPrivateKeyManagementType,
    )
    from pyhanko.sign.validation.qualified.tsp import QcCertType

    status = getattr(qualification, "status", None)
    if (
        status is not None
        and status.qualified
        and status.qc_type == QcCertType.QC_ESIGN
        and status.qc_key_security != QcPrivateKeyManagementType.UNKNOWN
    ):
        return "QESig"
    return "AdESig"


def _subject(cert: Any) -> Optional[str]:
    subject = getattr(cert, "subject", None)
    if subject is None:
        return None
    native = getattr(subject, "native", None) or {}
    common_name = native.get("common_name") if isinstance(native, dict) else None
    return (
        f"CN={common_name}" if common_name else getattr(subject, "human_friendly", None)
    )


def _passed(status: Any) -> bool:
    from pyhanko.sign.diff_analysis import ModificationLevel

    if status is None or not (status.intact and status.valid and status.trusted):
        return False
    level = getattr(status, "modification_level", None)
    if level is None:
        diff = getattr(status, "diff_result", None)
        level = getattr(diff, "modification_level", None)
    return level is None or level <= ModificationLevel.FORM_FILLING


class QualifiedValidator:
    """Walidator kwalifikowanego podpisu PAdES na liście zaufanych UE."""

    def __init__(self) -> None:
        self._registry: Any = None

    @property
    def authoritative(self) -> bool:
        return self._registry is not None

    async def prepare(self) -> "QualifiedValidator":
        self._registry = await trusted_registry()
        return self

    async def validate(self, signed_pdf: bytes) -> ValidationReport:
        if self._registry is None:
            await self.prepare()
        if self._registry is None:
            return ValidationReport(
                is_qes=False,
                indication="INDETERMINATE",
                sub_indication="EU_TRUSTED_LIST_UNAVAILABLE",
            )
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import async_validate_pdf_signature
        from pyhanko.sign.validation.qualified.assess import QualificationAssessor
        from pyhanko.sign.validation.qualified.tsp import TSPTrustManager
        from pyhanko_certvalidator import ValidationContext

        try:
            reader = PdfFileReader(BytesIO(signed_pdf))
            approvals = approval_signatures(reader) or []
        except Exception as exc:  # noqa: BLE001 — uszkodzony PDF = brak podpisu
            logger.info("[b2b_esign] PDF nie do odczytu: %s", exc)
            return ValidationReport(is_qes=False, indication="NO_SIGNATURE")

        assessor = QualificationAssessor(self._registry)
        results: list[dict[str, Any]] = []
        for embedded, _name in approvals:
            context = ValidationContext(
                trust_manager=TSPTrustManager(self._registry),
                allow_fetching=True,
                revocation_mode="hard-fail",
            )
            try:
                status = await async_validate_pdf_signature(
                    embedded, signer_validation_context=context
                )
            except Exception:  # noqa: BLE001 — podpis nie do sprawdzenia = negatywny
                logger.warning(
                    "[b2b_esign] walidacja podpisu nie powiodła się", exc_info=True
                )
                status = None
            passed = _passed(status)
            level = None
            if passed and status is not None and status.validation_path is not None:
                moment = status.signer_reported_dt or datetime.now(timezone.utc)
                qualification = status.qualification_result or (
                    assessor.check_entity_cert_qualified(status.validation_path, moment)
                )
                level = level_of(qualification)
            results.append(
                {
                    "signer": _subject(getattr(status, "signing_cert", None)),
                    "indication": "TOTAL_PASSED" if passed else "TOTAL_FAILED",
                    "level": level,
                }
            )
        return ValidationReport(
            is_qes=bool(results) and all(r["level"] == "QESig" for r in results),
            signature_count=len(approvals),
            signers=[r["signer"] for r in results if r["signer"]],
            signature_results=results,
            raw={"validator": "pyhanko-eutl"},
        )
