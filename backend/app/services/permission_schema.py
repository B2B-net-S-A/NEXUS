"""Schemat i zasiew dziewięciu uprawnień — jedno źródło SQL.

Czytają je: migracja ``0409_named_permissions``, migracja ``0282`` (żeby jej
ponowne uruchomienie przy starcie nigdy nie zwęziło CHECK-a), literały
``CREATE TABLE`` w ``entrypoint.sh`` (przez test lustra) i siatka przy starcie
(``named_permissions_bootstrap``). Wszystko powstaje z ``permission_catalog``.
"""

from __future__ import annotations

from app.services import permission_catalog as catalog

ACTION_TABLES: tuple[str, ...] = (
    "rbac_role_action_permissions",
    "rbac_user_action_overrides",
)

#: Każda akcja, którą przyjmują tabele uprawnień: generator + dziewięć z ekranu.
ACTIONS: tuple[str, ...] = (catalog.GENERATOR, *catalog.KEYS)

_LEVEL = {"read": 1, "write": 2}


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


ACTION_CHECK_SQL = f"action IN ({_quoted(ACTIONS)})"


def constraint_name(table: str) -> str:
    return f"ck_{table}_action"


def widen_action_checks_sql() -> list[str]:
    """DDL poszerzający CHECK akcji w obu tabelach (idempotentny)."""

    statements: list[str] = []
    for table in ACTION_TABLES:
        name = constraint_name(table)
        statements.append(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
        statements.append(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({ACTION_CHECK_SQL})"
        )
    return statements


def _values(rows: list[str]) -> str:
    return ",\n        ".join(rows)


_ROLE_ROWS = [f"('{role}')" for role in catalog.ROLES]
_ACTION_ROWS = [f"('{key}')" for key in catalog.SEEDED_KEYS]
_HOLDER_ROWS = [
    f"('{holder.role}', '{permission.key}')"
    for permission in catalog.PERMISSIONS
    if permission.seeded
    for holder in permission.holders
]
_NEED_ROWS = [
    f"('{holder.role}', '{permission.key}', '{section}', {_LEVEL[minimum]})"
    for permission in catalog.PERMISSIONS
    if permission.seeded
    for holder in permission.holders
    for section, minimum in holder.needs
]

# Zasiew: wiersz dla KAŻDEJ pary rola × uprawnienie. „manage” dostaje admin
# oraz domyślny posiadacz, którego ZAPISANE sekcje spełniają progi; reszta
# dostaje jawne „none”. Istniejącego wiersza nie rusza (decyzja z panelu wygrywa).
SEED_SQL = f"""
WITH roles(role) AS (
    VALUES
        {_values(_ROLE_ROWS)}
),
actions(action) AS (
    VALUES
        {_values(_ACTION_ROWS)}
),
holders(role, action) AS (
    VALUES
        {_values(_HOLDER_ROWS)}
),
needs(role, action, section, min_level) AS (
    VALUES
        {_values(_NEED_ROWS)}
),
levels AS (
    SELECT role, section,
           CASE access WHEN 'write' THEN 2 WHEN 'read' THEN 1 ELSE 0 END AS level
    FROM rbac_role_section_permissions
)
INSERT INTO rbac_role_action_permissions (role, action, access)
SELECT roles.role, actions.action,
       CASE
           WHEN roles.role = '{catalog.ADMIN}' THEN 'manage'
           WHEN EXISTS (
                    SELECT 1 FROM holders
                    WHERE holders.role = roles.role
                      AND holders.action = actions.action
                )
                AND NOT EXISTS (
                    SELECT 1 FROM needs
                    LEFT JOIN levels
                           ON levels.role = needs.role
                          AND levels.section = needs.section
                    WHERE needs.role = roles.role
                      AND needs.action = actions.action
                      AND COALESCE(levels.level, 0) < needs.min_level
                )
           THEN 'manage'
           ELSE 'none'
       END
FROM roles CROSS JOIN actions
ON CONFLICT (role, action) DO NOTHING
"""

# Podpis B2B u TAC był włączony od 0282, ale nigdy nie działał (zakres klienta
# zawsze odmawiał). Ekran ma mówić prawdę, więc wiersz, którego nikt nie
# ustawił ręcznie, przechodzi na „none”. Wiersz zmieniony w panelu zostaje.
TAC_SIGNATURE_SQL = f"""
UPDATE rbac_role_action_permissions
SET access = 'none', updated_at = now()
WHERE role = 'tac'
  AND action = '{catalog.SIGNATURE}'
  AND access = 'manage'
  AND updated_by IS NULL
"""

BUMP_REVISION_SQL = (
    "UPDATE rbac_policy_state SET revision = revision + 1, updated_at = now() "
    "WHERE id = 1"
)

# Oba CHECK-i znają ostatnią akcję katalogu i każda rola ma komplet wierszy.
READY_SQL = f"""
SELECT (
    SELECT count(*) FROM pg_constraint
    WHERE conname IN ({_quoted(tuple(constraint_name(t) for t in ACTION_TABLES))})
      AND pg_get_constraintdef(oid) LIKE '%{catalog.SEEDED_KEYS[-1]}%'
) = {len(ACTION_TABLES)} AND (
    SELECT count(*) FROM rbac_role_action_permissions
    WHERE action IN ({_quoted(catalog.SEEDED_KEYS)})
      AND role IN ({_quoted(catalog.ROLES)})
) = {len(catalog.SEEDED_KEYS) * len(catalog.ROLES)}
"""


def apply_statements() -> list[str]:
    """Pełna naprawa w kolejności wykonania: CHECK → zasiew → TAC → rewizja."""

    return [
        *widen_action_checks_sql(),
        SEED_SQL,
        TAC_SIGNATURE_SQL,
        BUMP_REVISION_SQL,
    ]
