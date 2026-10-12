"""Bezpłatne rozpoznanie duplikatu PRZED płatnym odczytem CV.

`POST /api/candidates/from-cv` do 18.09.2026 robiło to w odwrotnej kolejności:
najpierw pełny odczyt CV przez model (krok 2), potem skan duplikatów (krok 3).
Odmowa 409 przychodziła więc już po zapłaceniu za odczyt — a w imporcie masowym
duplikat jest REGUŁĄ, nie wyjątkiem: bieg integracji #9 (17.09) wypchnął 8441 CV,
z czego 8349 było już w bazie. Zmierzone na produkcji od 16.09: 9739 płatnych
odczytów ($244) dało 689 kandydatów — 92,9% odczytów poszło do kosza.

Dwa darmowe sita, w tej kolejności:

1. **Ten sam plik** — `sha256` bajtów kontra `candidate_documents.content_sha256`.
   Replay tego samego pliku rozpoznajemy bez czytania treści.
2. **Ta sama osoba** — e-mail wyciągnięty regexem z nagłówka (zero I/O) podany
   do `find_candidate_by_email`. Od 12.10.2026 tylko e-mail: „ta sama osoba =
   ten sam e-mail” (decyzja Artura). Adres z formularza wygrywa z nagłówkiem.

Sito jest JEDNOSTRONNE i tylko takie być może: znalezienie duplikatu oszczędza
odczyt, NIEznalezienie niczego nie przesądza. Dlatego skan po płatnym odczycie
w `/from-cv` ZOSTAJE — regex bywa gorszy od modelu i to on jest tu tańszą,
a nie dokładniejszą ścieżką. Usunięcie tamtego skanu zamieniłoby oszczędność
w regres jakości danych.

`force=true` omija oba sita tak samo, jak omijał skan po odczycie.

**Dlaczego bez telefonu.** Fałszywe trafienie nie jest tu kosmetyczne: scraper
czyta z odmowy 409 `existing_candidate_id` i wgrywa CV do TEGO profilu, więc
wspólny numer (agencja, biuro) wrzucał CV obcej osoby komuś innemu. Na
produkcji 313 numerów należało 12.10.2026 do kilku różnych osób.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.services.dedup_service import find_candidate_by_email

logger = logging.getLogger(__name__)

#: Powód dopisywany do wiersza duplikatu rozpoznanego po bajtach pliku.
IDENTICAL_FILE_REASON = "identical_file"

#: Ile pierwszych linii CV liczy się jako nagłówek — dane kontaktowe stoją na
#: górze, adresy z treści (referencje, klienci) nie opisują kandydata.
_HEADER_LINES = 20

#: Ile wierszy duplikatu zwracamy. Odpowiedź 409 i tak pokazuje pierwszy;
#: reszta jest kontekstem dla człowieka.
_MAX_ROWS = 5


def content_digest(content: bytes) -> str:
    """SHA-256 bajtów pliku — ten sam skrót, który zapisuje `content_sha256`."""
    return hashlib.sha256(content).hexdigest()


def _header(raw_text: str) -> str:
    return "\n".join((raw_text or "").splitlines()[:_HEADER_LINES])


def header_email(raw_text: str) -> Optional[str]:
    """Pierwszy e-mail z NAGŁÓWKA CV, małymi literami."""
    from app.services.cv_parser import _EMAIL_RE

    match = _EMAIL_RE.search(_header(raw_text))
    return match.group(0).lower() if match else None


async def _duplicates_by_file_hash(
    db: AsyncSession, *, digest: str
) -> list[dict[str, Any]]:
    """Kandydaci, którzy mają JUŻ dokument o tych samych bajtach.

    Bierze wyłącznie dokumenty żywe (`source_deleted_at IS NULL`) — wiersz po
    skasowaniu źródła nie dowodzi, że kandydat ten plik nadal ma.
    """
    rows = (
        await db.execute(
            select(Candidate.id, Candidate.name, Candidate.lastname, Candidate.email)
            .join(CandidateDocument, CandidateDocument.candidate_id == Candidate.id)
            .where(
                CandidateDocument.content_sha256 == digest,
                CandidateDocument.source_deleted_at.is_(None),
            )
            .order_by(Candidate.id)
            .limit(_MAX_ROWS)
        )
    ).all()
    return [
        {
            "candidate_id": row.id,
            "name": row.name,
            "lastname": row.lastname,
            "email": row.email,
            "match_score": 1.0,
            "match_reasons": [IDENTICAL_FILE_REASON],
        }
        for row in rows
    ]


async def find_duplicates_without_llm(
    db: AsyncSession,
    *,
    content: bytes,
    raw_text: str,
    form_email: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Duplikaty rozpoznawalne bez wywołania modelu; pusta lista = nie wiadomo.

    `form_email` to adres z formularza i wygrywa z nagłówkiem pliku, tak jak
    w zapisie: `None` = formularz milczy (bierzemy nagłówek), `""` = rekruter
    adres wyczyścił (kroku e-mail nie ma — inaczej nagłówek blokowałby zapis
    mimo poprawki).

    NIGDY nie rzuca: to optymalizacja kosztu, a nie bramka onboardingu —
    awaria sita ma zostawić dotychczasową ścieżkę nietkniętą.
    """
    try:
        by_hash = await _duplicates_by_file_hash(db, digest=content_digest(content))
        if by_hash:
            return by_hash
    except Exception as exc:  # noqa: BLE001 — sito kosztowe, nie bramka
        logger.warning("[from-cv] sito po bajtach nie zadziałało: %s", exc)

    # Ta sama osoba = ten sam e-mail (12.10.2026). Telefon, LinkedIn oraz imię
    # i nazwisko niczego tu nie przesądzają: imienników i wspólnych numerów
    # w bazie jest wielu, a odmowa zamknęłaby onboarding innej osobie.
    if form_email is None:
        try:
            email = header_email(raw_text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[from-cv] odczyt e-maila z nagłówka nie zadziałał: %s", exc)
            return []
    else:
        email = form_email.strip().lower() or None

    if not email:
        return []

    try:
        return await find_candidate_by_email(db, email)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[from-cv] zapytanie sita o duplikaty nie zadziałało: %s", exc)
        return []


__all__ = [
    "IDENTICAL_FILE_REASON",
    "content_digest",
    "find_duplicates_without_llm",
    "header_email",
]
