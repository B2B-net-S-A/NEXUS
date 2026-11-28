"""Skan antywirusowy plików z zewnątrz przez clamd (ClamAV, GPL-2.0).

Decyzja Artura z 28.11.2026 (pakiet „Ochrona wejścia”). Bajty idą do clamd
po TCP komendą ``INSTREAM`` ZANIM plik trafi do magazynu, bazy albo
ekstraktora tekstu. Reguła i uzasadnienie polityk:
``docs/claude/podstawy/skan-plikow-i-altcha.md``.

* **Publiczne wejście** (formularz kariery, link ``/apply``, serwer strony WWW)
  — ``require_clean_public_upload``: wirus = 422 przy polu ``cv``, clamd
  niedostępny = 503 (fail-closed: plik z internetu bez skanu nie wchodzi).
* **Wewnętrzne** (rekruter wgrywa CV, załączniki z poczty) — ``scan_internal``:
  wirus = odmowa u wołającego, clamd niedostępny = przepuszczamy z ostrzeżeniem
  w logu (fail-open: awaria skanera nie może zatrzymać pracy zespołu).

Każdy wynik to linia JSON ``event_kind="file_scan"`` (Loki i Wazuh). W logu nie
ma nazwy pliku (zwykle imię i nazwisko kandydata) — tylko skrót SHA-256,
rozmiar, źródło i nazwa sygnatury.
"""

from __future__ import annotations

import asyncio
import enum
import hashlib
import logging
import struct
from contextlib import suppress
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)

MSG_REJECTED = "Nie udało się przyjąć pliku. Wyślij CV ponownie w PDF albo DOCX."
MSG_UNAVAILABLE = "Nie możemy teraz sprawdzić pliku. Spróbuj ponownie za kilka minut."
MSG_INTERNAL_INFECTED = "Skaner antywirusowy odrzucił ten plik. Nie został zapisany."

_CHUNK = 64 * 1024
# Odpowiedź clamd to jedna krótka linia; zapas na długą nazwę sygnatury.
_MAX_REPLY = 4096


class Verdict(str, enum.Enum):
    CLEAN = "clean"
    INFECTED = "infected"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


@dataclass(frozen=True)
class ScanResult:
    verdict: Verdict
    signature: Optional[str] = None
    failure_kind: Optional[str] = None


def enabled() -> bool:
    return bool((settings.CLAMAV_HOST or "").strip())


async def _command(payload: bytes, *, content: Optional[bytes] = None) -> str:
    """Jedna komenda clamd w trybie ``z`` (zakończona NUL), odpowiedź bez NUL."""
    reader, writer = await asyncio.open_connection(
        settings.CLAMAV_HOST.strip(), settings.CLAMAV_PORT
    )
    try:
        writer.write(payload)
        if content is not None:
            view = memoryview(content)
            for start in range(0, len(view), _CHUNK):
                chunk = view[start : start + _CHUNK]
                writer.write(struct.pack("!I", len(chunk)))
                writer.write(chunk)
                await writer.drain()
            writer.write(struct.pack("!I", 0))
        await writer.drain()
        raw = await reader.readuntil(b"\0")
        if len(raw) > _MAX_REPLY:
            raise ValueError("clamd reply too long")
        return raw.rstrip(b"\0").decode("utf-8", "replace").strip()
    finally:
        writer.close()
        with suppress(Exception):
            await writer.wait_closed()


def parse_reply(reply: str) -> ScanResult:
    """``stream: OK`` / ``stream: <sygnatura> FOUND`` / ``… ERROR``."""
    body = reply.split(":", 1)[1].strip() if ":" in reply else reply.strip()
    if body == "OK":
        return ScanResult(Verdict.CLEAN)
    if body.endswith(" FOUND"):
        return ScanResult(Verdict.INFECTED, signature=body[: -len(" FOUND")][:200])
    return ScanResult(Verdict.UNAVAILABLE, failure_kind="clamd_error")


async def scan_bytes(content: bytes) -> ScanResult:
    """Skan bajtów; nigdy nie rzuca — awaria to ``UNAVAILABLE``."""
    if not enabled():
        return ScanResult(Verdict.DISABLED)
    try:
        reply = await asyncio.wait_for(
            _command(b"zINSTREAM\0", content=content),
            timeout=settings.CLAMAV_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 — każda awaria = brak werdyktu
        return ScanResult(Verdict.UNAVAILABLE, failure_kind=type(exc).__name__)
    return parse_reply(reply)


async def ping(timeout: float = 2.0) -> str:
    """Sonda ``/api/health``: ``disabled`` / ``healthy`` / ``unhealthy``."""
    if not enabled():
        return "disabled"
    try:
        reply = await asyncio.wait_for(_command(b"zPING\0"), timeout=timeout)
    except Exception:  # noqa: BLE001 — sonda informacyjna
        return "unhealthy"
    return "healthy" if reply == "PONG" else "unhealthy"


def _log(result: ScanResult, content: bytes, *, source: str, policy: str) -> None:
    fields = {
        "event_kind": "file_scan",
        "scan_verdict": result.verdict.value,
        "scan_source": source,
        "scan_policy": policy,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    if result.signature:
        fields["signature"] = result.signature
    if result.failure_kind:
        fields["failure_kind"] = result.failure_kind
    if result.verdict is Verdict.INFECTED:
        logger.warning("file_scan", extra=fields)
    elif result.verdict is Verdict.UNAVAILABLE:
        # Publiczny formularz odmawia (error), wewnętrzny przepuszcza (warning).
        level = logging.ERROR if policy == "fail_closed" else logging.WARNING
        logger.log(level, "file_scan", extra=fields)
    elif result.verdict is Verdict.CLEAN:
        logger.info("file_scan", extra=fields)


async def require_clean_public_upload(content: bytes, *, source: str) -> None:
    """Publiczne wejście: wirus = 422 przy ``cv``, brak skanera = 503."""
    from app.services.public_apply import field_error

    result = await scan_bytes(content)
    _log(result, content, source=source, policy="fail_closed")
    if result.verdict is Verdict.INFECTED:
        raise field_error("cv", MSG_REJECTED)
    if result.verdict is Verdict.UNAVAILABLE:
        raise HTTPException(status_code=503, detail=MSG_UNAVAILABLE)


async def scan_internal(content: bytes, *, source: str) -> ScanResult:
    """Wewnętrzne wejście: zwraca wynik; o odmowie przy wirusie decyduje wołający."""
    result = await scan_bytes(content)
    _log(result, content, source=source, policy="fail_open")
    return result


async def require_clean_internal_upload(content: bytes, *, source: str) -> None:
    """Upload w aplikacji: wirus = 422, brak skanera = przepuszczamy (fail-open)."""
    result = await scan_internal(content, source=source)
    if result.verdict is Verdict.INFECTED:
        raise HTTPException(status_code=422, detail=MSG_INTERNAL_INFECTED)
