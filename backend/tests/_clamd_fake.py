"""Udawany clamd dla testów bez Dockera: protokół INSTREAM/PING po TCP.

Odpowiada ``stream: Eicar-Test-Signature FOUND`` na bajty zawierające
łańcuch testowy EICAR, ``stream: OK`` na resztę i ``PONG`` na ``zPING``.
"""

from __future__ import annotations

import asyncio
import struct
from contextlib import asynccontextmanager
from typing import AsyncIterator
import io
import zipfile

# Standardowy plik testowy EICAR (68 bajtów) — nie jest wirusem, każdy
# antywirus rozpoznaje go jako „Eicar-Test-Signature”.
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def eicar_docx() -> bytes:
    """DOCX z wpisem EICAR — przechodzi sprawdzenie formatu CV, a prawdziwy clamd
    1.5 zgłasza ``Eicar-Test-Signature`` (sprawdzone 28.11.2026). Sam EICAR
    w środku PDF-a clamd przepuszcza: sygnatura wymaga go na początku pliku.
    Wpis bez kompresji, więc udawany clamd widzi łańcuch w bajtach."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<w:document/>")
        zf.writestr("word/media/eicar.com", EICAR)
    return buf.getvalue()


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        command = await reader.readuntil(b"\0")
        if command == b"zPING\0":
            writer.write(b"PONG\0")
        elif command == b"zINSTREAM\0":
            data = bytearray()
            while True:
                (size,) = struct.unpack("!I", await reader.readexactly(4))
                if size == 0:
                    break
                data += await reader.readexactly(size)
            verdict = b"Eicar-Test-Signature FOUND" if EICAR in data else b"OK"
            writer.write(b"stream: " + verdict + b"\0")
        else:
            writer.write(b"UNKNOWN COMMAND\0")
        await writer.drain()
    finally:
        writer.close()


@asynccontextmanager
async def fake_clamd() -> AsyncIterator[int]:
    """Serwer na losowym porcie localhost; zwraca port."""
    server = await asyncio.start_server(_handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield port
    finally:
        server.close()
        await server.wait_closed()
