"""SEC-03 (audyt 22.09 r2): żaden endpoint nie czyta uploadu w całości do RAM."""

from __future__ import annotations

import re
from pathlib import Path

API = Path(__file__).resolve().parents[1] / "app" / "api"
# `(?<!`)` — pomija cytat w docstringu, który opisuje stary błąd.
UNBOUNDED = re.compile(r"(?<!`)await\s+(file|cv|upload|[a-z_]*_file)\.read\(\s*\)")


def test_upload_reads_have_an_explicit_ceiling():
    offenders = [
        f"{path.name}:{number}"
        for path in sorted(API.glob("*.py"))
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if UNBOUNDED.search(line)
    ]
    assert offenders == [], (
        "Czytaj upload przez read(LIMIT + 1) i sprawdź długość (wzorzec "
        f"_read_upload_bounded w api/candidates.py): {offenders}"
    )
