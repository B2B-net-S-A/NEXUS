"""Plik w pamięci idzie do przeglądarki jedną odpowiedzią, nie przez `BytesIO`.

`StreamingResponse(io.BytesIO(content))` iteruje bufor linia po linii, a w
binarnym PDF-ie „linia” ma średnio 78 bajtów: CV 398 KB wychodziło w 5 112
kawałkach, każdy przez wszystkie middleware'y, na jedynej pętli zdarzeń.
Na produkcji 27.10.2026 pobranie oryginału CV miało p50 2 s i p90 35 s.
"""

from __future__ import annotations

import io
import re
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
LINE_STREAMED = re.compile(r"StreamingResponse\(\s*(?:io\.)?BytesIO\(")


def test_no_route_streams_an_in_memory_file_line_by_line() -> None:
    offenders = []
    for path in sorted(APP_DIR.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for match in LINE_STREAMED.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(APP_DIR.parent)}:{line}")
    assert offenders == [], (
        "Plik jest już w pamięci — zwróć `Response(content, …)`: "
        + ", ".join(offenders)
    )


def test_bytesio_iterates_binary_in_many_small_chunks() -> None:
    # Dlaczego strażnik wyżej istnieje: tyle kawałków dostałby ASGI z jednego pliku.
    content = bytes(range(256)) * 400  # 100 KB, jedno „\n” na 256 bajtów
    assert sum(1 for _ in io.BytesIO(content)) > 400
