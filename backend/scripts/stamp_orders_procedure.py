#!/usr/bin/env python3
"""Potwierdź, że instrukcja obsługi zamówień odpowiada dzisiejszemu kodowi.

Uruchom po zmianie czegokolwiek w logice zamówień:

    cd backend && python scripts/stamp_orders_procedure.py

Skrypt NIE sprawdza treści za Ciebie — nie da się automatycznie stwierdzić, czy
akapit „co robi system automatycznie" nadal jest prawdą. Robi dwie rzeczy,
które da się zrobić maszynowo:

  1. zapisuje odciski obserwowanych plików, żeby test przestał przypominać,
  2. przestawia widoczną w aplikacji datę przeglądu, żeby Delivery Lead wiedział,
     jak świeża jest instrukcja, którą właśnie czyta.

Wolno uruchomić go BEZ zmiany treści — jeżeli przejrzałeś instrukcję i zmiana
w kodzie jej nie dotyczy, to jest poprawny wynik przeglądu, a nie obejście.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.procedures import (  # noqa: E402
    ORDERS_PROCEDURE,
    current_digests,
    load_stamp,
    write_stamp,
)

# Linia widoczna w treści procedury — jedyne miejsce, w którym czytelnik widzi,
# kiedy instrukcję ostatnio skonfrontowano z systemem.
_REVIEWED_LINE = re.compile(
    r"^> \*\*Zgodność z systemem sprawdzona:\*\* \d{4}-\d{2}-\d{2}$", re.MULTILINE
)


def _restamp_markdown(today: date) -> bool:
    """Przestaw datę przeglądu w treści. Zwraca ``True``, jeśli coś zmieniono."""
    path = ORDERS_PROCEDURE.path
    content = path.read_text(encoding="utf-8")
    replacement = f"> **Zgodność z systemem sprawdzona:** {today.isoformat()}"
    updated, count = _REVIEWED_LINE.subn(replacement, content)
    if count == 0:
        raise SystemExit(
            f"Nie znalazłem linii z datą przeglądu w {path.name}.\n"
            "Instrukcja musi zawierać dokładnie jedną linię w formacie:\n"
            "  > **Zgodność z systemem sprawdzona:** RRRR-MM-DD"
        )
    if updated == content:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    today = date.today()
    digests = current_digests()

    missing = sorted(k for k, v in digests.items() if v == "missing")
    if missing:
        print("Nie znalazłem obserwowanych plików:", file=sys.stderr)
        for path in missing:
            print(f"  · {path}", file=sys.stderr)
        print(
            "\nJeżeli plik został przeniesiony — popraw ORDERS_LOGIC_SOURCES\n"
            "w app/data/procedures/__init__.py i uruchom skrypt ponownie.",
            file=sys.stderr,
        )
        return 1

    try:
        previous = load_stamp().get("sources", {})
    except FileNotFoundError:
        previous = {}

    changed = sorted(k for k, v in digests.items() if previous.get(k) != v)
    # Kolejność jest load-bearing: `_restamp_markdown` WALIDUJE treść i potrafi
    # przerwać skrypt (brak linii z datą). Gdyby stempel szedł pierwszy,
    # zostawałby z dzisiejszą datą przy nieruszonej treści — a test złapałby to
    # jako „data w dokumencie różni się od stempla", czyli komunikat opisujący
    # skutek zamiast przyczyny.
    md_changed = _restamp_markdown(today)
    write_stamp(today, digests)

    if changed:
        print("Przestemplowano po zmianie w:")
        for path in changed:
            print(f"  · {path}")
    else:
        print("Odciski plików bez zmian.")
    print(
        f"Data przeglądu: {today.isoformat()}"
        + ("" if md_changed else " (bez zmiany w treści instrukcji)")
    )
    print("\nPamiętaj o zacommitowaniu obu plików:")
    print("  · app/data/procedures/orders_procedure_stamp.json")
    print(f"  · app/data/procedures/{ORDERS_PROCEDURE.filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
