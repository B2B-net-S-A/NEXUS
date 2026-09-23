#!/usr/bin/env python3
"""Potwierdź, że przewodniki ekranów Jarvisa odpowiadają dzisiejszym ekranom.

Uruchom po zmianie przewodnika albo pliku z jego listy ``sources``:

    cd backend && python scripts/stamp_screen_guides.py

Skrypt nie sprawdza treści — zapisuje odciski, żeby test przestał przypominać.
Uruchomienie bez zmiany treści jest poprawnym wynikiem przeglądu, jeśli
zmiana w kodzie przewodnika nie dotyczy.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.screen_guides import current_digests, load_guides, write_stamp  # noqa: E402


def main() -> None:
    load_guides.cache_clear()
    digests = current_digests()
    missing = [
        f"{key}: {rel}"
        for key, guide in load_guides().items()
        for rel in guide.sources
        if not (Path(__file__).resolve().parents[2] / rel).is_file()
    ]
    if missing:
        raise SystemExit(
            "Nie ma plików źródłowych przewodników:\n  " + "\n  ".join(missing)
        )
    write_stamp(date.today(), digests)
    print(f"Przestemplowano {len(digests)} przewodników.")


if __name__ == "__main__":
    main()
