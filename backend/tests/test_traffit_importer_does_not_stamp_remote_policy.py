"""Importer Traffita nie stempluje już `remote_policy` na 'hybrid' (0278).

Do tej migracji `_UPSERT_JOB` wstawiał `CAST('hybrid' AS remotepolicy)` przy
KAŻDYM insercie nowej oferty, więc „nikt nie ustawił trybu" było
nieodróżnialne od „oferta chce biura" — a to właśnie ta różnica napędza
dealbreaker `remote_only_refuses_office`. Kolumna jest NEXUS_OWNED
(`job_column_ownership.NEXUS_OWNED`), więc `ON CONFLICT ... DO UPDATE SET`
i tak nigdy jej nie nadpisywał — ryzyko siedziało wyłącznie w INSERT-cie.

Test czyta `_UPSERT_JOB` przez AST (bez wykonania) — grep po surowym
tekście źródła złapałby też komentarz wyjaśniający DLACZEGO kolumny już nie
ma, i fałszywie zaliczał plik, w którym ktoś przywrócił stempel obok tego
komentarza.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_IMPORTER_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "traffit"
    / "importer.py"
)


def _upsert_job_sql() -> str:
    tree = ast.parse(_IMPORTER_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "_UPSERT_JOB"
        ):
            continue
        call = node.value
        assert isinstance(call, ast.Call) and call.args, (
            "_UPSERT_JOB nie jest wywołaniem `text(...)` z argumentem"
        )
        return ast.literal_eval(call.args[0])
    raise AssertionError("importer.py: brak przypisania _UPSERT_JOB")


def test_upsert_job_never_writes_remote_policy():
    sql = _upsert_job_sql()
    assert "remote_policy" not in sql, (
        "_UPSERT_JOB wciąż wspomina remote_policy — importer nie powinien już "
        "stemplować trybu pracy na INSERT (0278, decyzja Artura 07.09.2026)"
    )
    # Typ enuma bazy (`remotepolicy`, bez podkreślnika) pojawiał się wcześniej
    # WYŁĄCZNIE w `CAST('hybrid' AS remotepolicy)` — jego obecność gdziekolwiek
    # w tym SQL-u znaczyłaby regres stempla, nawet gdyby nazwa kolumny obok
    # została inaczej sformatowana.
    assert "remotepolicy" not in sql.lower(), (
        "_UPSERT_JOB nadal rzutuje na typ remotepolicy — sprawdź, czy to nie "
        "regres stempla 'hybrid'"
    )


def test_upsert_job_column_and_value_counts_still_match():
    """Usunięcie kolumny z listy MUSI zdjąć dokładnie jedną wartość z VALUES.

    Regresja, którą ten test łapie: ktoś kasuje `remote_policy,` z listy
    kolumn, ale zostawia `CAST('hybrid' AS remotepolicy),` w VALUES (albo
    odwrotnie) — INSERT z niezgodną liczbą kolumn/wartości pada dopiero w
    runtime, na produkcji, przy pierwszym imporcie.
    """
    sql = _upsert_job_sql()
    columns_block = re.search(r"INSERT INTO jobs \(([^)]*)\)", sql, re.DOTALL)
    values_block = re.search(r"\)\s*VALUES\s*\(([^;]*?)\)\s*ON CONFLICT", sql, re.DOTALL)
    assert columns_block and values_block, "nie udało się wyodrębnić kolumn/VALUES"

    column_count = len([c for c in columns_block.group(1).split(",") if c.strip()])
    # VALUES ma wyrażenia z przecinkami wewnątrz CAST(...) — liczymy nawiasy,
    # nie dzielimy naiwnie po przecinku.
    depth = 0
    value_count = 1
    for ch in values_block.group(1):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            value_count += 1

    assert column_count == value_count, (
        f"_UPSERT_JOB: {column_count} kolumn vs {value_count} wartości w VALUES"
    )
