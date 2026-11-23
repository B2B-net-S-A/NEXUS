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
from typing import TYPE_CHECKING, Any, Optional

from app.services.signing.pades import approval_signatures
from app.services.signing.provider import ValidationReport

if TYPE_CHECKING:
    import aiohttp

logger = logging.getLogger(__name__)

REFRESH_HOURS = 12
_FETCH_TIMEOUT_S = 120
# Nagłówki pobierania list krajowych (22.11.2026). Z domyślnymi nagłówkami
# aiohttp listy CZ i EE nie schodziły, także na produkcji, więc podpis
# kwalifikowany z Czech i Estonii nie miał zaufanego wystawcy:
# - ``sr.riik.ee`` odpowiada 403 na ``User-Agent`` ze słowem „aiohttp”;
# - ``tsl.gov.cz`` podaje listę jako ``text/plain`` i odpowiada 406, gdy
#   ``Accept`` zna tylko typy XML, o które prosi pyHanko.
USER_AGENT = "NEXUS trusted-list fetch"
ACCEPT = "text/xml, application/vnd.etsi.tsl+xml, */*;q=0.1"

_registry: Any = None
_loaded_at: float = 0.0
_lock = asyncio.Lock()


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:  # pragma: no cover — obraz bez certifi
        return ssl.create_default_context()


async def _accept_any_type(
    request: aiohttp.ClientRequest, handler: aiohttp.ClientHandlerType
) -> aiohttp.ClientResponse:
    """pyHanko ustawia ``Accept`` przy każdym żądaniu, więc nagłówek sesji go
    nie zastąpi; middleware dopisuje ``*/*`` z niską wagą."""
    request.headers["Accept"] = ACCEPT
    return await handler(request)


def _client_session() -> aiohttp.ClientSession:
    import aiohttp

    return aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=_ssl_context()),
        timeout=aiohttp.ClientTimeout(total=_FETCH_TIMEOUT_S),
        headers={"User-Agent": USER_AGENT},
        middlewares=(_accept_any_type,),
    )


async def _fetch_registry() -> Any:
    from pyhanko.sign.validation.qualified import eutl_fetch

    async with _client_session() as client:
        registry, errors = await eutl_fetch.lotl_to_registry(None, client)
    if errors:
        # Pojedyncza lista krajowa z błędem nie przekreśla pozostałych.
        logger.warning("[b2b_esign] lista zaufanych UE: %d błędów list", len(errors))
        # Nie zeszła cała lista kraju = jego podpisy kwalifikowane nie przejdą.
        # Reszta błędów to zwykle stare wpisy usług (IT, SK) bez znaczenia.
        missing = [str(e) for e in errors if "Failed to download" in str(e)]
        if missing:
            logger.warning("[b2b_esign] nie pobrano list krajowych: %s", missing)
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
            started = time.monotonic()
            _registry = await _fetch_registry()
            _loaded_at = clock
            logger.info(
                "[b2b_esign] lista zaufanych UE pobrana w %.0f s",
                time.monotonic() - started,
            )
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


def _untrusted_issuer(status: Any) -> bool:
    """Podpis cały i ważny, ale jego certyfikatu nie da się połączyć z żadnym
    wystawcą z listy UE (np. podpis osobisty z e-dowodu, wystawca MSWiA).

    Taki podpis nie jest kwalifikowany, więc kontraktor ma to usłyszeć wprost,
    a nie „nie przeszedł weryfikacji” (22.11.2026). Rzadko to też podpis
    kwalifikowany bez certyfikatu pośredniego w pliku; odmowa jest ta sama."""
    from pyhanko.sign.ades.report import AdESIndeterminate

    return (
        status is not None
        and status.intact
        and status.valid
        and not status.trusted
        and getattr(status, "trust_problem_indic", None)
        == AdESIndeterminate.NO_CERTIFICATE_CHAIN_FOUND
    )


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

    @staticmethod
    def fetcher_backend() -> Any:
        """Połączenia OCSP/CRL na jeden bieg; wołający zamyka je w ``finally``."""
        from pyhanko_certvalidator.fetchers.aiohttp_fetchers import (
            AIOHttpFetcherBackend,
        )

        return AIOHttpFetcherBackend()

    def revocation_context(self, fetchers: Any) -> Any:
        """Kontekst jednego podpisu: zaufanie z listy UE, OCSP/CRL z sieci
        (adresy z certyfikatów), brak danych o unieważnieniu = odmowa. Ten sam
        dla walidacji i dla danych do długiej weryfikacji (``long_term``)."""
        from pyhanko.sign.validation.qualified.tsp import TSPTrustManager
        from pyhanko_certvalidator import ValidationContext

        return ValidationContext(
            trust_manager=TSPTrustManager(self._registry),
            allow_fetching=True,
            revocation_mode="hard-fail",
            fetcher_backend=fetchers,
        )

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

        try:
            # strict=False: PDF-y z „mieszanym” spisem obiektów (Word, część
            # narzędzi do podpisu, Dziennik Ustaw) w trybie ścisłym pyHanko
            # odrzuca w całości — prawdziwy podpis kwalifikowany dostawał
            # „nie przeszedł” (test 21.10.2026). Ukrytą treść łapie nadal
            # analiza zmian po podpisie (``_passed``) i porównanie początku
            # pliku z wysłanym (``verdict.builds_on``).
            reader = PdfFileReader(BytesIO(signed_pdf), strict=False)
            approvals = approval_signatures(reader) or []
        except Exception as exc:  # noqa: BLE001 — uszkodzony PDF = brak podpisu
            logger.info("[b2b_esign] PDF nie do odczytu: %s", exc)
            return ValidationReport(is_qes=False, indication="NO_SIGNATURE")

        assessor = QualificationAssessor(self._registry)
        results: list[dict[str, Any]] = []
        # Jedno połączenie OCSP/CRL na całą walidację, zamykane w ``finally``
        # — domyślny backend pyHanko zostawiał otwartą sesję na każde wgranie.
        fetchers = self.fetcher_backend()
        try:
            statuses = []
            for embedded, _name in approvals:
                context = self.revocation_context(fetchers)
                try:
                    statuses.append(
                        await async_validate_pdf_signature(
                            embedded, signer_validation_context=context
                        )
                    )
                except Exception:  # noqa: BLE001 — nie do sprawdzenia = negatywny
                    logger.warning(
                        "[b2b_esign] walidacja podpisu nie powiodła się", exc_info=True
                    )
                    statuses.append(None)
        finally:
            await fetchers.close()
        for status in statuses:
            passed = _passed(status)
            level = None
            if passed and status is not None and status.validation_path is not None:
                moment = status.signer_reported_dt or datetime.now(timezone.utc)
                qualification = status.qualification_result or (
                    assessor.check_entity_cert_qualified(status.validation_path, moment)
                )
                level = level_of(qualification)
            result: dict[str, Any] = {
                "signer": _subject(getattr(status, "signing_cert", None)),
                "indication": "TOTAL_PASSED" if passed else "TOTAL_FAILED",
                "level": level,
            }
            if _untrusted_issuer(status):
                result["untrusted_issuer"] = True
            results.append(result)
        return ValidationReport(
            is_qes=bool(results) and all(r["level"] == "QESig" for r in results),
            signature_count=len(approvals),
            signers=[r["signer"] for r in results if r["signer"]],
            signature_results=results,
            raw={"validator": "pyhanko-eutl"},
        )
