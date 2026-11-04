"""Numer KSeF: ``NIP-RRRRMMDD-XXXXXXXXXXXX-CC`` (35 znaków).

NIP sprzedawcy, data przyjęcia faktury, 12 znaków szesnastkowych części
technicznej i suma kontrolna CRC-8 (wielomian ``0x07``, wartość początkowa
``0x00``) z pierwszych 32 znaków — dokumentacja MF „Numer KSeF – struktura
i walidacja”. KSeF 2.0 nadaje wyłącznie numery 35-znakowe.
"""

from __future__ import annotations

import re
from datetime import date

KSEF_NUMBER_RE = re.compile(
    r"^(\d{10})-(\d{4})(\d{2})(\d{2})-([0-9A-F]{12})-([0-9A-F]{2})$"
)


def crc8(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def checksum(data_part: str) -> str:
    """Dwa znaki sumy kontrolnej dla 32 znaków części danych."""

    return f"{crc8(data_part.encode('ascii')):02X}"


def is_valid(number: object) -> bool:
    if not isinstance(number, str) or len(number) != 35:
        return False
    match = KSEF_NUMBER_RE.match(number)
    if match is None:
        return False
    try:
        date(int(match.group(2)), int(match.group(3)), int(match.group(4)))
    except ValueError:
        return False
    return checksum(number[:32]) == match.group(6)


def seller_nip(number: str) -> str:
    return number[:10]


def make(nip: str, day: date, technical: str) -> str:
    """Składa numer z sumą kontrolną (fikcyjne numery w testach i symulacji)."""

    data = f"{nip}-{day:%Y%m%d}-{technical.upper()}"
    return f"{data}-{checksum(data)}"
