"""Połączenie ról `sourcer` + `recruiter` + `tac` w jedną rolę `recruiter` (0411).

Decyzja Artura 02.10.2026: „sourcer, rekruter, TAC jako jedno — rekruter”.
Jedno źródło SQL-a dla migracji 0411 i lustra w `entrypoint.sh` (prod alembic
bywa osierocony). Moduł celowo NIE importuje kodu aplikacji — migracja biegnie
też na starym obrazie, a `core/config.py` importuje stąd normalizator bez cyklu.

Instrukcje są ZBIEŻNE, nie jednorazowe: każda dotyka wyłącznie wierszy ze starą
wartością, więc drugi przebieg (alembic, potem entrypoint, potem każdy kolejny
start) zmienia 0 wierszy i nie unieważnia sesji drugi raz. Entrypoint wykonuje
je przy każdym starcie, bo stara wartość może wrócić spoza aplikacji (odtworzona
kopia, stary obraz po rollbacku, surowy INSERT z importu).

Etykiety `sourcer` i `tac` ZOSTAJĄ w typie `userrole` (Postgres nie ma
`DROP VALUE`) i w CHECK-ach tabel RBAC: po rollbacku obrazu stary kod wstawia
wiersze tych ról, a wąski CHECK zatrzymałby wtedy start kontenera. Porównania
idą zawsze przez `role::text`.

Co robi:

1. Konta — `role` i lista `roles` (rola dodatkowa u Delivery Leada, Head of
   Recruitment i TCM też przechodzi na `recruiter`, bez duplikatu). Stan sprzed
   zmiany trafia do `role_session_migration_audit` (same id i role). Sesje
   zmienionych kont są unieważniane — token niesie rolę. Konto, którego rola
   główna była `sourcer` albo `tac`, nie przechodzi onboardingu rekrutera:
   pracuje w NEXUSIE od dawna, a te role nigdy go nie wymagały.
2. Wiersze `sourcer`/`tac` w obu tabelach uprawnień RBAC — skasowane; ich treść
   zostaje pod `repair_details_…` (do przywrócenia), liczniki pod kluczem
   paragonu.
3. `kpi_role_defaults` — wiersze tych ról skasowane (cel rekrutera idzie
   z katalogu KPI).
4. Reguły powiadomień etapów wskazujące rolę — przepisane na `recruiter`;
   bliźniak, który po przepisaniu byłby duplikatem, jest kasowany wcześniej
   (`uq_client_stage_override`).
5. `job_work_assignments.role` — `sourcer` → `recruiter` (rola pracy przy
   requeście przestała istnieć).

`kpi_target_events` to dziennik zmian — zostaje nietknięty.
"""

from __future__ import annotations

ROLE_MERGE_KEY = "0411_merge_recruiter_roles"
ROLE_MERGE_DETAILS_KEY = f"repair_details_{ROLE_MERGE_KEY}"

MERGED_ROLE_VALUE = "recruiter"
RETIRED_ROLE_VALUES: tuple[str, ...] = ("sourcer", "tac")


def normalize_role_value(value: str) -> str:
    """Wycofana rola (`sourcer`, `tac`) to dziś `recruiter`; reszta bez zmian."""

    return MERGED_ROLE_VALUE if value in RETIRED_ROLE_VALUES else value


_ACCOUNTS_SQL = f"""
WITH target AS (
    SELECT id,
           role::text AS old_role,
           roles AS old_roles,
           profile_completed,
           authorization_version,
           tokens_valid_after
    FROM users
    WHERE role::text IN ('sourcer', 'tac')
       OR roles ?| ARRAY['sourcer', 'tac']
    FOR UPDATE
),
rewritten AS (
    SELECT t.id,
           t.old_role IN ('sourcer', 'tac') AS primary_retired,
           CASE
               WHEN t.old_role IN ('sourcer', 'tac') THEN 'recruiter'
               ELSE t.old_role
           END AS new_role,
           (
               SELECT COALESCE(
                   jsonb_agg(d.value ORDER BY d.first_ord), '[]'::jsonb
               )
               FROM (
                   SELECT CASE
                              WHEN e.value IN ('sourcer', 'tac') THEN 'recruiter'
                              ELSE e.value
                          END AS value,
                          MIN(e.ordinality) AS first_ord
                   FROM jsonb_array_elements_text(t.old_roles)
                        WITH ORDINALITY AS e(value, ordinality)
                   GROUP BY 1
               ) AS d
           ) AS new_roles
    FROM target AS t
),
audit AS (
    INSERT INTO role_session_migration_audit (
        migration_key, user_id, original_state
    )
    SELECT '{ROLE_MERGE_KEY}',
           t.id,
           jsonb_build_object(
               'role', t.old_role,
               'roles', t.old_roles,
               'profile_completed', t.profile_completed,
               'authorization_version', t.authorization_version,
               'tokens_valid_after', t.tokens_valid_after
           )
    FROM target AS t
    ON CONFLICT (migration_key, user_id) DO NOTHING
)
UPDATE users AS u
SET role = r.new_role::userrole,
    roles = CASE
        WHEN r.new_roles ? r.new_role THEN r.new_roles
        ELSE jsonb_build_array(r.new_role) || r.new_roles
    END,
    profile_completed = CASE
        WHEN r.primary_retired THEN TRUE
        ELSE u.profile_completed
    END,
    profile_completed_at = CASE
        WHEN r.primary_retired
            THEN COALESCE(u.profile_completed_at, clock_timestamp())
        ELSE u.profile_completed_at
    END,
    authorization_version = GREATEST(u.authorization_version, 1) + 1,
    tokens_valid_after = clock_timestamp()
FROM rewritten AS r
WHERE u.id = r.id
"""

# Rewizji polityki (`rbac_policy_state`) celowo nie podbijamy: po kroku 1 żadne
# konto nie ma już tych ról, więc niczyje uprawnienia się nie zmieniają.
_RBAC_ROWS_SQL = f"""
WITH gone_sections AS (
    DELETE FROM rbac_role_section_permissions
    WHERE role IN ('sourcer', 'tac')
    RETURNING *
),
gone_actions AS (
    DELETE FROM rbac_role_action_permissions
    WHERE role IN ('sourcer', 'tac')
    RETURNING *
),
counted AS (
    SELECT (SELECT count(*) FROM gone_sections) AS sections,
           (SELECT count(*) FROM gone_actions) AS actions,
           (
               SELECT COALESCE(jsonb_agg(to_jsonb(s)), '[]'::jsonb)
               FROM gone_sections AS s
           ) AS section_rows,
           (
               SELECT COALESCE(jsonb_agg(to_jsonb(a)), '[]'::jsonb)
               FROM gone_actions AS a
           ) AS action_rows
),
details AS (
    INSERT INTO app_settings (key, value, updated_at)
    SELECT '{ROLE_MERGE_DETAILS_KEY}',
           jsonb_build_object(
               'sections', c.section_rows, 'actions', c.action_rows
           ),
           now()
    FROM counted AS c
    WHERE c.sections + c.actions > 0
    ON CONFLICT (key) DO NOTHING
)
INSERT INTO app_settings (key, value, updated_at)
SELECT '{ROLE_MERGE_KEY}',
       jsonb_build_object(
           'rbac_section_rows_deleted', c.sections,
           'rbac_action_rows_deleted', c.actions
       ),
       now()
FROM counted AS c
WHERE c.sections + c.actions > 0
ON CONFLICT (key) DO NOTHING
"""

_KPI_ROLE_DEFAULTS_SQL = """
DELETE FROM kpi_role_defaults
WHERE role::text IN ('sourcer', 'tac')
"""

# Dla jednego etapu zostaje jedna reguła „rola: rekruter”: istniejąca reguła
# rekrutera, a gdy jej nie ma — najstarsza z reguł wycofanych ról.
_STAGE_RULE_TWINS_SQL = """
DELETE FROM stage_notification_rules AS doomed
USING (
    SELECT id,
           row_number() OVER (
               PARTITION BY stage_def_id
               ORDER BY (role = 'recruiter') DESC, id
           ) AS rn
    FROM stage_notification_rules
    WHERE recipient_type::text = 'role'
      AND role IN ('recruiter', 'sourcer', 'tac')
) AS ranked
WHERE doomed.id = ranked.id
  AND ranked.rn > 1
  AND doomed.role IN ('sourcer', 'tac')
"""

_STAGE_RULES_SQL = """
UPDATE stage_notification_rules
SET role = 'recruiter'
WHERE role IN ('sourcer', 'tac')
"""

_CLIENT_OVERRIDE_TWINS_SQL = """
DELETE FROM client_stage_notification_overrides AS doomed
USING (
    SELECT id,
           row_number() OVER (
               PARTITION BY client_id, stage_def_id
               ORDER BY (role = 'recruiter') DESC, id
           ) AS rn
    FROM client_stage_notification_overrides
    WHERE recipient_type::text = 'role'
      AND role IN ('recruiter', 'sourcer', 'tac')
) AS ranked
WHERE doomed.id = ranked.id
  AND ranked.rn > 1
  AND doomed.role IN ('sourcer', 'tac')
"""

_CLIENT_OVERRIDES_SQL = """
UPDATE client_stage_notification_overrides
SET role = 'recruiter'
WHERE role IN ('sourcer', 'tac')
"""

_WORK_ASSIGNMENTS_SQL = """
UPDATE job_work_assignments
SET role = 'recruiter'
WHERE role = 'sourcer'
"""

# Kolejność ma znaczenie: konta przed wierszami RBAC (nikt nie zostaje z rolą
# bez wierszy), bliźniaki przed przepisaniem reguł.
ROLE_MERGE_STATEMENTS: tuple[str, ...] = (
    _ACCOUNTS_SQL,
    _RBAC_ROWS_SQL,
    _KPI_ROLE_DEFAULTS_SQL,
    _STAGE_RULE_TWINS_SQL,
    _STAGE_RULES_SQL,
    _CLIENT_OVERRIDE_TWINS_SQL,
    _CLIENT_OVERRIDES_SQL,
    _WORK_ASSIGNMENTS_SQL,
)


# Przywrócenie (downgrade 0411 albo ręcznie po rollbacku obrazu — stary obraz
# nie uruchamia `alembic downgrade`). Wraca wyłącznie konto, którego rola
# główna i lista ról są nadal takie, jakie zostawiła konwersja: późniejsza
# zmiana przez administratora (także odebrana rola dodatkowa) wygrywa. Reguły powiadomień, cele ról i role pracy nie
# są przywracane — w dniu migracji produkcja nie miała takich wierszy.
_RESTORE_ACCOUNTS_SQL = f"""
UPDATE users AS u
SET role = (a.original_state ->> 'role')::userrole,
    roles = a.original_state -> 'roles',
    authorization_version = GREATEST(u.authorization_version, 1) + 1,
    tokens_valid_after = clock_timestamp()
FROM role_session_migration_audit AS a
WHERE a.migration_key = '{ROLE_MERGE_KEY}'
  AND a.user_id = u.id
  AND u.role::text = CASE
      WHEN a.original_state ->> 'role' IN ('sourcer', 'tac') THEN 'recruiter'
      ELSE a.original_state ->> 'role'
  END
  AND jsonb_typeof(u.roles) = 'array'
  AND (
      SELECT COALESCE(array_agg(DISTINCT c.value ORDER BY c.value), '{{}}')
      FROM jsonb_array_elements_text(u.roles) AS c(value)
  ) = (
      SELECT array_agg(DISTINCT m.value ORDER BY m.value)
      FROM (
          SELECT CASE
                     WHEN e.value IN ('sourcer', 'tac') THEN 'recruiter'
                     ELSE e.value
                 END AS value
          FROM jsonb_array_elements_text(a.original_state -> 'roles') AS e(value)
          UNION
          SELECT CASE
                     WHEN a.original_state ->> 'role' IN ('sourcer', 'tac')
                         THEN 'recruiter'
                     ELSE a.original_state ->> 'role'
                 END
      ) AS m
  )
"""

_RESTORE_RBAC_SECTIONS_SQL = f"""
INSERT INTO rbac_role_section_permissions
SELECT r.*
FROM app_settings AS s,
     jsonb_populate_recordset(
         NULL::rbac_role_section_permissions, s.value -> 'sections'
     ) AS r
WHERE s.key = '{ROLE_MERGE_DETAILS_KEY}'
ON CONFLICT DO NOTHING
"""

_RESTORE_RBAC_ACTIONS_SQL = f"""
INSERT INTO rbac_role_action_permissions
SELECT r.*
FROM app_settings AS s,
     jsonb_populate_recordset(
         NULL::rbac_role_action_permissions, s.value -> 'actions'
     ) AS r
WHERE s.key = '{ROLE_MERGE_DETAILS_KEY}'
ON CONFLICT DO NOTHING
"""

_FORGET_RECEIPTS_SQL = f"""
DELETE FROM app_settings
WHERE key IN ('{ROLE_MERGE_KEY}', '{ROLE_MERGE_DETAILS_KEY}')
"""

ROLE_MERGE_RESTORE_STATEMENTS: tuple[str, ...] = (
    _RESTORE_ACCOUNTS_SQL,
    _RESTORE_RBAC_SECTIONS_SQL,
    _RESTORE_RBAC_ACTIONS_SQL,
    _FORGET_RECEIPTS_SQL,
)
