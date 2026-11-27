"""Etap „Zweryfikowany” → „Przygotowanie CV” w szablonach NEXUSA.

Revision ID: 0798_stage_przygotowanie_cv
Revises: 0797_verification_counts_from_qc_cv

Decyzja z 27.11.2026: weryfikacja liczy się od wejścia pary na „QC CV”, a w
kolumnie `verified` powstaje CV firmowe — kolumna Tablicy nazywa się więc
„Przygotowanie CV”. Kod etapu (`verified`) się nie zmienia.

Zmiana nazwy idzie tylko w szablonach spoza Traffita (np. „Default B2B”).
Szablon z Traffita zostaje — nocny sync i tak by go przepisał, a jego etap
„Zweryfikowany” trafia na etap `verified` szablonu rekrutacji po kodzie
(`board_stage_badges.foreign_stage_target`). Szablon, który ma już etap
„Przygotowanie CV”, pomijamy. Zmiana jest JEDNORAZOWA (znacznik
w ``app_settings``), więc ręczna zmiana nazwy przez admina nie jest cofana
przy starcie kontenera — wzór 0361.

Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony) — pilnuje
``test_stage_przygotowanie_cv.py``.
"""

from alembic import op

revision = "0798_stage_przygotowanie_cv"
down_revision = "0797_verification_counts_from_qc_cv"
branch_labels = None
depends_on = None

RENAME_MARKER = "0798_stage_renamed_przygotowanie_cv"
# Wstawienie znacznika i zmiana nazwy w JEDNEJ instrukcji: drugie uruchomienie
# (entrypoint przy każdym starcie) nic nie robi, bo znacznik już jest.
RENAME_VERIFIED_STAGE = (
    "WITH marker AS ("
    "INSERT INTO app_settings (key, value) "
    f"VALUES ('{RENAME_MARKER}', 'true'::jsonb) "
    "ON CONFLICT (key) DO NOTHING RETURNING key) "
    "UPDATE pipeline_stage_defs SET name = 'Przygotowanie CV', updated_at = now() "
    "WHERE name = 'Zweryfikowany' "
    "AND template_id IN (SELECT id FROM pipeline_templates "
    "WHERE coalesce(external_source, 'manual') <> 'traffit') "
    "AND NOT EXISTS (SELECT 1 FROM pipeline_stage_defs x "
    "WHERE x.template_id = pipeline_stage_defs.template_id "
    "AND x.name = 'Przygotowanie CV') "
    "AND EXISTS (SELECT 1 FROM marker)"
)


def upgrade() -> None:
    op.execute(RENAME_VERIFIED_STAGE)


def downgrade() -> None:
    op.execute(
        "UPDATE pipeline_stage_defs SET name = 'Zweryfikowany', "
        "updated_at = now() "
        "WHERE name = 'Przygotowanie CV' "
        "AND template_id IN (SELECT id FROM pipeline_templates "
        "WHERE coalesce(external_source, 'manual') <> 'traffit') "
        "AND NOT EXISTS (SELECT 1 FROM pipeline_stage_defs x "
        "WHERE x.template_id = pipeline_stage_defs.template_id "
        "AND x.name = 'Zweryfikowany')"
    )
    op.execute(f"DELETE FROM app_settings WHERE key = '{RENAME_MARKER}'")
