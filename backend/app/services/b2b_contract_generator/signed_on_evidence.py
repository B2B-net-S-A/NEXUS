"""Dzień podpisu umowy B2B z podpisu konsultanta w pliku (decyzja Artura 06.11.2026).

Do 06.11.2026 okno „Oznacz jako podpisaną” podpowiadało dzisiejszą datę, a plik
był dobrowolny. Premia 200% liczy miesiąc podpisu, więc data kliknięcia
przenosiła placement do złego miesiąca: w jednej z umów DL oznaczył podpis 30.10,
a konsultant podpisał 02.11 07:32. Teraz:

* plik podpisanej umowy jest obowiązkowy;
* z PDF-a czytamy podpisy elektroniczne (pyHanko, bez sieci): kto podpisał
  (nazwa z certyfikatu) i kiedy (znacznik czasu z podpisu, a bez niego czas
  deklarowany w podpisie). Podpis konsultanta to podpis, którego nazwa
  z certyfikatu zawiera imię i nazwisko z umowy (``verdict.name_matches``);
* dzień podpisu = dzień najwcześniejszego nienaruszonego podpisu konsultanta
  w kalendarzu firmy (``signed_on_source = 'pdf'``);
* plik z podpisami elektronicznymi, ale bez podpisu konsultanta: odmowa —
  nie da się oznaczyć podpisu obustronnego;
* skan bez podpisu elektronicznego (podpis odręczny): data wpisana ręcznie
  i obowiązkowy powód (``signed_on_source = 'manual'``).

Ta ścieżka nie rozstrzyga, czy podpis jest kwalifikowany (lista zaufanych UE
działa w drodze e-podpisu, ``services/b2b_esign``): potwierdzenie dalej jest
deklaracją uprawnionej osoby, a plik daje datę i ślad.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from io import BytesIO
from typing import Any, Literal, Optional

from fastapi import HTTPException, status
from fastapi.concurrency import run_in_threadpool

from app.core.scheduling import DEFAULT_TZ, business_date
from app.services.b2b_esign.verdict import name_matches
from app.services.signing.pades import approval_signatures

logger = logging.getLogger(__name__)

Party = Literal["consultant", "company", "other"]
Source = Literal["pdf", "manual", "esign"]

REASON_MIN_LENGTH = 3
REASON_MAX_LENGTH = 500

MSG_NOT_READABLE = (
    "Nie udało się odczytać podpisów z tego PDF-a. Sprawdź, czy to podpisany "
    "plik umowy, a nie wydruk do PDF."
)
MSG_NO_CONSULTANT = (
    "W pliku nie ma podpisu konsultanta z tej umowy, więc nie da się oznaczyć "
    "umowy jako podpisanej obustronnie."
)
MSG_CONSULTANT_BROKEN = (
    "Podpis konsultanta w pliku jest naruszony (plik zmieniono po podpisie). "
    "Poproś o plik prosto od konsultanta."
)
MSG_MANUAL_DATE = (
    "W pliku nie ma podpisu elektronicznego. Przy podpisie odręcznym wpisz datę "
    "podpisu konsultanta."
)
MSG_MANUAL_REASON = (
    "Przy podpisie odręcznym podaj powód ręcznej daty, np. „podpis odręczny 09.10”."
)


@dataclass(frozen=True)
class PdfSignature:
    """Jeden podpis zatwierdzający z pliku (bez znaczników czasu dokumentu)."""

    signer: str
    signed_at: Optional[datetime]
    #: ``timestamp`` = znacznik czasu w podpisie, ``declared`` = czas podany
    #: przez narzędzie do podpisu, ``None`` = brak czasu.
    time_source: Optional[str]
    #: Treść pliku objęta podpisem się nie zmieniła i podpis się zgadza.
    intact: bool


@dataclass(frozen=True)
class SignatureEntry:
    signer: str
    signed_at: Optional[datetime]
    time_source: Optional[str]
    intact: bool
    party: Party

    def payload(self) -> dict[str, Any]:
        return {
            "signer": self.signer,
            "signed_at": self.signed_at.isoformat() if self.signed_at else None,
            "time_source": self.time_source,
            "intact": self.intact,
            "party": self.party,
        }


@dataclass(frozen=True)
class SignedOnEvidence:
    """Skąd jest dzień podpisu zapisany przy umowie."""

    source: Source
    signed_on: Optional[date]
    reason: Optional[str] = None
    consultant_signed_at: Optional[datetime] = None


def _common_name(subject: str | None) -> str:
    """„Common Name: Jan Kowalski, Country: PL” → „Jan Kowalski” (z ogonkami)."""
    if not subject:
        return "nieznany podpisujący"
    text = str(subject)
    match = re.search(r"common name:\s*([^,;]+)", text, flags=re.IGNORECASE)
    if match is None:
        match = re.search(r"(?:^|[,/;\s])cn=([^,;/]+)", text, flags=re.IGNORECASE)
    if match is not None:
        return match.group(1).strip()
    # Certyfikat bez CN: imię i nazwisko z osobnych pól.
    given = re.search(r"given name:\s*([^,;]+)", text, flags=re.IGNORECASE)
    surname = re.search(r"surname:\s*([^,;]+)", text, flags=re.IGNORECASE)
    if given and surname:
        return f"{given.group(1).strip()} {surname.group(1).strip()}"
    return text.strip()


def _timestamp_time(emb: Any) -> Optional[datetime]:
    """Czas ze znacznika czasu podpisu (atrybut niepodpisany CMS), gdy jest."""
    try:
        from pyhanko.sign.validation.generic_cms import extract_tst_data_iter

        for tst in extract_tst_data_iter(emb.signer_info, signed=False):
            info = tst["encap_content_info"]["content"].parsed
            value = info["gen_time"].native
            if isinstance(value, datetime):
                return value
    except Exception:  # noqa: BLE001 — brak znacznika = czas deklarowany
        logger.debug("pyhanko: brak znacznika czasu podpisu", exc_info=True)
    return None


def _signing_time(emb: Any) -> tuple[Optional[datetime], Optional[str]]:
    stamped = _timestamp_time(emb)
    if stamped is not None:
        return stamped, "timestamp"
    try:
        declared = emb.self_reported_timestamp
    except Exception:  # noqa: BLE001
        declared = None
    if isinstance(declared, datetime):
        if declared.tzinfo is None:
            declared = declared.replace(tzinfo=timezone.utc)
        return declared, "declared"
    return None, None


async def _intact(emb: Any) -> bool:
    """Spójność kryptograficzna podpisu, bez sieci i bez listy zaufanych."""
    try:
        from pyhanko.sign.validation import async_validate_pdf_signature
        from pyhanko_certvalidator import ValidationContext

        status_ = await async_validate_pdf_signature(
            emb,
            signer_validation_context=ValidationContext(
                allow_fetching=False, revocation_mode="soft-fail"
            ),
        )
    except Exception:  # noqa: BLE001 — uszkodzony podpis = naruszony
        logger.info("pyhanko: podpis nie przeszedł sprawdzenia", exc_info=True)
        return False
    return bool(getattr(status_, "intact", False) and getattr(status_, "valid", False))


async def read_pdf_signatures(data: bytes) -> Optional[list[PdfSignature]]:
    """Podpisy zatwierdzające z PDF-a; ``[]`` = brak podpisów, ``None`` = nieczytelny."""
    if not data.startswith(b"%PDF"):
        return []

    def _parse() -> Optional[list[tuple[Any, str]]]:
        from pyhanko.pdf_utils.reader import PdfFileReader

        try:
            reader = PdfFileReader(BytesIO(data), strict=False)
        except Exception:  # noqa: BLE001
            logger.warning("pyhanko: nie da się otworzyć PDF-a", exc_info=True)
            return None
        return approval_signatures(reader)

    approvals = await run_in_threadpool(_parse)
    if approvals is None:
        return None
    found: list[PdfSignature] = []
    for emb, subject in approvals:
        signed_at, time_source = _signing_time(emb)
        found.append(
            PdfSignature(
                signer=_common_name(subject),
                signed_at=signed_at,
                time_source=time_source,
                intact=await _intact(emb),
            )
        )
    return found


def classify(
    signatures: list[PdfSignature],
    *,
    partner_name: str | None,
    company_names: list[str],
) -> list[SignatureEntry]:
    """Kto podpisał: konsultant (imię i nazwisko z umowy), firma (konto w NEXUSIE)."""
    entries: list[SignatureEntry] = []
    for sig in signatures:
        subject = f"CN={sig.signer}"
        party: Party = "other"
        if partner_name and name_matches(partner_name, subject):
            party = "consultant"
        elif any(name and name_matches(name, subject) for name in company_names):
            party = "company"
        entries.append(
            SignatureEntry(
                signer=sig.signer,
                signed_at=sig.signed_at,
                time_source=sig.time_source,
                intact=sig.intact,
                party=party,
            )
        )
    return entries


def consultant_signature(entries: list[SignatureEntry]) -> Optional[SignatureEntry]:
    """Najwcześniejszy nienaruszony podpis konsultanta z czasem."""
    dated = [
        entry
        for entry in entries
        if entry.party == "consultant" and entry.intact and entry.signed_at
    ]
    return min(dated, key=lambda entry: entry.signed_at) if dated else None


def clean_reason(reason: str | None) -> Optional[str]:
    text = " ".join((reason or "").split())
    return text or None


def resolve(
    entries: Optional[list[SignatureEntry]],
    *,
    manual_on: Optional[date],
    reason: Optional[str],
) -> SignedOnEvidence:
    """Dzień podpisu z pliku albo ręcznie z powodem; odmowa 422 z powodem."""
    if entries is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, MSG_NOT_READABLE)
    consultant = consultant_signature(entries)
    if consultant is not None:
        assert consultant.signed_at is not None
        return SignedOnEvidence(
            source="pdf",
            signed_on=business_date(consultant.signed_at, DEFAULT_TZ),
            consultant_signed_at=consultant.signed_at,
        )
    if entries:
        if any(e.party == "consultant" for e in entries):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, MSG_CONSULTANT_BROKEN
            )
        signers = ", ".join(entry.signer for entry in entries)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{MSG_NO_CONSULTANT} Podpisy w pliku: {signers}.",
        )
    if manual_on is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, MSG_MANUAL_DATE)
    text = clean_reason(reason)
    if text is None or len(text) < REASON_MIN_LENGTH:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, MSG_MANUAL_REASON)
    return SignedOnEvidence(
        source="manual", signed_on=manual_on, reason=text[:REASON_MAX_LENGTH]
    )


def preview(entries: Optional[list[SignatureEntry]]) -> dict[str, Any]:
    """Odpowiedź dla okna: lista podpisów i co z nią zrobi potwierdzenie."""
    if entries is None:
        return {"mode": "unreadable", "signatures": [], "message": MSG_NOT_READABLE}
    consultant = consultant_signature(entries)
    payload: dict[str, Any] = {
        "signatures": [entry.payload() for entry in entries],
        "consultant_signed_at": None,
        "consultant_signed_on": None,
        "message": None,
    }
    if consultant is not None:
        assert consultant.signed_at is not None
        payload.update(
            mode="pdf",
            consultant_signed_at=consultant.signed_at.isoformat(),
            consultant_signed_on=business_date(
                consultant.signed_at, DEFAULT_TZ
            ).isoformat(),
        )
    elif entries:
        payload.update(
            mode="blocked",
            message=(
                MSG_CONSULTANT_BROKEN
                if any(e.party == "consultant" for e in entries)
                else MSG_NO_CONSULTANT
            ),
        )
    else:
        payload.update(mode="manual")
    return payload


__all__ = [
    "PdfSignature",
    "SignatureEntry",
    "SignedOnEvidence",
    "classify",
    "consultant_signature",
    "preview",
    "read_pdf_signatures",
    "resolve",
]
