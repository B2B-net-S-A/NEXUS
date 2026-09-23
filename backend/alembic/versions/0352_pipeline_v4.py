"""Pipeline v4 (23.09.2026): blokada 12 h, źródło wejścia, kto zakończył proces.

Revision ID: 0352_pipeline_v4
Revises: 0351_audit_round2

Tablica rekrutacji ma sześć kolumn (Nowi · Zweryfikowany · CV wysłane ·
Rozmowa u klienta · Umowa · Zatrudniony). Etapy szablonu zostają — tablica
tylko je składa — więc migracja dokłada wyłącznie to, czego nie da się
wyliczyć z etapów:

* ``recruitment_processes.claimed_by_user_id`` / ``claimed_until`` — osoba
  dodana ręcznie jest przez 12 h na wyłączność dodającego w tej rekrutacji,
  potem każdy może ją przejąć (decyzja Artura 23.09.2026).
* ``recruitment_processes.entry_source`` + ``reassign_from_job_id`` — skąd
  osoba weszła do rekrutacji (dotąd źródło szło tylko do telemetrii),
  przepięcie pamięta rekrutację, z której przyszło.
* ``candidate_stages.ended_by`` — kto zakończył proces: kandydat, my,
  Delivery Lead albo klient.
* ``interview_feedback.no_client_questions`` — debrief po rozmowie u klienta
  z jawnym „klient nie zadawał pytań” (bramka przed „Umową”).
* dwa typy powiadomień i klucz AI podpowiedzi przy przepięciu.

Lustro w ``entrypoint.sh`` (alembic na prodzie bywa osierocony).
"""

from alembic import op

revision = "0352_pipeline_v4"
down_revision = "0351_audit_round2"
branch_labels = None
depends_on = None

ENTRY_SOURCES = (
    "added_manual",
    "application",
    "proposal",
    "reassign",
    "auto_match",
    "import",
)
ENDED_BY = ("candidate", "recruiter", "delivery_lead", "client")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'candidate_claim_taken'"
        )
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'hired_order_missing'"
        )
        op.execute(
            "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'screening_reassign_suggest'"
        )

    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        "SELECT 'screening_reassign_suggest', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS "
        "(SELECT 1 FROM ai_features WHERE feature = 'screening_reassign_suggest')"
    )

    op.execute(
        "ALTER TABLE recruitment_processes ADD COLUMN IF NOT EXISTS "
        "claimed_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE recruitment_processes ADD COLUMN IF NOT EXISTS "
        "claimed_until TIMESTAMPTZ NULL"
    )
    op.execute(
        "ALTER TABLE recruitment_processes ADD COLUMN IF NOT EXISTS "
        "entry_source VARCHAR(24) NULL"
    )
    op.execute(
        "ALTER TABLE recruitment_processes ADD COLUMN IF NOT EXISTS "
        "reassign_from_job_id INTEGER NULL REFERENCES jobs(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE recruitment_processes "
        "DROP CONSTRAINT IF EXISTS ck_recruitment_processes_entry_source"
    )
    op.execute(
        "ALTER TABLE recruitment_processes ADD CONSTRAINT "
        "ck_recruitment_processes_entry_source CHECK "
        f"(entry_source IS NULL OR entry_source IN ({_in_list(ENTRY_SOURCES)}))"
    )
    op.execute(
        "ALTER TABLE recruitment_processes "
        "DROP CONSTRAINT IF EXISTS ck_recruitment_processes_claim_pair"
    )
    op.execute(
        "ALTER TABLE recruitment_processes ADD CONSTRAINT "
        "ck_recruitment_processes_claim_pair CHECK "
        "((claimed_by_user_id IS NULL) = (claimed_until IS NULL))"
    )

    op.execute(
        "ALTER TABLE candidate_stages ADD COLUMN IF NOT EXISTS ended_by VARCHAR(16) NULL"
    )
    op.execute(
        "ALTER TABLE candidate_stages DROP CONSTRAINT IF EXISTS ck_candidate_stages_ended_by"
    )
    op.execute(
        "ALTER TABLE candidate_stages ADD CONSTRAINT ck_candidate_stages_ended_by "
        f"CHECK (ended_by IS NULL OR ended_by IN ({_in_list(ENDED_BY)})) NOT VALID"
    )

    op.execute(
        "ALTER TABLE interview_feedback ADD COLUMN IF NOT EXISTS "
        "no_client_questions BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE interview_feedback DROP COLUMN IF EXISTS no_client_questions"
    )
    op.execute(
        "ALTER TABLE candidate_stages DROP CONSTRAINT IF EXISTS ck_candidate_stages_ended_by"
    )
    op.execute("ALTER TABLE candidate_stages DROP COLUMN IF EXISTS ended_by")
    op.execute(
        "ALTER TABLE recruitment_processes "
        "DROP CONSTRAINT IF EXISTS ck_recruitment_processes_claim_pair"
    )
    op.execute(
        "ALTER TABLE recruitment_processes "
        "DROP CONSTRAINT IF EXISTS ck_recruitment_processes_entry_source"
    )
    for column in (
        "reassign_from_job_id",
        "entry_source",
        "claimed_until",
        "claimed_by_user_id",
    ):
        op.execute(f"ALTER TABLE recruitment_processes DROP COLUMN IF EXISTS {column}")
    # Wartości enumów zostają — Postgres nie ma `ALTER TYPE … DROP VALUE`.
