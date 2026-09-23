"""Przegląd DZ + jedna osoba wysyłająca do Cpro na rekrutację.

Revision ID: 0353_dz_review_cpro_sender
Revises: 0352_pipeline_v4

Decyzje Artura 23.09.2026:

* Do Cpro wysyła JEDNA osoba na cały proces (rekrutację), nie inna osoba na
  każdego kandydata — ``jobs.cpro_sender_id``. Kolumna
  ``candidate_stages.task_assignee_id`` (0348) zostaje: niesie typowania
  sprzed tej zmiany i jest zapasem, gdy rekrutacja nie ma jeszcze osoby.
* Dominik zatwierdza DZ, porównując CV dla klienta z oryginałem i zapytaniem
  klienta; podpowiedzi liczy GPT-6 Luna (klucz AI ``dz_review``). Wynik jest
  zapamiętany per wiersz etapu i skrót wejścia (``dz_review_hints``), żeby
  ponowne otwarcie tego samego kandydata nie płaciło drugi raz.

Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony).
"""

from alembic import op

revision = "0353_dz_review_cpro_sender"
down_revision = "0352_pipeline_v4"
branch_labels = None
depends_on = None

JOBS_CPRO_SENDER = (
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS cpro_sender_id INTEGER NULL "
    "REFERENCES users(id) ON DELETE SET NULL"
)
CREATE_DZ_REVIEW_HINTS = """CREATE TABLE IF NOT EXISTS dz_review_hints (
    id BIGSERIAL PRIMARY KEY,
    candidate_stage_id INTEGER NOT NULL
        REFERENCES candidate_stages(id) ON DELETE CASCADE,
    input_hash VARCHAR(64) NOT NULL,
    model VARCHAR(80) NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_dz_review_hints_stage_hash UNIQUE (candidate_stage_id, input_hash)
)"""


def upgrade() -> None:
    # ADD VALUE musi biec w autocommicie (nowej etykiety nie da się użyć w tej
    # samej transakcji, w której ją dodano).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'dz_review'")
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        "SELECT 'dz_review', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS (SELECT 1 FROM ai_features WHERE feature = 'dz_review')"
    )
    op.execute(JOBS_CPRO_SENDER)
    op.execute(CREATE_DZ_REVIEW_HINTS)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dz_review_hints")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS cpro_sender_id")
    # Wartość enuma zostaje — Postgres nie ma `ALTER TYPE … DROP VALUE`.
