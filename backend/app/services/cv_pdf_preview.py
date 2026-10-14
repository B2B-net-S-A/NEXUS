"""Strony CV jak w pliku: PDF z pliku Word (Edytor CV 3, decyzja J2 Artura, 14.10.2026).

Podgląd CV w przeglądarce (docx-preview) nie dzieli dokumentu na strony,
nie pokazuje klauzuli zgody przypiętej do dołu ostatniej strony i zależy od
czcionek zainstalowanych u oglądającego. Zespół mówił, że „podgląd wygląda
okropnie, a po pobraniu normalnie”. Ten moduł zamienia TEN SAM plik Word,
który pobiera „Pobierz Word”, na PDF przez LibreOffice w kontenerze backendu
(z czcionką Montserrat z `app/assets/fonts/`) — podgląd pokazuje wtedy
prawdziwe strony A4, tak samo na każdym komputerze.

- Plik Word pozostaje jedynym źródłem; PDF służy do podglądu i do „Pobierz PDF”.
- Jedna zamiana naraz (LibreOffice to ciężki proces), z limitem czasu; proces
  i jego dzieci giną razem (osobna grupa procesów). Kolejka czeka w pętli
  zdarzeń (`pdf_from_docx`), nie w wątkach wspólnej puli — czekające żądania
  nie mogą zablokować innych tras; najwyżej `MAX_WAITING` czeka, reszta od
  razu dostaje „podgląd niedostępny”.
- Wynik pamiętany po SHA-256 treści pliku Word (ograniczona pamięć procesu),
  więc ponowne otwarcie tej samej wersji nie płaci drugi raz. Klucz liczy się
  z części archiwum, nie z bajtów pliku: szkic składany od nowa z tej samej
  treści różni się tylko czasem zapisu w ZIP-ie.
- Każda awaria to `PdfPreviewUnavailable` — trasa odpowiada 503, a przeglądarka
  pokazuje dotychczasowy podgląd pliku. Brak LibreOffice (np. lokalnie, w CI)
  nie może wywrócić niczego poza samym podglądem stron.
"""

import asyncio
import hashlib
import io
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import zipfile
from collections import OrderedDict
from typing import Callable, Optional

from anyio import to_thread

logger = logging.getLogger(__name__)

SOFFICE_ENV = "CV_PDF_SOFFICE"
TIMEOUT_S = 45
# Ile żądanie czeka na wolne miejsce, zanim podgląd wróci do zapasu.
WAIT_S = 30
MAX_DOCX_BYTES = 20 * 1024 * 1024
# Ile żądań może czekać w kolejce na zamianę; następne — od razu zapas.
MAX_WAITING = 4
# Zmienne środowiska przekazywane LibreOffice — bez sekretów aplikacji.
_ENV_KEEP = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "FONTCONFIG_PATH", "FONTCONFIG_FILE")
MAX_ENTRIES = 32
TTL_S = 30 * 60

MSG_UNAVAILABLE = (
    "Podgląd stron jest chwilowo niedostępny. Plik Word pobierzesz jak zwykle."
)


class PdfPreviewUnavailable(RuntimeError):
    """PDF nie powstał — trasa odpowiada 503, przeglądarka pokazuje zapas."""


_slot = threading.BoundedSemaphore(1)
_queue = asyncio.Lock()
_waiting = 0
_cache_lock = threading.Lock()
_cache: "OrderedDict[str, tuple[float, bytes]]" = OrderedDict()


def soffice_path() -> Optional[str]:
    """Plik wykonywalny LibreOffice albo `None`, gdy go nie ma."""
    return shutil.which(os.getenv(SOFFICE_ENV) or "soffice")


def _cached(key: str, now: float) -> Optional[bytes]:
    with _cache_lock:
        hit = _cache.get(key)
        if hit is None:
            return None
        stored_at, pdf = hit
        if now - stored_at > TTL_S:
            del _cache[key]
            return None
        _cache.move_to_end(key)
        return pdf


def _store(key: str, pdf: bytes, now: float) -> None:
    with _cache_lock:
        _cache[key] = (now, pdf)
        _cache.move_to_end(key)
        for stale in [k for k, (at, _) in _cache.items() if now - at > TTL_S]:
            del _cache[stale]
        while len(_cache) > MAX_ENTRIES:
            _cache.popitem(last=False)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _kill_group(process: subprocess.Popen) -> None:
    """Zabija proces LibreOffice razem z dziećmi (`soffice` uruchamia `soffice.bin`)."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        logger.warning("[cv_pdf_preview] LibreOffice nie zakończył się po SIGKILL")


def _convert(binary: str, docx: bytes) -> bytes:
    try:
        return _run(binary, docx)
    except OSError as error:
        # Brak pamięci na fork, pełny /tmp, plik, którego nie da się uruchomić —
        # też tylko „podgląd niedostępny”, nie 500.
        logger.warning("[cv_pdf_preview] LibreOffice nie ruszył: %s", error)
        raise PdfPreviewUnavailable("os") from error


def _run(binary: str, docx: bytes) -> bytes:
    with tempfile.TemporaryDirectory(prefix="cv-pdf-") as tmp:
        source = os.path.join(tmp, "cv.docx")
        with open(source, "wb") as handle:
            handle.write(docx)
        command = [
            binary,
            # Własny profil na każdą zamianę: brak blokad współdzielonego profilu
            # i brak śladów po poprzednich plikach.
            f"-env:UserInstallation=file://{tmp}/profile",
            "--headless",
            "--invisible",
            "--nologo",
            "--norestore",
            "--nolockcheck",
            "--nodefault",
            "--convert-to",
            "pdf:writer_pdf_Export",
            "--outdir",
            tmp,
            source,
        ]
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
            env={
                **{key: os.environ[key] for key in _ENV_KEEP if key in os.environ},
                "HOME": tmp,
                "TMPDIR": tmp,
            },
        )
        try:
            _, stderr = process.communicate(timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired as error:
            _kill_group(process)
            raise PdfPreviewUnavailable("timeout") from error
        finally:
            # Proces główny skończył, ale dziecko mogło zostać.
            _kill_group(process)
        target = os.path.join(tmp, "cv.pdf")
        if process.returncode != 0 or not os.path.exists(target):
            logger.warning(
                "[cv_pdf_preview] LibreOffice exit=%s stderr=%s",
                process.returncode,
                (stderr or b"")[:300].decode("utf-8", "replace"),
            )
            raise PdfPreviewUnavailable(f"exit {process.returncode}")
        with open(target, "rb") as handle:
            pdf = handle.read()
    if not pdf.startswith(b"%PDF"):
        raise PdfPreviewUnavailable("not a pdf")
    return pdf


def _uses_montserrat(docx: bytes) -> bool:
    """Czy plik Word pisze czcionką szablonu CV (Montserrat)."""
    try:
        with zipfile.ZipFile(io.BytesIO(docx)) as archive:
            names = set(archive.namelist())
            for part in ("word/document.xml", "word/styles.xml"):
                if part in names and b"Montserrat" in archive.read(part):
                    return True
    except (zipfile.BadZipFile, KeyError, OSError):
        return False
    return False


def _cache_key(docx: bytes) -> str:
    """SHA-256 części pliku Word (nazwa + treść), bez czasów zapisu z ZIP-a."""
    digest = hashlib.sha256()
    try:
        with zipfile.ZipFile(io.BytesIO(docx)) as archive:
            for name in sorted(archive.namelist()):
                data = archive.read(name)
                digest.update(f"{name}\0{len(data)}\0".encode())
                digest.update(data)
    except (zipfile.BadZipFile, KeyError, OSError, RuntimeError):
        return hashlib.sha256(docx).hexdigest()
    return digest.hexdigest()


def docx_to_pdf(docx: bytes, *, clock: Callable[[], float] = time.monotonic) -> bytes:
    """PDF z pliku Word (synchronicznie — wołać przez `run_in_threadpool`)."""
    if not docx or len(docx) > MAX_DOCX_BYTES:
        raise PdfPreviewUnavailable("size")
    key = _cache_key(docx)
    hit = _cached(key, clock())
    if hit is not None:
        return hit
    binary = soffice_path()
    if binary is None:
        raise PdfPreviewUnavailable("no soffice")
    if not _slot.acquire(timeout=WAIT_S):
        raise PdfPreviewUnavailable("busy")
    try:
        # Inne żądanie mogło właśnie zamienić ten sam plik.
        hit = _cached(key, clock())
        if hit is not None:
            return hit
        started = time.monotonic()
        pdf = _convert(binary, docx)
        # Bez Montserrat w obrazie LibreOffice podstawia inną czcionkę i strony
        # wyglądają inaczej niż Word u klienta — wtedy lepiej pokazać zapas.
        if _uses_montserrat(docx) and b"Montserrat" not in pdf:
            logger.error(
                "[cv_pdf_preview] PDF bez czcionki Montserrat — sprawdź "
                "`fc-list | grep Montserrat` w kontenerze backendu"
            )
            raise PdfPreviewUnavailable("fonts")
        logger.info(
            "[cv_pdf_preview] PDF %d B w %.2f s", len(pdf), time.monotonic() - started
        )
    finally:
        _slot.release()
    _store(key, pdf, clock())
    return pdf


def cached_pdf(
    docx: bytes, *, clock: Callable[[], float] = time.monotonic
) -> Optional[bytes]:
    """PDF z pamięci albo `None` — bez czekania i bez zamiany."""
    if not docx or len(docx) > MAX_DOCX_BYTES:
        return None
    return _cached(_cache_key(docx), clock())


async def pdf_from_docx(docx: bytes) -> bytes:
    """Wejście dla tras: pamięć → kolejka w pętli zdarzeń → zamiana w jednym wątku."""
    global _waiting
    hit = cached_pdf(docx)
    if hit is not None:
        return hit
    if _waiting >= MAX_WAITING:
        raise PdfPreviewUnavailable("queue full")
    _waiting += 1
    try:
        await asyncio.wait_for(_queue.acquire(), timeout=WAIT_S)
    except asyncio.TimeoutError as error:
        raise PdfPreviewUnavailable("busy") from error
    finally:
        _waiting -= 1
    try:
        return await to_thread.run_sync(docx_to_pdf, docx)
    finally:
        _queue.release()
