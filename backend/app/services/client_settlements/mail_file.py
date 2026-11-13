"""Odczyt maila zapisanego jako plik: MSG z Outlooka albo EML. Bez zależności.

Rozliczenia przyjmują maile z akceptacją jako pliki (``cp_documents``), a mail
z Jiry Aliora (E6.3) niesie w treści opiekuna i czas akceptacji, a w załączniku
KEŚU. MSG to kontener OLE (Compound File Binary); czytamy z niego tylko temat,
nadawcę, treść tekstową i załączniki plikowe. Uszkodzony plik daje ``None``,
nigdy wyjątek, bo plik przychodzi z zewnątrz.
"""

from __future__ import annotations

import email
import email.policy
import logging
import struct
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

MSG_MIME = "application/vnd.ms-outlook"
EML_MIME = "message/rfc822"
OLE_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_FREE, _END = 0xFFFFFFFF, 0xFFFFFFFE
#: Granice ochronne: plik rozliczenia ma najwyżej kilka MB.
_MAX_SECTORS = 200_000
_MAX_ENTRIES = 20_000


@dataclass
class Attachment:
    name: str
    content: bytes


@dataclass
class MailFile:
    subject: str
    sender: str
    body: str
    attachments: list[Attachment] = field(default_factory=list)


class _Broken(Exception):
    pass


class _Cfb:
    """Minimalny czytnik Compound File Binary (MS-CFB), tylko odczyt."""

    def __init__(self, data: bytes) -> None:
        if len(data) < 512 or not data.startswith(OLE_HEADER):
            raise _Broken("header")
        self.data = data
        self.sector = 1 << struct.unpack_from("<H", data, 0x1E)[0]
        self.mini = 1 << struct.unpack_from("<H", data, 0x20)[0]
        if self.sector not in (512, 4096) or self.mini != 64:
            raise _Broken("sector size")
        fat_count = struct.unpack_from("<I", data, 0x2C)[0]
        dir_start = struct.unpack_from("<I", data, 0x30)[0]
        self.cutoff = struct.unpack_from("<I", data, 0x38)[0]
        minifat_start, _minifat_count, difat_start, difat_count = struct.unpack_from(
            "<IIII", data, 0x3C
        )
        difat = list(struct.unpack_from("<109I", data, 0x4C))
        per = self.sector // 4
        current, guard = difat_start, 0
        while current not in (_FREE, _END) and difat_count > 0 and guard < 10_000:
            values = struct.unpack_from(f"<{per}I", data, self._offset(current))
            difat.extend(values[:-1])
            current, difat_count, guard = values[-1], difat_count - 1, guard + 1
        self.fat: list[int] = []
        for index in difat[:fat_count]:
            if index in (_FREE, _END):
                continue
            self.fat.extend(struct.unpack_from(f"<{per}I", data, self._offset(index)))
        self.minifat = (
            list(struct.unpack(f"<{len(raw) // 4}I", raw))
            if (raw := self._chain(minifat_start))
            else []
        )
        directory = self._chain(dir_start)
        self.entries: list[dict[str, int | str]] = []
        for i in range(min(len(directory) // 128, _MAX_ENTRIES)):
            entry = directory[i * 128 : (i + 1) * 128]
            length = struct.unpack_from("<H", entry, 0x40)[0]
            name = entry[: max(min(length, 64) - 2, 0)].decode("utf-16-le", "replace")
            left, right, child = struct.unpack_from("<III", entry, 0x44)
            start, size = struct.unpack_from("<IQ", entry, 0x74)
            self.entries.append(
                {
                    "name": name,
                    "type": entry[0x42],
                    "left": left,
                    "right": right,
                    "child": child,
                    "start": start,
                    "size": size & 0xFFFFFFFF,
                }
            )
        if not self.entries:
            raise _Broken("directory")
        root = self.entries[0]
        self.ministream = (
            self._chain(int(root["start"]))[: int(root["size"])]
            if root["start"] not in (_FREE, _END)
            else b""
        )

    def _offset(self, sector: int) -> int:
        offset = (sector + 1) * self.sector
        if offset + self.sector > len(self.data):
            raise _Broken("sector out of file")
        return offset

    def _chain(self, start: int) -> bytes:
        parts: list[bytes] = []
        current, steps = start, 0
        while current not in (_FREE, _END) and steps < _MAX_SECTORS:
            if current >= len(self.fat):
                raise _Broken("fat")
            offset = self._offset(current)
            parts.append(self.data[offset : offset + self.sector])
            current, steps = self.fat[current], steps + 1
        return b"".join(parts)

    def read(self, index: int) -> bytes:
        entry = self.entries[index]
        size = int(entry["size"])
        if size < self.cutoff:
            parts: list[bytes] = []
            current, steps = int(entry["start"]), 0
            while current not in (_FREE, _END) and steps < _MAX_SECTORS:
                if current >= len(self.minifat):
                    raise _Broken("minifat")
                parts.append(
                    self.ministream[current * self.mini : (current + 1) * self.mini]
                )
                current, steps = self.minifat[current], steps + 1
            return b"".join(parts)[:size]
        return self._chain(int(entry["start"]))[:size]

    def children(self, index: int) -> dict[str, int]:
        """Dzieci magazynu: nazwa → indeks wpisu."""

        out: dict[str, int] = {}
        stack = [int(self.entries[index]["child"])]
        seen: set[int] = set()
        while stack:
            current = stack.pop()
            if current in (_FREE, _END) or current >= len(self.entries):
                continue
            if current in seen:
                raise _Broken("cycle")
            seen.add(current)
            entry = self.entries[current]
            out[str(entry["name"])] = current
            stack.extend((int(entry["left"]), int(entry["right"])))
        return out


def _text(cfb: _Cfb, items: dict[str, int], prop: str) -> str:
    """Właściwość tekstowa MAPI: Unicode (001F), a w starszych plikach 8-bit (001E)."""

    if (index := items.get(f"__substg1.0_{prop}001F")) is not None:
        return cfb.read(index).decode("utf-16-le", "replace").rstrip("\x00")
    if (index := items.get(f"__substg1.0_{prop}001E")) is not None:
        return cfb.read(index).decode("cp1250", "replace").rstrip("\x00")
    return ""


def _read_msg(content: bytes) -> MailFile:
    cfb = _Cfb(content)
    top = cfb.children(0)
    mail = MailFile(
        subject=_text(cfb, top, "0037"),
        sender=_text(cfb, top, "0C1F") or _text(cfb, top, "0065"),
        body=_text(cfb, top, "1000"),
    )
    for name, index in sorted(top.items()):
        if not name.startswith("__attach_version1.0_#"):
            continue
        items = cfb.children(index)
        data_index = items.get("__substg1.0_37010102")
        if data_index is None:
            continue  # wiadomość osadzona albo obiekt OLE: pomijamy
        file_name = _text(cfb, items, "3707") or _text(cfb, items, "3704")
        mail.attachments.append(Attachment(file_name, cfb.read(data_index)))
    return mail


def _read_eml(content: bytes) -> MailFile:
    message = email.message_from_bytes(content, policy=email.policy.default)
    body_part = message.get_body(preferencelist=("plain", "html"))
    body = body_part.get_content() if body_part is not None else ""
    mail = MailFile(
        subject=str(message.get("subject") or ""),
        sender=str(message.get("from") or ""),
        body=body if isinstance(body, str) else "",
    )
    for part in message.iter_attachments():
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            mail.attachments.append(Attachment(part.get_filename() or "", payload))
    return mail


def read(content: bytes, mime: str) -> Optional[MailFile]:
    """Mail z pliku MSG albo EML; plik nieczytelny albo inny typ = ``None``."""

    try:
        if mime == MSG_MIME:
            return _read_msg(content)
        if mime == EML_MIME:
            return _read_eml(content)
    except (_Broken, struct.error, IndexError, ValueError, LookupError) as exc:
        logger.info("mail_file: plik nieczytelny (%s)", type(exc).__name__)
    return None
