"""Ślady klienta, których NIE widać w kluczach obcych.

Skan ``pg_catalog`` w ``inactive_client_cleanup`` łapie wszystko, co wskazuje
na ``clients.id``. Ten moduł łapie resztę — przegląd adwersarialny znalazł
ją w trzech miejscach i każde z nich pozwalało usunąć klienta z historią:

* **powiązania po NAZWIE**: DynaReporter ma własną tabelę klientów
  (``dr_clients``; MRR i placementy wiszą na niej, nie na ``clients``),
  wyniki miesięczne Finansów i rozbicie placementów Rady trzymają nazwę jako
  wolny tekst, a umowa B2B wygenerowana bez rekrutacji zapisuje wyłącznie
  ``client_name`` (``client_id`` zostaje pusty);
* **zasiewy przy starcie**: ``entrypoint.sh`` zakłada ponownie „Ministerstwo
  Sprawiedliwości", jeśli go nie ma, a karta klienta zasiewa się, gdy wzorzec
  nazwy trafia w DOKŁADNIE jednego klienta — usunięcie duplikatu zmienia ten
  licznik i przy następnym deployu zakłada kartę komuś innemu;
* **stałe w kodzie**: klienci ze specjalną obsługą zamówień (Polkomtel,
  e-Zdrowie, Wedel, Cyfrowy Polsat, kanoniczne ID polityk PDF).

Dopasowanie po nazwie jest celowo LUŹNE (bez form prawnych). Fałszywe
trafienie może tylko ZATRZYMAĆ klienta — nigdy go nie usuwa — więc przy
trwałym kasowaniu to jest właściwy kierunek błędu.
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.client_portfolio_import import (
    loose_client_name,
    normalize_client_name,
)

NameTarget = Literal[
    "cooperation_stats",
    "contracts",
    "related",
]


@dataclass(frozen=True)
class NameReference:
    table: str
    column: str
    target: NameTarget
    label: str
    # Stały predykat SQL (bez parametrów) — np. B2B liczymy po nazwie tylko
    # tam, gdzie brak ``client_id``, bo resztę już policzył skan FK.
    where: Optional[str] = None


NAME_REFERENCES: tuple[NameReference, ...] = (
    NameReference(
        "dr_clients",
        "name",
        "cooperation_stats",
        "Klient w DynaReporterze (MRR, placementy)",
    ),
    NameReference(
        "dr_board_placement_clients",
        "client_name",
        "cooperation_stats",
        "Placementy w raporcie Rady",
    ),
    NameReference(
        "finance_monthly_results",
        "client_name",
        "cooperation_stats",
        "Wyniki miesięczne (Finanse)",
    ),
    NameReference(
        "b2b_generated_contracts",
        "client_name",
        "contracts",
        "Umowy B2B wygenerowane bez rekrutacji",
        where="client_id IS NULL",
    ),
    NameReference(
        "dr_sales_leads",
        "company_name",
        "related",
        "Leady sprzedażowe (DynaReporter)",
    ),
    NameReference(
        "dr_sales_offers",
        "company_name",
        "related",
        "Oferty sprzedażowe (DynaReporter)",
    ),
)

# Klienci zakładani ponownie przy KAŻDYM starcie, jeśli ich brak
# (``entrypoint.sh``, blok 0153 — wyróżnienie w generatorze umów B2B).
BOOT_SEEDED_CLIENT_NAMES: tuple[str, ...] = ("Ministerstwo Sprawiedliwości",)

_PLAYBOOK_SEED = Path(__file__).resolve().parents[1] / (
    "data/client_playbooks/seed.json"
)


# Formy prawne, których ``loose_client_name`` (klucz SUGESTII importu portfela)
# nie zdejmuje — „Sp. z o.o." zostawiało tam „o o" i gubiło dopasowanie.
# Szerszy klucz daje tylko więcej trafień, a trafienie może klienta wyłącznie
# zatrzymać, więc przy trwałym kasowaniu to jest bezpieczny kierunek.
_EXTRA_LEGAL_TOKENS = frozenset(
    {
        "o",
        "oo",
        "sa",
        "spzoo",
        "k",
        "komandytowa",
        "jawna",
        "j",
        "ltd",
        "gmbh",
        "inc",
        "plc",
        "ag",
        "bv",
        "nv",
        "llc",
        "abp",
    }
)


def name_key(value: Optional[str]) -> str:
    """Klucz dopasowania: bez form prawnych, a gdy nic nie zostaje — pełny."""

    loose = " ".join(
        token
        for token in loose_client_name(value).split()
        if token not in _EXTRA_LEGAL_TOKENS
    )
    return loose or normalize_client_name(value)


def _like_to_regex(pattern: str) -> re.Pattern[str]:
    parts = []
    for char in pattern:
        if char == "%":
            parts.append(".*")
        elif char == "_":
            parts.append(".")
        else:
            parts.append(re.escape(char))
    return re.compile("^" + "".join(parts) + "$", re.DOTALL)


@lru_cache(maxsize=1)
def playbook_seed_patterns() -> tuple[str, ...]:
    """Wzorce ``LIKE`` zasiewu karty klienta (to samo źródło co entrypoint)."""

    try:
        entries = json.loads(_PLAYBOOK_SEED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    return tuple(
        str(entry["name_pattern"])
        for entry in entries
        if isinstance(entry, dict) and entry.get("name_pattern")
    )


def matching_playbook_patterns(
    name: Optional[str], patterns: tuple[str, ...]
) -> list[str]:
    """Lustro ``lower(c.name) LIKE $1`` z ``_PLAYBOOK_SEED_SQL``."""

    if not name:
        return []
    lowered = name.lower()
    return [p for p in patterns if _like_to_regex(p).match(lowered)]


def is_boot_seeded(*names: Optional[str]) -> bool:
    seeded = {normalize_client_name(value) for value in BOOT_SEEDED_CLIENT_NAMES}
    return any(normalize_client_name(value) in seeded for value in names if value)


def code_configured_client_ids() -> dict[int, list[str]]:
    """ID klientów zaszyte w kodzie (specjalna obsługa zamówień/odczytu PDF)."""

    from app.services.cyfrowy_polsat_orders import CYFROWY_POLSAT_CLIENT_ID
    from app.services.ezdrowie import EZDROWIE_CLIENT_ID
    from app.services.finance_order_matching import POLKOMTEL_CLIENT_ID
    from app.services.lotte_wedel_orders import LOTTE_WEDEL_CLIENT_ID
    from app.services.nexus_data_correction import _CANONICAL_CLIENTS
    from app.services.order_policies.registry import POLICIES

    found: dict[int, list[str]] = {}

    def add(client_id: int, label: str) -> None:
        found.setdefault(int(client_id), [])
        if label not in found[int(client_id)]:
            found[int(client_id)].append(label)

    add(EZDROWIE_CLIENT_ID, "obsługa e-Zdrowia")
    add(POLKOMTEL_CLIENT_ID, "dopasowanie zamówień Finansów (Polkomtel)")
    add(LOTTE_WEDEL_CLIENT_ID, "zamówienia Lotte Wedel")
    add(CYFROWY_POLSAT_CLIENT_ID, "zamówienia Cyfrowego Polsatu")
    for client_id, name in _CANONICAL_CLIENTS:
        add(client_id, f"korekta danych ({name})")
    for policy in POLICIES:
        for client_id in policy.canonical_client_ids:
            add(client_id, f"polityka odczytu PDF „{policy.display_name}”")
    return found


def model_client_foreign_keys() -> list[tuple[str, str, str]]:
    """``(tabela, kolumna, kod ON DELETE)`` dla FK do klienta z modeli ORM.

    Uzupełnienie katalogu: jeśli na produkcji brakuje więzu, który model
    deklaruje, skan ``pg_catalog`` by go nie zobaczył, a dane i tak by
    osierociały. Kod jak w ``pg_constraint.confdeltype``.
    """

    import app.models  # noqa: F401  (rejestracja wszystkich tabel)
    from app.core.database import Base

    codes = {
        "CASCADE": "c",
        "SET NULL": "n",
        "SET DEFAULT": "d",
        "RESTRICT": "r",
        "NO ACTION": "a",
    }
    refs: set[tuple[str, str, str]] = set()
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            # ``target_fullname`` nie rozwiązuje celu — ``fk.column`` rzuciłby
            # na FK do tabeli spoza metadanych.
            if fk.target_fullname == "clients.id":
                code = codes.get((fk.ondelete or "NO ACTION").upper(), "a")
                refs.add((table.name, fk.parent.name, code))
    return sorted(refs)


async def column_exists(db: AsyncSession, table: str, column: str) -> bool:
    return bool(
        await db.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name = :table AND column_name = :column)"
            ),
            {"table": table, "column": column},
        )
    )


async def name_reference_counts(
    db: AsyncSession, ref: NameReference, quote
) -> dict[str, int]:
    """Liczba wierszy per klucz nazwy. Brak tabeli/kolumny = brak śladów."""

    if not await column_exists(db, ref.table, ref.column):
        return {}
    column = quote(ref.column)
    where = f"WHERE {ref.where}" if ref.where else ""
    statement = text(
        f"SELECT {column} AS name, count(*) AS n FROM {quote(ref.table)} "  # noqa: S608
        f"{where} GROUP BY {column}"
    )
    counts: dict[str, int] = {}
    for row in (await db.execute(statement)).all():
        key = name_key(row.name)
        if key:
            counts[key] = counts.get(key, 0) + int(row.n)
    return counts


def configured_client_ids(
    environ: Optional[dict[str, str]] = None,
) -> dict[int, list[str]]:
    """Klienci wskazani z nazwy w zmiennych ``*_CLIENT_IDS`` (bramki per klient).

    Usunięcie takiego klienta nic by nie zepsuło w bazie, ale zostawiłoby
    w Coolify wpis wskazujący na nieistniejący rekord — i zdradza, że ktoś
    świadomie skonfigurował dla niego zachowanie. To decyzja dla człowieka.
    """

    source = os.environ if environ is None else environ
    found: dict[int, list[str]] = defaultdict(list)
    for key, raw in source.items():
        if not key.endswith("_CLIENT_IDS") or not raw:
            continue
        for token in re.split(r"[,;\s]+", raw):
            token = token.strip()
            if token.isdigit():
                found[int(token)].append(key)
    return {client_id: sorted(keys) for client_id, keys in found.items()}


def configuration_reasons(
    client_id: int,
    names: tuple[Optional[str], Optional[str]],
    *,
    env_ids: dict[int, list[str]],
    code_ids: dict[int, list[str]],
    patterns: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Wstrzymania z konfiguracji. ``names`` = (wyświetlana, źródłowa ``name``)."""

    reasons: list[dict[str, Any]] = []
    keys = env_ids.get(client_id)
    if keys:
        reasons.append(
            {
                "code": "configuration",
                "label": "Klient wskazany w konfiguracji: " + ", ".join(keys),
                "count": len(keys),
                "effect": "konfiguracja wskazywałaby nieistniejącego klienta",
            }
        )
    labels = code_ids.get(client_id)
    if labels:
        reasons.append(
            {
                "code": "code_constant",
                "label": "Klient zaszyty w kodzie: " + ", ".join(labels),
                "count": len(labels),
                "effect": "specjalna obsługa przestałaby działać",
            }
        )
    if is_boot_seeded(*names):
        reasons.append(
            {
                "code": "boot_seed",
                "label": "Klient zakładany automatycznie przy starcie aplikacji",
                "count": 1,
                "effect": "wróciłby przy najbliższym deployu z nowym id",
            }
        )
    matched = matching_playbook_patterns(names[1], patterns)
    if matched:
        reasons.append(
            {
                "code": "playbook_seed",
                "label": "Nazwa pasuje do zasiewu karty klienta: " + ", ".join(matched),
                "count": len(matched),
                "effect": (
                    "usunięcie zmieniłoby liczbę pasujących klientów i następny "
                    "start założyłby kartę innemu klientowi"
                ),
            }
        )
    return reasons
