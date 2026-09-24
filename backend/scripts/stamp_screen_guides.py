#!/usr/bin/env python3
"""Potwierdź, że przewodniki ekranów Jarvisa odpowiadają dzisiejszym ekranom.

Uruchom po zmianie przewodnika albo pliku z jego listy ``sources``:

    cd backend && python3 scripts/stamp_screen_guides.py
    cd backend && python3 scripts/stamp_screen_guides.py --only jobs.list

Skrypt nie sprawdza treści — zapisuje odciski, żeby test przestał przypominać.
Uruchomienie bez zmiany treści jest poprawnym wynikiem przeglądu, jeśli
zmiana w kodzie przewodnika nie dotyczy.

Każdy ekran ma własny plik stempla (``app/data/screen_guides/stamps/``) i skrypt
przepisuje tylko te, które się rozjechały — PR ruszający inny ekran nie zderzy
się z Twoim w kolejce merge'ów. Szybkie sprawdzenie bez zapisu (też z hooka
pre-commit): ``python3 backend/scripts/check_stamps.py``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.review_stamps import (  # noqa: E402
    REPO_ROOT,
    guide_drift,
    load_raw_guides,
    stamp_guides,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--only",
        action="append",
        metavar="KLUCZ",
        help="przestempluj tylko ten ekran (można powtórzyć), np. jobs.list",
    )
    args = parser.parse_args()

    missing = [
        f"{key}: {rel}"
        for key, entry in load_raw_guides().items()
        for rel in entry.get("sources", [])
        if not (REPO_ROOT / rel).is_file()
    ]
    if missing:
        print(
            "Nie ma plików źródłowych przewodników:\n  " + "\n  ".join(missing),
            file=sys.stderr,
        )
        return 1

    drift = guide_drift()
    try:
        changed = stamp_guides(only=args.only)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    if not changed:
        print("Stemple przewodników bez zmian.")
        return 0
    print("Przestemplowano:")
    for key in changed:
        reasons = ", ".join(drift.get(key, ["usunięty przewodnik"]))
        print(f"  · {key} ({reasons})")
    print("\nZacommituj przewodnik razem z plikami z app/data/screen_guides/stamps/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
