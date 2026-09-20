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
2. **Ta sama osoba** — e-mail i telefon wyciągnięte regexem (zero I/O) podane
   do `find_candidate_duplicates`.

Sito jest JEDNOSTRONNE i tylko takie być może: znalezienie duplikatu oszczędza
odczyt, NIEznalezienie niczego nie przesądza. Dlatego skan po płatnym odczycie
w `/from-cv` ZOSTAJE — regex bywa gorszy od modelu i to on jest tu tańszą,
a nie dokładniejszą ścieżką. Usunięcie tamtego skanu zamieniłoby oszczędność
w regres jakości danych.

`force=true` omija oba sita tak samo, jak omijał skan po odczycie.

**Dlaczego telefon TYLKO z nagłówka.** `cv_parser._extract_phone_from_text`
skanuje cały tekst CV, a wzorzec „9 cyfr z separatorami" potrafi zjeść zbitkę
dat („01.02.2020 03.04.2021"). Fałszywe trafienie nie jest tu kosmetyczne:
scraper czyta z odmowy 409 `existing_candidate_id` i wgrywa CV do TEGO profilu,
więc CV obcej osoby wylądowałoby u kogoś innego. Dane kontaktowe stoją
w nagłówku, zbitki dat i kwot niżej — dlatego sito czyta tylko nagłówek.
Pełny skan zostaje ścieżce po płatnym odczycie, gdzie telefon pochodzi z modelu.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.services.dedup_service import find_candidate_duplicates

logger = logging.getLogger(__name__)

#: Powód dopisywany do wiersza duplikatu rozpoznanego po bajtach pliku.
IDENTICAL_FILE_REASON = "identical_file"

#: Ile pierwszych linii CV liczy się jako nagłówek. Ta sama liczba co
#: w `cv_parser._extract_phone_from_text` — tam jest preferencją, tu granicą.
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


def header_phone(raw_text: str) -> Optional[str]:
    """Pierwszy telefon z NAGŁÓWKA CV — patrz uzasadnienie w docstringu modułu."""
    from app.services.cv_parser import _PHONE_PL_RE

    for match in _PHONE_PL_RE.finditer(_header(raw_text)):
        raw = match.group(0).strip(" .-")
        if len(re.sub(r"\D", "", raw)) in (9, 11):
            return raw
    return None


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
) -> list[dict[str, Any]]:
    """Duplikaty rozpoznawalne bez wywołania modelu; pusta lista = nie wiadomo.

    NIGDY nie rzuca: to optymalizacja kosztu, a nie bramka onboardingu —
    awaria sita ma zostawić dotychczasową ścieżkę nietkniętą.
    """
    try:
        by_hash = await _duplicates_by_file_hash(db, digest=content_digest(content))
        if by_hash:
            return by_hash
    except Exception as exc:  # noqa: BLE001 — sito kosztowe, nie bramka
        logger.warning("[from-cv] sito po bajtach nie zadziałało: %s", exc)

    # Samo imię i nazwisko to za słaby sygnał, żeby odmówić założenia kandydata:
    # imienników w bazie jest wielu, a odmowa zamknęłaby onboarding osobie,
    # której CV model przeczytałby poprawnie. LinkedIn świadomie pominięty
    # (decyzja właściciela z 18.09) — sito jest węższe niż skan po odczycie.
    try:
        email = header_email(raw_text)
        phone = header_phone(raw_text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[from-cv] odczyt kontaktu z nagłówka nie zadziałał: %s", exc)
        return []

    if not email and not phone:
        return []

    try:
        return await find_candidate_duplicates(db, email=email, phone=phone)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[from-cv] zapytanie sita o duplikaty nie zadziałało: %s", exc)
        return []


__all__ = [
    "IDENTICAL_FILE_REASON",
    "content_digest",
    "find_duplicates_without_llm",
    "header_email",
    "header_phone",
]
