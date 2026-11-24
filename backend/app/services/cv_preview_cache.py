"""Odczyty CV z okna „Dodaj kandydata” (`/cv/preview` → `/from-cv`) w bazie.

Do 24.11.2026 była to pamięć procesu. Przy dwóch procesach web
(``NEXUS_WEB_CONCURRENCY=2``) `/from-cv`, który trafił do innego procesu niż podgląd,
czytał CV modelem drugi raz (koszt) i mógł zapisać inny odczyt niż ten, który rekruter
widział w formularzu. Teraz tabela ``cv_preview_reads`` (0770,
``cv_preview_reads_schema.py``). → docs/claude/podstawy/kilka-procesow-web.md

- klucz: SHA-256 treści pliku,
- najwyżej ``MAX_ENTRIES`` wierszy (najdawniej użyty wypada pierwszy),
- TTL ``TTL_SECONDS``; wygasłe wiersze kasuje każdy zapis i każdy odczyt, a wiersz
  pliku znika po zapisie kandydata (``forget``),
- tekst CV dłuższy niż ``MAX_RAW_TEXT_CHARS`` nie jest trzymany (``None``) —
  `/from-cv` odczyta go wtedy z pliku ponownie (bez modelu, lokalnie),
- pierwszy zapis wygrywa: póki wiersz żyje, odczyt tego samego pliku w drugim procesie
  (``cache_single_flight`` jest per proces) go nie nadpisuje, a podgląd pokazuje to,
  co leży w tabeli. `/from-cv` zapisze więc ten odczyt, który widział człowiek,
- odczyt i tekst są zaszyfrowane (Fernet) kluczem z bajtów pliku, nie z ``sha256``:
  wiersz da się odczytać tylko z tym samym plikiem w ręku. Kopia bazy (06:30 UTC,
  14 dni), staging z kopii i odczyt produkcji nie dostają CV z porzuconych podglądów,
  więc retencja zostaje taka jak przy pamięci procesu,
- każda operacja ma własną krótką sesję. Zapis widać od razu w drugim procesie (i
  w żądaniu czekającym na ``cache_single_flight``), sesja żądania zostaje bez zapisów
  (``release_idle_connection`` na czas modelu), a awaria tabeli to odczyt modelem jak
  przed tą zmianą, nie błąd dodania kandydata. W logu tylko typ błędu, nigdy treść.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

MAX_ENTRIES = 64
TTL_SECONDS = 30 * 60
MAX_RAW_TEXT_CHARS = 200_000

# Zmiana etykiety unieważnia wszystkie wiersze: odczytają się jak brak wpisu.
_KEY_LABEL = b"nexus:cv-preview-read:v1"

_SWEEP = text("DELETE FROM cv_preview_reads WHERE expires_at <= now()")
# Bez nadpisania: żywy wiersz tego pliku zostaje (wygasłe usunął już `_SWEEP`).
_INSERT = text(
    """
    INSERT INTO cv_preview_reads (sha256, payload, expires_at, used_at)
    VALUES (
        :sha256,
        :payload,
        now() + CAST(:ttl_seconds AS integer) * INTERVAL '1 second',
        clock_timestamp()
    )
    ON CONFLICT (sha256) DO NOTHING
    RETURNING sha256
    """
)
# Tylko gdy żywego wiersza nie da się odczytać (np. inna etykieta klucza).
_UPSERT = text(
    """
    INSERT INTO cv_preview_reads (sha256, payload, expires_at, used_at)
    VALUES (
        :sha256,
        :payload,
        now() + CAST(:ttl_seconds AS integer) * INTERVAL '1 second',
        clock_timestamp()
    )
    ON CONFLICT (sha256) DO UPDATE
       SET payload = EXCLUDED.payload,
           expires_at = EXCLUDED.expires_at,
           used_at = EXCLUDED.used_at
    """
)
_TRIM = text(
    """
    DELETE FROM cv_preview_reads
     WHERE sha256 IN (
        SELECT sha256 FROM cv_preview_reads
         ORDER BY used_at DESC, sha256 DESC
         OFFSET :max_entries
     )
    """
)
_TOUCH = text(
    """
    UPDATE cv_preview_reads
       SET used_at = clock_timestamp()
     WHERE sha256 = :sha256 AND expires_at > now()
    RETURNING payload
    """
)
_DELETE = text("DELETE FROM cv_preview_reads WHERE sha256 = :sha256")


@dataclass(frozen=True)
class CachedCvRead:
    parsed: dict[str, Any]
    raw_text: Optional[str]


def content_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _cipher(content: bytes) -> Fernet:
    # HMAC z etykietą, nie ``content_sha256``: z klucza wiersza nie da się wyliczyć
    # klucza szyfrowania, trzeba mieć plik.
    digest = hmac.new(_KEY_LABEL, content, hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _seal(content: bytes, read: CachedCvRead) -> bytes:
    body = json.dumps(
        {"parsed": read.parsed, "raw_text": read.raw_text}, ensure_ascii=False
    )
    return _cipher(content).encrypt(body.encode("utf-8"))


def _unseal(content: bytes, payload: bytes) -> Optional[CachedCvRead]:
    try:
        body = json.loads(_cipher(content).decrypt(bytes(payload)))
    except (InvalidToken, TypeError, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    parsed, raw_text = body.get("parsed"), body.get("raw_text")
    if not isinstance(parsed, dict) or not (
        raw_text is None or isinstance(raw_text, str)
    ):
        return None
    return CachedCvRead(parsed=parsed, raw_text=raw_text)


async def _touch(session: AsyncSession, content: bytes) -> Optional[CachedCvRead]:
    result = await session.execute(_TOUCH, {"sha256": content_sha256(content)})
    payload = result.scalar_one_or_none()
    return None if payload is None else _unseal(content, payload)


def _log_failure(action: str, exc: BaseException) -> None:
    logger.warning(
        "[cv_preview] %s: błąd tabeli cv_preview_reads (%s)",
        action,
        type(exc).__name__,
    )


async def recall(content: bytes) -> Optional[CachedCvRead]:
    """Odczyt z podglądu tego pliku albo ``None`` (brak, wygasł, tabela niedostępna)."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(_SWEEP)
            read = await _touch(session, content)
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — bez wpisu `/from-cv` czyta CV modelem
        _log_failure("odczyt", exc)
        return None
    return read


async def remember(
    content: bytes, *, parsed: dict[str, Any], raw_text: str
) -> Optional[CachedCvRead]:
    """Zapisz odczyt z podglądu i zwróć ten, który leży w tabeli.

    Żywy wiersz tego pliku zostaje (pierwszy zapis wygrywa) i to jego odczyt wraca do
    podglądu. ``None`` = nic nie zapisano (wyłączone, typy spoza JSON, awaria tabeli):
    podgląd pokazuje wtedy własny odczyt, a `/from-cv` przeczyta CV modelem.
    """
    if TTL_SECONDS <= 0 or MAX_ENTRIES <= 0:
        return None
    kept_text = raw_text if len(raw_text) <= MAX_RAW_TEXT_CHARS else None
    read = CachedCvRead(parsed=parsed, raw_text=kept_text)
    try:
        payload = _seal(content, read)
    except (TypeError, ValueError) as exc:
        logger.warning(
            "[cv_preview] odczyt bez zapisu, wartość spoza JSON (%s)",
            type(exc).__name__,
        )
        return None
    params = {
        "sha256": content_sha256(content),
        "payload": payload,
        "ttl_seconds": int(TTL_SECONDS),
    }
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(_SWEEP)
            inserted = (await session.execute(_INSERT, params)).scalar_one_or_none()
            stored = read if inserted is not None else await _touch(session, content)
            if stored is None:
                await session.execute(_UPSERT, params)
                stored = read
            await session.execute(_TRIM, {"max_entries": int(MAX_ENTRIES)})
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — podgląd działa i bez wpisu
        _log_failure("zapis", exc)
        return None
    return stored


async def forget(content: bytes) -> None:
    """Kandydat zapisany — odczyt z podglądu zrobił swoje, wiersz znika."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(_DELETE, {"sha256": content_sha256(content)})
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — wiersz i tak wygaśnie po TTL
        _log_failure("kasowanie", exc)
