"""Dane do długiej weryfikacji (PAdES-LT) w umowie podpisanej przez obie strony.

E6, 23.11.2026. Dostawcy (np. KIR) dają podpis PAdES-BES albo PAdES-T: plik ma
podpis i znacznik czasu, ale nie ma odpowiedzi OCSP ani list CRL z chwili
podpisu. Za kilka lat responder OCSP może już nie odpowiadać, a certyfikat
wygaśnie, i wtedy podpisu nie da się sprawdzić. Dlatego po podpisie obu stron
dopisujemy sami, bez opłat, słownik DSS (Document Security Store): certyfikaty
ścieżek, odpowiedzi OCSP i listy CRL każdego podpisu, jako aktualizację
przyrostową bez nowego podpisu.

Zasady:

- Za przełącznikiem ``B2B_ESIGN_ADD_LTV`` (domyślnie wyłączony) i tylko
  z walidatorem ``pyhanko``: zaufanie i pobieranie OCSP/CRL są te same co przy
  walidacji (``QualifiedValidator.revocation_context``), adresy wyłącznie
  z certyfikatów, jeden backend połączeń na bieg, zamykany w ``finally``.
- Najlepszy wysiłek: każda awaria, przekroczenie czasu albo wynik, który nie
  przechodzi tej samej walidacji co wgrany plik, zostawia plik bez zmian
  i ostrzeżenie w logu. Podpisu obu stron to nigdy nie blokuje.
- Wynik zaczyna się bajtami wgranego pliku (``verdict.builds_on``), więc
  oryginał to zawsze jego początek.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from io import BytesIO
from typing import Any

from app.core.config import settings as app_config
from app.core.logging_config import redact_sensitive
from app.services.b2b_esign.qualified import QualifiedValidator
from app.services.b2b_esign.verdict import Fingerprint, builds_on
from app.services.signing.pades import approval_signatures

logger = logging.getLogger(__name__)

# Pobranie OCSP/CRL i ponowna walidacja razem. Reprezentant czeka na odpowiedź
# po wgraniu pliku, a pojedyncze żądanie i tak ma 10 s (backend pyHanko).
TIMEOUT_S = 60


class LongTermDataError(RuntimeError):
    """Danych do długiej weryfikacji nie da się zebrać."""


def _why(exc: BaseException) -> str:
    # Komunikaty pyHanko niosą podmiot certyfikatu (imię, nazwisko, PESEL).
    text = redact_sensitive(str(exc))[:300]
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _has_timestamp(embedded: Any) -> bool:
    from pyhanko.sign.validation.generic_cms import extract_tst_data_iter

    return any(
        True
        for signed in (False, True)
        for _ in extract_tst_data_iter(embedded.signer_info, signed=signed)
    )


async def _collect(embedded: Any, validator: QualifiedValidator, fetchers: Any):
    """OCSP/CRL i ścieżki jednego podpisu. Dane podpisującego są obowiązkowe
    (wyjątek przerywa całość), dane znacznika czasu podpisu (PAdES-T) tylko
    dokładane: ich brak nie przekreśla danych podpisującego."""
    from pyhanko.sign.validation.dss import collect_validation_info

    context = validator.revocation_context(fetchers)
    paths = await collect_validation_info(embedded, context, skip_timestamp=True)
    if _has_timestamp(embedded):
        try:
            # Ten sam kontekst: odpowiedzi dla podpisującego są już w pamięci.
            paths = await collect_validation_info(embedded, context)
        except Exception as exc:  # noqa: BLE001 — zostają dane podpisującego
            logger.info(
                "[b2b_esign] LT: bez danych znacznika czasu podpisu (%s)", _why(exc)
            )
    return context, paths


async def add_validation_data(
    signed_pdf: bytes, validator: QualifiedValidator
) -> bytes:
    """Plik z DSS dla każdego podpisu zatwierdzającego; wyjątek, gdy się nie da.

    Bez nowych danych (wszystko już jest w DSS) zwraca ``signed_pdf``."""
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation.dss import DocumentSecurityStore

    # strict=False jak w walidatorze (Word, część narzędzi do podpisu).
    reader = PdfFileReader(BytesIO(signed_pdf), strict=False)
    approvals = approval_signatures(reader)
    if not approvals:
        raise LongTermDataError("brak podpisów zatwierdzających")
    collected = []
    fetchers = validator.fetcher_backend()
    try:
        for embedded, _name in approvals:
            context, paths = await _collect(embedded, validator, fetchers)
            collected.append((embedded, context, paths))
    finally:
        await fetchers.close()

    writer = IncrementalPdfFileWriter.from_reader(reader)
    modified = False
    for embedded, context, paths in collected:
        dss = DocumentSecurityStore.supply_dss_in_writer(
            writer,
            # Wpis VRI tego podpisu: klucz to skrót zawartości /Contents.
            embedded.pkcs7_content.hex().encode("ascii"),
            validation_context=context,
            paths=paths,
        )
        modified = modified or dss.modified
    if not modified:
        return signed_pdf
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


async def with_long_term_data(
    signed_pdf: bytes,
    *,
    validator: Any,
    still_accepted: Callable[[bytes], Awaitable[bool]],
) -> bytes:
    """``signed_pdf`` z danymi PAdES-LT albo bez zmian (najlepszy wysiłek).

    ``still_accepted`` sprawdza wynik tą samą walidacją i tymi samymi
    wymaganiami co wgrany plik; wynik, który nie przejdzie, przepada."""
    if not app_config.B2B_ESIGN_ADD_LTV:
        return signed_pdf
    if not isinstance(validator, QualifiedValidator) or not validator.authoritative:
        # Sidecar DSS albo brak listy UE: bez zaufania z listy nie ma czym
        # zebrać OCSP/CRL, a pobranie listy tylko po to to nowy ruch do sieci.
        logger.info("[b2b_esign] LT: pominięte, walidator bez listy zaufanych UE")
        return signed_pdf

    async def _extend() -> bytes:
        extended = await add_validation_data(signed_pdf, validator)
        if extended is signed_pdf:
            return signed_pdf
        if not builds_on(extended, Fingerprint.of(signed_pdf)):
            raise LongTermDataError("wynik nie zaczyna się bajtami wgranego pliku")
        if not await still_accepted(extended):
            raise LongTermDataError("plik z danymi LT nie przechodzi walidacji")
        return extended

    try:
        return await asyncio.wait_for(_extend(), timeout=TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — podpis obu stron jest ważny i bez LT
        logger.warning(
            "[b2b_esign] LT: umowa zostaje bez danych do długiej weryfikacji (%s)",
            _why(exc),
        )
        return signed_pdf
