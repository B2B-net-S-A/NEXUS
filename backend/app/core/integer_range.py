"""Liczba z żądania, która nie mieści się w kolumnie bazy.

Python przyjmuje dowolnie duży ``int``, a identyfikatory to int4. asyncpg
odmawia zakodowania takiego parametru: ``OverflowError("value out of int32
range")`` → ``asyncpg.DataError`` → ``sqlalchemy.exc.DBAPIError``. Zapytanie
nie dochodzi do bazy, więc niczego nie zmienia — to błąd żądania, nie serwera.

Rozpoznajemy wyłącznie ten jeden wyjątek kodera (int2/int4/int8). Przepełnienie
zgłoszone przez Postgresa (22003: sekwencja, arytmetyka, NUMERIC) zostaje
błędem serwera — tam przyczyną bywają dane wewnętrzne.
"""

import re

OUT_OF_RANGE = "Liczba w żądaniu jest poza dopuszczalnym zakresem."

_ENCODER_OVERFLOW = re.compile(r"^value out of int(16|32|64) range$")


def is_integer_out_of_range(exc: BaseException) -> bool:
    """Czy przyczyną wyjątku jest liczba, której asyncpg nie zakodował.

    Idzie po przyczynach (``orig`` SQLAlchemy i ``__cause__``); ``__context__``
    pomija, bo to błąd obsłużony wcześniej, a nie powód tego.
    """
    seen: set[int] = set()
    node: BaseException | None = exc
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        if isinstance(node, OverflowError) and _ENCODER_OVERFLOW.match(str(node)):
            return True
        node = getattr(node, "orig", None) or node.__cause__
    return False
