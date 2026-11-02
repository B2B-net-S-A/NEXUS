"""Wycofywany Viewer (``user``) bez sekcji — JEDNO źródło SQL migracji 0636
i ``entrypoint.sh`` (przez ``hr_schema_bundle``).

Audyt najmniejszych dostępów 02.11.2026: rola bez nowych kont przechodziła
bramki sekcji do odczytu, także imienne Insights. Na kopii produkcji z tego dnia
nie ma żadnego konta tej roli, więc zerowanie nikomu nie odbiera pracy.

Biegnie RAZ (znacznik w ``app_settings``), bo entrypoint startuje przy każdym
wdrożeniu, a późniejsza decyzja admina w panelu ma zostać.
"""

from __future__ import annotations

MARKER = "0636_viewer_role_no_sections"

ZERO_SECTIONS = (
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM app_settings WHERE key = "
    f"'{MARKER}') THEN "
    "UPDATE rbac_role_section_permissions SET access = 'none', updated_at = now() "
    "WHERE role = 'user' AND access <> 'none'; "
    "UPDATE rbac_policy_state SET revision = revision + 1, updated_at = now() "
    "WHERE id = 1; "
    "INSERT INTO app_settings (key, value) VALUES "
    f"('{MARKER}', jsonb_build_object('completed_at', clock_timestamp())) "
    "ON CONFLICT (key) DO NOTHING; END IF; END $$"
)

DATA_DDL: tuple[str, ...] = (ZERO_SECTIONS,)
