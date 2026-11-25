"""Załącznik ZIP w poczcie rozliczeń → pliki ze środka jako zwykłe załączniki.

Próba IX–X 2026: raport zbiorczy Credit Agricole przychodzi w ZIP-ie z hasłem
(DL przekazuje go na rozliczenia@), a konsultant PKO wysyła „Dokumenty.zip”
z Time Sheetami i mailami odbioru. ZIP nie jest typem dokumentu, więc czytnik
go odrzucał i 6 osobo-miesięcy stało bez MD.

* Rozpakowujemy tylko pliki ``.zip``, które nie są arkuszem ani dokumentem Office
  (XLSX i DOCX też są ZIP-ami). ZIP w ZIP-ie zostaje plikiem.
* Hasło (tradycyjne szyfrowanie PKWARE) bierzemy z ``CONSULTANT_PORTAL_ZIP_PASSWORD``
  (kilka po przecinku), ustawianej workflow „Coolify set env” z sekretu repo
  (decyzja Artura z 23.11.2026). Hasła nie ma w kodzie ani w logach. Plik
  szyfrowany AES (WinZip) zostaje w archiwum: biblioteka standardowa go nie otwiera.
* ZIP, z którego nic nie wyszło (złe hasło, uszkodzony), zostaje na liście jak
  dotąd; czytnik pominie go jako plik spoza listy typów. Plik z uszkodzonym albo
  źle odszyfrowanym strumieniem (``zlib.error`` przy deflate) pomijamy, nie rzucamy.
"""

from __future__ import annotations

import base64
import io
import logging
import lzma
import posixpath
import zipfile
import zlib
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

FILE_ATTACHMENT = "#microsoft.graph.fileAttachment"
#: Limit pliku z archiwum jak limit dokumentu portalu; razem najwyżej ``MAX_TOTAL_BYTES``.
MAX_ENTRY_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_ENTRIES = 50
_OFFICE_MARKERS = ("[Content_Types].xml",)
_UTF8_FLAG = 0x800
_AES = 99
#: Uszkodzony albo źle odszyfrowany strumień pliku. ``zlib.error`` i ``LZMAError`` nie
#: są ``OSError``; wypuszczone z ``expand`` zatrzymywały czytnik poczty na jednym mailu.
_BROKEN_STREAM = (zipfile.BadZipFile, zlib.error, lzma.LZMAError, OSError, EOFError)


def configured_passwords() -> tuple[bytes, ...]:
    raw = settings.CONSULTANT_PORTAL_ZIP_PASSWORD or ""
    return tuple(part.strip().encode() for part in raw.split(",") if part.strip())


def _name(info: zipfile.ZipInfo) -> str:
    """Nazwa bez katalogów. Bez flagi UTF-8 ``zipfile`` czyta CP437, a archiwizator
    Windows pisze polskie nazwy w CP852 („Odbiór usług” jako „Odbiór usêug”).
    Nazwę z pola Unicode Path (Info-ZIP, PKO) ``zipfile`` podaje już poprawnie:
    wtedy ``filename`` różni się od ``orig_filename`` i jej nie ruszamy."""

    name = info.filename
    if not info.flag_bits & _UTF8_FLAG and name == info.orig_filename:
        raw = name.encode("cp437", errors="replace")
        try:
            name = raw.decode("utf-8")
        except UnicodeDecodeError:
            name = raw.decode("cp852", errors="replace")
    return posixpath.basename(name.replace("\\", "/"))


def _read(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, passwords: tuple[bytes, ...]
) -> Optional[bytes]:
    encrypted = bool(info.flag_bits & 0x1)
    if encrypted and info.compress_type == _AES:
        return None
    for password in passwords if encrypted else (None,):
        try:
            with archive.open(info, pwd=password) as handle:
                data = handle.read(MAX_ENTRY_BYTES + 1)
        except RuntimeError:  # złe hasło
            continue
        except _BROKEN_STREAM:
            # Bajt kontrolny ZipCrypto przepuszcza co 256. złe hasło: odszyfrowany
            # strumień to wtedy śmieci (CRC, deflate, bzip2, lzma) i próbujemy dalej.
            # Bez hasła to uszkodzony plik.
            if encrypted:
                continue
            return None
        except NotImplementedError:  # metoda kompresji spoza biblioteki standardowej
            return None
        return data if len(data) <= MAX_ENTRY_BYTES else None
    return None


def _entries(content: bytes, passwords: tuple[bytes, ...]) -> list[tuple[str, bytes]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, OSError):
        return []
    with archive:
        infos = archive.infolist()
        names = {info.filename for info in infos}
        if any(marker in names for marker in _OFFICE_MARKERS):
            return []
        found: list[tuple[str, bytes]] = []
        total = skipped = 0
        for info in infos[:MAX_ENTRIES]:
            name = _name(info)
            if info.is_dir() or not name or name.startswith("."):
                continue
            data = _read(archive, info, passwords)
            if data is None or total + len(data) > MAX_TOTAL_BYTES:
                skipped += 1
                continue
            total += len(data)
            found.append((name, data))
        if skipped:
            logger.warning(
                "rozliczenia: %d plików z ZIP-a nie otwarto (hasło, AES albo rozmiar)",
                skipped,
            )
        return found


def expand(
    files: list[dict[str, Any]], *, passwords: tuple[bytes, ...]
) -> list[dict[str, Any]]:
    """Lista załączników z ZIP-ami zastąpionymi przez ich pliki (jeden poziom)."""

    out: list[dict[str, Any]] = []
    for attachment in files:
        name = str(attachment.get("name") or "")
        raw = attachment.get("contentBytes")
        if (
            attachment.get("@odata.type") != FILE_ATTACHMENT
            or attachment.get("isInline")
            or not name.lower().endswith(".zip")
            or not isinstance(raw, str)
        ):
            out.append(attachment)
            continue
        try:
            content = base64.b64decode(raw, validate=True)
        except ValueError:
            out.append(attachment)
            continue
        entries = _entries(content, passwords)
        if not entries:
            out.append(attachment)
            continue
        out.extend(
            {
                "@odata.type": FILE_ATTACHMENT,
                "name": inner,
                "isInline": False,
                "contentBytes": base64.b64encode(data).decode(),
            }
            for inner, data in entries
        )
    return out
