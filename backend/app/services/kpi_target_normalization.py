"""Jednorazowe uporządkowanie `kpi_role_defaults` / `user_kpi_targets` (0346).

Jedno źródło SQL-a dla migracji 0346 i lustra w `entrypoint.sh` (prod alembic
bywa osierocony). Moduł celowo NIE importuje kodu aplikacji — migracja biegnie
też na starym obrazie. Zgodność stałych z katalogiem (`kpi_catalog`) pilnuje
`tests/test_kpi_catalog_unification.py`.

Co robi (w jednej transakcji, raz — marker w `app_settings` + advisory lock):

1. Kasuje martwe id z 0034 (`daily_activity_count`, `weekly_screenings`).
2. Przepisuje stare id panelu „Moje KPI" na kanoniczne id katalogu. Gdy dla tej
   samej roli (osoby) istnieją oba wiersze, zostaje wiersz spod STAREGO id —
   to seed 0124, młodszy niż 0034 i zgodny z decyzją z 22.09.
3. Kasuje wiersze z wartościami seeda 0034 (recruiter 2 / TAC 3 placementy,
   recruiter 3 / TAC 2 nowych kandydatów…) — to były kopie kodu, nie decyzje
   ludzi, a po 22.09 są nieaktualne.
4. Kasuje wiersze RÓWNE domyślnym z katalogu. Nie zmienia to żadnego celu
   (wiersz i katalog dają tę samą liczbę), a sprawia, że katalog jest jedynym
   źródłem liczb: tabela ról trzyma wyłącznie świadome odstępstwa.

`user_kpi_targets` (osobiste cele) przechodzi wyłącznie krok 2 — osobisty cel
równy domyślnemu jest nadal decyzją o tej osobie.
"""

from __future__ import annotations

KPI_TARGET_NORMALIZATION_MARKER = "0346_kpi_catalog_unification"

# Stary id → kanoniczny id (lustro `kpi_catalog.KPI_ID_ALIASES`).
KPI_ID_RENAMES: tuple[tuple[str, str], ...] = (
    ("verifications_daily", "daily_first_verifications"),
    ("cv_added_daily", "daily_new_candidates"),
    ("placements_monthly", "monthly_placements"),
    ("precision_monthly", "monthly_precision"),
)

# Lustro `kpi_catalog.RETIRED_KPI_IDS`.
RETIRED_KPI_IDS: tuple[str, ...] = ("daily_activity_count", "weekly_screenings")

# Wartości zasiane przez 0034 dla id, które żyją dalej (kpi_id, rola, wartość).
OLD_SEED_ROWS: tuple[tuple[str, str, int], ...] = (
    ("daily_new_candidates", "recruiter", 3),
    ("daily_new_candidates", "tac", 2),
    ("daily_new_candidates", "sourcer", 5),
    ("weekly_cvs_sent", "recruiter", 15),
    ("weekly_cvs_sent", "tac", 12),
    ("monthly_placements", "recruiter", 2),
    ("monthly_placements", "tac", 3),
    ("monthly_placements", "sourcer", 1),
)

# Lustro domyślnych celów katalogu (kpi_id, rola, wartość) — decyzje 22.09.2026.
CATALOG_DEFAULT_ROWS: tuple[tuple[str, str, int], ...] = (
    ("daily_completed_calls", "recruiter", 15),
    ("daily_completed_calls", "sourcer", 15),
    ("daily_completed_calls", "tac", 15),
    ("daily_first_verifications", "recruiter", 4),
    ("daily_first_verifications", "sourcer", 4),
    ("daily_first_verifications", "tac", 4),
    ("daily_new_candidates", "recruiter", 5),
    ("daily_new_candidates", "sourcer", 5),
    ("daily_new_candidates", "tac", 5),
    ("weekly_cvs_sent", "recruiter", 15),
    ("weekly_cvs_sent", "tac", 12),
    ("monthly_placements", "recruiter", 1),
    ("monthly_placements", "sourcer", 1),
    ("monthly_placements", "tac", 1),
    ("monthly_precision", "recruiter", 75),
    ("monthly_precision", "sourcer", 75),
    ("monthly_precision", "tac", 75),
)


def _values(rows: tuple[tuple[str, str, int], ...]) -> str:
    return ", ".join(f"('{kpi}', '{role}', {int(value)})" for kpi, role, value in rows)


def _rename_block() -> str:
    parts: list[str] = []
    for legacy, canonical in KPI_ID_RENAMES:
        parts.append(
            f"""
    DELETE FROM kpi_role_defaults c
     WHERE c.kpi_id = '{canonical}'
       AND EXISTS (
           SELECT 1 FROM kpi_role_defaults l
            WHERE l.kpi_id = '{legacy}' AND l.role = c.role
       );
    UPDATE kpi_role_defaults
       SET kpi_id = '{canonical}', updated_at = now()
     WHERE kpi_id = '{legacy}';
    DELETE FROM user_kpi_targets c
     WHERE c.kpi_id = '{canonical}'
       AND EXISTS (
           SELECT 1 FROM user_kpi_targets l
            WHERE l.kpi_id = '{legacy}' AND l.user_id = c.user_id
       );
    UPDATE user_kpi_targets
       SET kpi_id = '{canonical}', updated_at = now()
     WHERE kpi_id = '{legacy}';"""
        )
    return "".join(parts)


_RETIRED_SQL = ", ".join(f"'{kpi}'" for kpi in RETIRED_KPI_IDS)

KPI_TARGET_NORMALIZATION_SQL = f"""
DO $kpi_catalog_unification$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('{KPI_TARGET_NORMALIZATION_MARKER}'));
    IF EXISTS (
        SELECT 1 FROM app_settings WHERE key = '{KPI_TARGET_NORMALIZATION_MARKER}'
    ) THEN
        RETURN;
    END IF;

    DELETE FROM kpi_role_defaults WHERE kpi_id IN ({_RETIRED_SQL});
{_rename_block()}

    DELETE FROM kpi_role_defaults d
     USING (VALUES {_values(OLD_SEED_ROWS)}) AS seed(kpi_id, role, value)
     WHERE d.kpi_id = seed.kpi_id
       AND d.role::text = seed.role
       AND d.target_value = seed.value;

    DELETE FROM kpi_role_defaults d
     USING (VALUES {_values(CATALOG_DEFAULT_ROWS)}) AS def(kpi_id, role, value)
     WHERE d.kpi_id = def.kpi_id
       AND d.role::text = def.role
       AND d.target_value = def.value;

    INSERT INTO app_settings (key, value)
    VALUES ('{KPI_TARGET_NORMALIZATION_MARKER}', '{{"done": true}}'::jsonb)
    ON CONFLICT (key) DO NOTHING;
END
$kpi_catalog_unification$;
"""
