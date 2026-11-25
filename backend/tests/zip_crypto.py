"""ZIP z hasłem (tradycyjne szyfrowanie PKWARE, „ZipCrypto”) do testów.

``zipfile`` takie pliki czyta, ale nie zapisuje. Raport Credit Agricole przychodzi
w takim ZIP-ie, więc testy budują go same: metoda „stored” albo „deflate”, nagłówek
12 bajtów z ostatnim bajtem równym górnemu bajtowi CRC (tak sprawdza go ``zipfile``).
"""

from __future__ import annotations

import os
import struct
import zlib


def _crc_table() -> list[int]:
    table = []
    for n in range(256):
        c = n
        for _ in range(8):
            c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
        table.append(c)
    return table


_TABLE = _crc_table()


class _Keys:
    def __init__(self, password: bytes) -> None:
        self.k = [0x12345678, 0x23456789, 0x34567890]
        for byte in password:
            self.update(byte)

    def _crc(self, crc: int, byte: int) -> int:
        return (crc >> 8) ^ _TABLE[(crc ^ byte) & 0xFF]

    def update(self, byte: int) -> None:
        k0, k1, k2 = self.k
        k0 = self._crc(k0, byte)
        k1 = (k1 + (k0 & 0xFF)) & 0xFFFFFFFF
        k1 = (k1 * 134775813 + 1) & 0xFFFFFFFF
        k2 = self._crc(k2, (k1 >> 24) & 0xFF)
        self.k = [k0, k1, k2]

    def encrypt(self, data: bytes) -> bytes:
        out = bytearray()
        for byte in data:
            temp = (self.k[2] | 2) & 0xFFFF
            out.append(byte ^ (((temp * (temp ^ 1)) >> 8) & 0xFF))
            self.update(byte)
        return bytes(out)


def encrypted_zip(
    files: dict[str, bytes], password: bytes, *, deflate: bool = False
) -> bytes:
    """Archiwum, w którym każdy plik jest zaszyfrowany ``password``."""

    method = 8 if deflate else 0

    local = bytearray()
    central = bytearray()
    for name, data in files.items():
        raw_name = name.encode()
        crc = zlib.crc32(data) & 0xFFFFFFFF
        keys = _Keys(password)
        header = os.urandom(11) + bytes([crc >> 24])
        payload = data
        if deflate:
            packer = zlib.compressobj(9, zlib.DEFLATED, -15)
            payload = packer.compress(data) + packer.flush()
        body = keys.encrypt(header) + keys.encrypt(payload)
        offset = len(local)
        local += struct.pack(
            "<IHHHHHIIIHH",
            0x04034B50,
            20,
            1,
            method,
            0,
            0x21,
            crc,
            len(body),
            len(data),
            len(raw_name),
            0,
        )
        local += raw_name + body
        central += struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50,
            20,
            20,
            1,
            method,
            0,
            0x21,
            crc,
            len(body),
            len(data),
            len(raw_name),
            0,
            0,
            0,
            0,
            0,
            offset,
        )
        central += raw_name
    end = struct.pack(
        "<IHHHHIIH",
        0x06054B50,
        0,
        0,
        len(files),
        len(files),
        len(central),
        len(local),
        0,
    )
    return bytes(local + central + end)
