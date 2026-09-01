#!/usr/bin/env python3
"""Read-only podgląd paragonów jednorazowych migracji naprawczych.

Po co osobne narzędzie: migracje naprawiające dane (0243, 0250, 0262 …) są
jednorazowe i zostawiają po sobie WYŁĄCZNIE wiersz w ``app_settings`` —
liczniki i identyfikatory tego, co faktycznie zmieniły. To jest jedyny dowód,
że naprawa w ogóle się wykonała i ile wierszy dotknęła. Bez tego skryptu
odczytanie go wymagało panelu Coolify albo SSH, a SSH na tym serwerze nie
działa.

**Wyłącznie SELECT** i wyłącznie klucze pasujące do wzorca paragonu migracji:
cztery cyfry, podkreślnik, reszta nazwy rewizji. To nie jest kosmetyka —
``app_settings`` trzyma też ustawienia kolumn użytkowników (``columns:<rola>``)
i manifest importu portfela klientów. Wzorzec sprawia, że kanał nie umie
przeczytać niczego poza paragonami, więc nie da się nim ominąć zasady
„log Actions nie dostaje danych osobowych ani ustawień kont".

Same paragony z założenia niosą liczniki i IDENTYFIKATORY (numery kontraktów,
zamówień, klientów) — tę samą klasę danych, którą już wypisuje
``scripts.list_clients``. Żadnych kwot, żadnych nazwisk.

Użycie::

    python -m scripts.show_migration_receipts
    python -m scripts.show_migration_receipts --key 0262_separate_md_periodic
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from sqlalchemy import select

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.app_setting import AppSetting  # noqa: E402

# Kształt klucza paragonu: numer rewizji + nazwa. Filtr stoi po stronie
# PYTHONA, nie SQL-a, i to jest świadome: zapytanie zwraca same klucze
# (bez wartości), więc nawet błąd we wzorcu nie może wypuścić cudzej wartości
# do logu — wartość dociągamy dopiero dla kluczy, które wzorzec przepuścił.
_RECEIPT_KEY_RE = re.compile(r"\A[0-9]{4}_[a-z0-9_]+\Z")


def is_receipt_key(key: str) -> bool:
    """Czy klucz jest paragonem migracji, a nie ustawieniem aplikacji."""

    return bool(_RECEIPT_KEY_RE.match(key or ""))


async def show(requested_key: str | None) -> int:
    async with AsyncSessionLocal() as db:
        keys = sorted(
            key
            for key in (await db.execute(select(AppSetting.key))).scalars()
            if is_receipt_key(key)
        )
        if requested_key is not None:
            if not is_receipt_key(requested_key):
                print(
                    "odmowa: --key musi mieć kształt paragonu migracji "
                    "(NNNN_nazwa_rewizji)"
                )
                return 2
            keys = [key for key in keys if key == requested_key]
            if not keys:
                # Rozróżnienie jest nośne: „migracja nie zostawiła paragonu"
                # znaczy, że naprawa się NIE wykonała, a nie że nie było czego
                # naprawiać. Cisza czytałaby się jak to drugie.
                print(f"=== brak paragonu dla klucza {requested_key} ===")
                print("migracja albo się nie wykonała, albo nie zapisuje paragonu")
                return 0

        print(f"=== paragony migracji: {len(keys)} ===")
        for key in keys:
            row = await db.get(AppSetting, key)
            if row is None:  # pragma: no cover - wyścig z równoległym zapisem
                continue
            print(f"--- {key} (updated_at={row.updated_at.isoformat()}) ---")
            print(json.dumps(row.value, ensure_ascii=False, indent=2, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--key",
        default=None,
        help="Pojedynczy paragon (np. 0262_separate_md_periodic); bez tego — wszystkie",
    )
    args = parser.parse_args()
    return asyncio.run(show(args.key))


if __name__ == "__main__":
    raise SystemExit(main())
