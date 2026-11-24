"""Cięcie puli do 150 w `_write_pool` (PR #3941, audyt R3 24.11.2026).

SQL cięcia jest stałym literałem (bez f-stringa), bo Semgrep (`semgrep-pr`)
blokuje `text()` z SQL składanym w kodzie. Klucze dodatków ponad pulą
(`POOL_EXTRA_EVIDENCE_KEYS`) są więc wpisane ręcznie — ten test pilnuje, żeby
nowy klucz w krotce nie został pominięty w cięciu i nie wycinał dodatków.
Bez bazy.
"""

from __future__ import annotations

from app.services import auto_match_service as ams
from app.services.auto_full_review import POOL_EXTRA_EVIDENCE_KEYS


def test_pool_trim_sql_skips_every_pool_extra_key():
    sql = ams._POOL_TRIM_SQL.text
    for key in POOL_EXTRA_EVIDENCE_KEYS:
        assert f"(evidence->>'{key}') IS DISTINCT FROM 'true'" in sql, key


def test_pool_trim_sql_skips_only_pool_extra_keys():
    sql = ams._POOL_TRIM_SQL.text
    assert sql.count("IS DISTINCT FROM 'true'") == len(POOL_EXTRA_EVIDENCE_KEYS)


def test_pool_trim_sql_binds_jobs_and_size():
    assert set(ams._POOL_TRIM_SQL.compile().params) == {"jobs", "size"}
