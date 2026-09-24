#!/usr/bin/env python3
"""Potwierdź, że instrukcja obsługi zamówień odpowiada dzisiejszemu kodowi.

Uruchom po zmianie czegokolwiek w logice zamówień:

    cd backend && python3 scripts/stamp_orders_procedure.py
    cd backend && python3 scripts/stamp_orders_procedure.py \\
        --only backend/app/services/order_types.py

Skrypt NIE sprawdza treści za Ciebie — nie da się automatycznie stwierdzić, czy
akapit „co robi system automatycznie" nadal jest prawdą. Robi dwie rzeczy,
które da się zrobić maszynowo:

  1. zapisuje odciski rozjechanych plików — każdy plik z ORDERS_LOGIC_SOURCES
     ma własny stempel w ``app/data/procedures/orders_stamps/``, więc PR
     ruszający inny plik zamówień nie zderzy się z Twoim w kolejce merge'ów;
  2. jeśli zmieniłeś treść instrukcji, przestawia widoczną w aplikacji datę
     przeglądu na dzisiejszą. Przegląd, po którym treść się nie zmieniła,
     daty nie rusza (patrz ``app/data/review_stamps.py`` — dlaczego).

Wolno uruchomić go BEZ zmiany treści — jeżeli przejrzałeś instrukcję i zmiana
w kodzie jej nie dotyczy, to jest poprawny wynik przeglądu, a nie obejście.
Szybkie sprawdzenie bez zapisu (też z hooka pre-commit):
``python3 backend/scripts/check_stamps.py``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.procedures import ORDERS_PROCEDURE  # noqa: E402
from app.data.review_stamps import stamp_orders  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--only",
        action="append",
        metavar="ŚCIEŻKA",
        help="przestempluj tylko ten plik (ścieżka od katalogu repo; można powtórzyć)",
    )
    args = parser.parse_args()

    try:
        changed, date_bumped = stamp_orders(only=args.only)
    except FileNotFoundError as exc:
        print("Nie znalazłem obserwowanych plików:", file=sys.stderr)
        for path in str(exc).splitlines():
            print(f"  · {path}", file=sys.stderr)
        print(
            "\nJeżeli plik został przeniesiony — popraw ORDERS_LOGIC_SOURCES\n"
            "w app/data/procedures/__init__.py i uruchom skrypt ponownie.",
            file=sys.stderr,
        )
        return 1
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    if not changed:
        print("Stemple instrukcji zamówień bez zmian.")
        return 0
    print("Przestemplowano po zmianie w:")
    for path in changed:
        print(f"  · {path}")
    if date_bumped:
        print("Treść instrukcji się zmieniła — data przeglądu w treści: dzisiejsza.")
    print("\nZacommituj zmienione pliki z app/data/procedures/orders_stamps/")
    print(f"(i app/data/procedures/{ORDERS_PROCEDURE.filename}, jeśli ją edytowałeś).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
