"""QC CV zamiast ręcznego przeglądu DZ (Rekrutacja v5).

Revision ID: 0361_cv_qc
Revises: 0357_contract_orders_card_dismissed

Decyzje Artura 23.09.2026: kontrolę CV firmowego przed wysłaniem do klienta
liczy kod (must-have w CV, pogrubione, opisane w rolach, bez twierdzeń spoza
oryginału, lata, daty, reguły klienta), AI proponuje poprawki, rekruter je
akceptuje. QC jest twardą bramką przed „CV wysłane”/Cpro; obejście — Delivery
Lead albo admin z powodem.

* ``cv_qc_runs`` — przebiegi QC pary (kandydat, rekrutacja) i obejścia.
* Etap „Przepuszczony przez DZ” w szablonach NEXUSA (np. „Default B2B”)
  dostaje nazwę „QC CV”. Szablon z Traffita zostaje — nocny sync i tak by go
  przepisał, a tablica rozpoznaje jego etap po nazwie. Zmiana nazwy jest
  JEDNORAZOWA (znacznik w ``app_settings``), więc ręczna zmiana nazwy przez
  admina nie jest cofana przy starcie kontenera.

Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony) — pilnuje
``test_cv_qc.py``.
"""

from alembic import op

revision = "0361_cv_qc"
down_revision = "0357_contract_orders_card_dismissed"
branch_labels = None
depends_on = None

CREATE_CV_QC_RUNS = """CREATE TABLE IF NOT EXISTS cv_qc_runs (
    id BIGSERIAL PRIMARY KEY,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    candidate_stage_id INTEGER NULL
        REFERENCES candidate_stages(id) ON DELETE SET NULL,
    cv_fingerprint VARCHAR(64) NULL,
    passed BOOLEAN NOT NULL,
    blocking_failed INTEGER NOT NULL,
    warnings_count INTEGER NOT NULL,
    result JSONB NOT NULL,
    override_reason TEXT NULL,
    override_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)"""
CREATE_CV_QC_RUNS_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_cv_qc_runs_pair_created "
    "ON cv_qc_runs (candidate_id, job_id, created_at DESC)"
)

RENAME_MARKER = "0361_dz_stage_renamed_qc_cv"
# Wstawienie znacznika i zmiana nazwy w JEDNEJ instrukcji: drugie uruchomienie
# (entrypoint przy każdym starcie) nic nie robi, bo znacznik już jest.
RENAME_DZ_STAGE = (
    "WITH marker AS ("
    "INSERT INTO app_settings (key, value) "
    f"VALUES ('{RENAME_MARKER}', 'true'::jsonb) "
    "ON CONFLICT (key) DO NOTHING RETURNING key) "
    "UPDATE pipeline_stage_defs SET name = 'QC CV', updated_at = now() "
    "WHERE name = 'Przepuszczony przez DZ' "
    "AND template_id IN (SELECT id FROM pipeline_templates "
    "WHERE coalesce(external_source, 'manual') <> 'traffit') "
    "AND NOT EXISTS (SELECT 1 FROM pipeline_stage_defs x "
    "WHERE x.template_id = pipeline_stage_defs.template_id AND x.name = 'QC CV') "
    "AND EXISTS (SELECT 1 FROM marker)"
)


def upgrade() -> None:
    op.execute(CREATE_CV_QC_RUNS)
    op.execute(CREATE_CV_QC_RUNS_INDEX)
    op.execute(RENAME_DZ_STAGE)


def downgrade() -> None:
    op.execute(
        "UPDATE pipeline_stage_defs SET name = 'Przepuszczony przez DZ', "
        "updated_at = now() "
        "WHERE name = 'QC CV' "
        "AND template_id IN (SELECT id FROM pipeline_templates "
        "WHERE coalesce(external_source, 'manual') <> 'traffit') "
        "AND NOT EXISTS (SELECT 1 FROM pipeline_stage_defs x "
        "WHERE x.template_id = pipeline_stage_defs.template_id "
        "AND x.name = 'Przepuszczony przez DZ')"
    )
    op.execute(f"DELETE FROM app_settings WHERE key = '{RENAME_MARKER}'")
    op.execute("DROP TABLE IF EXISTS cv_qc_runs")
