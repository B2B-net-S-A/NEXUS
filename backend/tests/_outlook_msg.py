"""Próbny plik MSG (Outlook) do testów: kontener OLE z tematem, treścią i załącznikami.

Prawdziwe maile z Jiry klienta mają nazwiska, adresy i telefony, więc do repo
nie trafiają. Ten zapis tworzy ten sam układ właściwości MAPI, który czyta
``mail_file``: temat (0037), nadawca (0C1F), treść (1000), a w magazynach
``__attach_version1.0_#…`` dane (3701) i nazwa (3707). Strumienie mają własne
sektory (próg mini-strumienia 0 w nagłówku), a drzewo katalogu to łańcuch
prawych sąsiadów — oba warianty są zgodne z MS-CFB i czytnik musi je przyjąć.
"""

from __future__ import annotations

import struct

SECTOR = 512
_FREE, _END, _FAT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD


def _utf16(text: str) -> bytes:
    return text.encode("utf-16-le")


def build_msg(
    *, subject: str, sender: str, body: str, attachments: list[tuple[str, bytes]]
) -> bytes:
    # (nazwa, typ 1=magazyn 2=strumień 5=korzeń, rodzic, dane)
    nodes: list[tuple[str, int, int, bytes]] = [("Root Entry", 5, -1, b"")]
    nodes += [
        ("__substg1.0_0037001F", 2, 0, _utf16(subject)),
        ("__substg1.0_0C1F001F", 2, 0, _utf16(sender)),
        ("__substg1.0_1000001F", 2, 0, _utf16(body)),
    ]
    for index, (name, content) in enumerate(attachments):
        nodes.append((f"__attach_version1.0_#{index:08X}", 1, 0, b""))
        parent = len(nodes) - 1
        nodes.append(("__substg1.0_3707001F", 2, parent, _utf16(name)))
        nodes.append(("__substg1.0_37010102", 2, parent, content))

    sectors: list[bytes] = []
    fat: list[int] = []

    def chain(data: bytes) -> int:
        if not data:
            return _END
        first = len(sectors)
        parts = [data[i : i + SECTOR] for i in range(0, len(data), SECTOR)]
        for offset, part in enumerate(parts):
            sectors.append(part.ljust(SECTOR, b"\x00"))
            fat.append(first + offset + 1 if offset < len(parts) - 1 else _END)
        return first

    starts = [chain(data) for _name, _kind, _parent, data in nodes]
    children: dict[int, list[int]] = {}
    for index, (_name, _kind, parent, _data) in enumerate(nodes):
        if parent >= 0:
            children.setdefault(parent, []).append(index)
    entries = b""
    for index, (name, kind, _parent, data) in enumerate(nodes):
        kids = children.get(index, [])
        siblings = children.get(nodes[index][2], []) if index else []
        position = siblings.index(index) if index else -1
        right = siblings[position + 1] if 0 <= position < len(siblings) - 1 else _FREE
        raw_name = _utf16(name) + b"\x00\x00"
        entry = raw_name.ljust(64, b"\x00")
        entry += struct.pack("<HBB", len(raw_name), kind, 1)
        entry += struct.pack("<III", _FREE, right, kids[0] if kids else _FREE)
        entry += b"\x00" * 16 + b"\x00" * 4 + b"\x00" * 16
        entry += struct.pack("<IQ", starts[index], len(data))
        entries += entry
    directory = chain(entries.ljust(-(-len(entries) // SECTOR) * SECTOR, b"\x00"))

    per = SECTOR // 4
    fat_count = 1
    while len(fat) + fat_count > fat_count * per:
        fat_count += 1
    fat_first = len(sectors)
    fat.extend([_FAT] * fat_count)
    fat.extend([_FREE] * (fat_count * per - len(fat)))
    for index in range(fat_count):
        sectors.append(struct.pack(f"<{per}I", *fat[index * per : (index + 1) * per]))

    header = bytearray(SECTOR)
    header[:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<HH", header, 0x18, 0x3E, 3)
    struct.pack_into("<HHH", header, 0x1C, 0xFFFE, 9, 6)
    struct.pack_into("<I", header, 0x2C, fat_count)
    struct.pack_into("<I", header, 0x30, directory)
    # Próg mini-strumienia 0: każdy strumień w zwykłych sektorach.
    struct.pack_into("<IIIII", header, 0x38, 0, _END, 0, _END, 0)
    difat = [fat_first + i for i in range(fat_count)] + [_FREE] * (109 - fat_count)
    struct.pack_into("<109I", header, 0x4C, *difat)
    return bytes(header) + b"".join(sectors)
