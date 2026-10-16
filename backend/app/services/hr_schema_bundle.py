"""„Ludzie w NEXUSIE” — jeden punkt, z którego ``entrypoint.sh`` bierze SQL modułu.

Każdy moduł HR ma własny ``*_schema.py`` (to samo źródło czyta jego migracja).
Entrypoint importuje tylko ten agregator i wpina listy w swoje fazy:

* ``COLUMN_DDL`` — tabele, kolumny, indeksy nowych tabel i CHECK-i ról
  (koniec ``_COLUMN_STATEMENTS``: tabele bazowe już istnieją),
* ``DATA_DDL`` — zasiewy i znaczniki jednorazowe (koniec ``_DATA_STATEMENTS``),
* ``CONSTRAINT_DDL`` — ograniczenia dokładane do istniejących tabel.

Nowe wartości typów enum (``userrole``, ``notificationtype``) stoją literalnie
w ``_ENUM_STATEMENTS`` — ta lista jest zdefiniowana przed importami.
"""

from __future__ import annotations

from app.services import hr_access_schema as access
from app.services import hr_foundation_schema as foundation

COLUMN_DDL: tuple[str, ...] = (
    *foundation.TABLE_DDL,
    *foundation.INDEX_DDL,
    *access.ROLE_CHECK_DDL,
)

DATA_DDL: tuple[str, ...] = (
    *foundation.DATA_DDL,
    *access.SEED_DDL,
)

CONSTRAINT_DDL: tuple[str, ...] = ()

#: Wartości enumów, które musi znać ``_ENUM_STATEMENTS`` (test lustra).
ENUM_DDL: tuple[str, ...] = (access.ENUM_DDL,)
