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

Runda 7 (R7-X2-1): „z założenia” nie wystarczyło — paragon ``0304_…`` niósł
migawkę raportu z nazwiskami i stawkami 557 konsultantów i poszedł do
publicznego logu Actions. Dlatego wydruk przechodzi przez ``redact``, który
wypuszcza WYŁĄCZNIE liczby, wartości logiczne, daty i listy takich wartości,
niezależnie od tego, co leży w bazie. Napis zostaje zastąpiony samą długością,
a liczba pod kluczem kwoty (stawka, marża, przychód…) — znacznikiem.

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
from typing import Any

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


# Napisy, które wolno wypisać: daty i znaczniki czasu ISO. Wszystko inne
# (nazwisko, tytuł zamówienia, powód z treścią) wychodzi jako długość.
_SAFE_STRING_RE = re.compile(
    r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}"
    r"(?:[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]+)?)?(?:Z|[+-][0-9]{2}:?[0-9]{2})?)?\Z"
)
# Klucz słownika wypisujemy tylko, gdy wygląda jak nazwa pola, nie jak dana
# (klucz „Jan Kowalski” w mapie nazwisko → liczba).
_SAFE_DICT_KEY_RE = re.compile(r"\A[A-Za-z0-9_.:\-]{1,80}\Z")
# Liczba pod takim kluczem to kwota — paragon ma nieść ID i liczniki, nie stawki.
# Porównanie po CZŁONACH nazwy (``md_rate_revenue`` → md/rate/revenue), nie
# po podłańcuchu: „rate” siedzi też w „generated”, „migrated”, „separated”.
_MONEY_KEY_TOKENS = frozenset(
    {
        "rate",
        "rates",
        "cost",
        "costs",
        "revenue",
        "margin",
        "amount",
        "amounts",
        "price",
        "salary",
        "budget",
        "value",
        "values",
        "kwota",
        "kwoty",
        "stawka",
        "stawki",
        "pln",
        "mrr",
    }
)
_MAX_LISTED_OBJECTS = 100


def _is_money_key(key: str) -> bool:
    tokens = re.split(r"[_.:\-]+", re.sub(r"([a-z])([A-Z])", r"\1_\2", key).lower())
    return any(token in _MONEY_KEY_TOKENS for token in tokens)


def redact(value: Any, *, money: bool = False) -> Any:
    """Kopia paragonu nadająca się do publicznego logu.

    Biała lista typów, nie czarna lista pól: nowy paragon z nowym polem
    tekstowym nie może niczego wypuścić tylko dlatego, że nikt nie dopisał
    tu jego nazwy.
    """

    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return "<kwota>" if money else value
    if isinstance(value, str):
        if _SAFE_STRING_RE.match(value):
            return value
        return f"<napis, {len(value)} zn.>"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            key_text = str(key)
            if _SAFE_DICT_KEY_RE.match(key_text):
                out[key_text] = redact(item, money=money or _is_money_key(key_text))
            else:
                out[f"<klucz {index + 1}>"] = redact(item, money=money)
        return out
    if isinstance(value, (list, tuple)):
        items = [redact(item, money=money) for item in value]
        objects = sum(1 for item in value if isinstance(item, (dict, list, tuple)))
        if objects > _MAX_LISTED_OBJECTS:
            return items[:_MAX_LISTED_OBJECTS] + [
                f"<pominięto {len(items) - _MAX_LISTED_OBJECTS} pozycji>"
            ]
        return items
    return f"<{type(value).__name__}>"


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
            print(json.dumps(redact(row.value), ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--key",
        default=None,
        help="Pojedynczy paragon (np. 0262_separate_md_periodic); bez tego — wszystkie",
    )
    args = parser.parse_args()
    try:
        return asyncio.run(show(args.key))
    except Exception as exc:  # noqa: BLE001 - wyjście trafia do publicznego logu
        # Traceback potrafi zacytować wiersz z bazy; w logu tylko klasa błędu.
        print(f"blad odczytu paragonow: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
