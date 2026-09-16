"""Docelowa struktura umów Centrum e-Zdrowia — jedno źródło SQL-a zasiewu.

Ticket „Struktura umów wykonawczych" (09.2026) podaje wprost, które umowy
wykonawcze wiszą pod którą częścią umowy ramowej. Numery „DO UMOWY RAMOWEJ"
na dokumentach są błędne (zamienione), więc struktura NIE jest parsowana
z treści dokumentów — pochodzi z tej tabeli i z ręcznego dodania w UI.

Zasiew jest idempotentny i działa WYŁĄCZNIE, gdy istnieje klient o
``EZDROWIE_CLIENT_ID`` (w CI go nie ma → no-op). Umowa ramowa jest
rozpoznawana po ``(client_id, project_part)``, wykonawcza po
``(client_id, number)`` — powtórny start i migracja po safety-necie nic nie
dublują. Wykonują go migracja 0312 i ``entrypoint.sh`` (prod alembic bywa
osierocony). Numery umów nie są danymi osobowymi.
"""

from __future__ import annotations

from app.services.ezdrowie import EZDROWIE_CLIENT_ID

# (project_part, nazwa umowy ramowej, numery umów wykonawczych)
EZDROWIE_STRUCTURE: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("cz1", "CeZ/89/2025 – cz. I", ("CeZ/45/2026",)),
    ("cz2", "CeZ/145/2025 – cz. II", ("CeZ/242/2025", "CeZ/2/2026")),
    ("cz4", "CeZ/10/2025 – cz. IV", ()),
    ("cz5", "CeZ/118/2025 – cz. V", ()),
    ("cz6", "CeZ/33/2025 – cz. VI", ()),
)

EZDROWIE_SEED_SOURCE_SYSTEM = "ezdrowie_seed"


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_structure_seed_sql(client_id: int = EZDROWIE_CLIENT_ID) -> str:
    """SQL (bez parametrów ``:nazwa`` — leci przez ``text()`` w entrypoint)."""

    framework_rows = ",\n            ".join(
        "({cid}, {name}, {part}, {key})".format(
            cid=int(client_id),
            name=_sql_literal(name),
            part=_sql_literal(part),
            key=_sql_literal(f"ezdrowie:{part}"),
        )
        for part, name, _numbers in EZDROWIE_STRUCTURE
    )
    executive_rows = ",\n            ".join(
        "({part}, {number})".format(
            part=_sql_literal(part), number=_sql_literal(number)
        )
        for part, _name, numbers in EZDROWIE_STRUCTURE
        for number in numbers
    )
    return f"""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM clients WHERE id = {int(client_id)}) THEN
            RETURN;
        END IF;
        INSERT INTO client_framework_contracts
            (client_id, name, status, signed_via, currency, project_part,
             source_system, source_key)
        SELECT v.client_id, v.name,
               'active'::frameworkcontractstatus,
               'legacy_import'::frameworkcontractsignedvia,
               'PLN', v.project_part,
               {_sql_literal(EZDROWIE_SEED_SOURCE_SYSTEM)}, v.source_key
        FROM (VALUES
            {framework_rows}
        ) AS v(client_id, name, project_part, source_key)
        WHERE NOT EXISTS (
            SELECT 1 FROM client_framework_contracts fc
            WHERE fc.client_id = v.client_id AND fc.project_part = v.project_part
        );
        INSERT INTO client_executive_contracts
            (client_id, framework_contract_id, number, status)
        SELECT fc.client_id, fc.id, v.number, 'active'
        FROM (VALUES
            {executive_rows}
        ) AS v(project_part, number)
        JOIN client_framework_contracts fc
          ON fc.client_id = {int(client_id)} AND fc.project_part = v.project_part
        WHERE NOT EXISTS (
            SELECT 1 FROM client_executive_contracts ec
            WHERE ec.client_id = fc.client_id AND ec.number = v.number
        );
    END $$
    """


EZDROWIE_STRUCTURE_SEED_SQL = build_structure_seed_sql()
