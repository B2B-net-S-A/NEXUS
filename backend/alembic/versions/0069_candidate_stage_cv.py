"""CV per rekrutacja — junction `candidate_stage_cvs` + `cv_share_tokens`.

Revision ID: 0069_candidate_stage_cv
Revises: 0068_candidate_risk
Create Date: 2026-04-28 09:00:00.000000

Tworzy:

  candidate_stage_cvs
    — 1:1 z candidate_stages (UNIQUE candidate_stage_id)
    — `original_cv_*`     migawka CV kandydata z momentu utworzenia stage'a,
                          niemutowalna po insert; rozwiązuje "Traffit pain"
                          (jeden kandydat = jedno aktualne CV myli rekruterów
                          gdy ten sam kandydat jest na wielu req).
    — `branded_*`         brandowane CV per rekrutacja: lazy-rendered draft
                          (Tiptap), finalize → snapshot HTML do storage_service.
                          Mirror Phase 16 Contract Draft.

  cv_share_tokens
    — token-based public link do brandowanego CV (per stage).
    — TTL default 30d, można odwołać przez `revoked=true`.
    — Mirror `engagement_declaration_tokens` (0062) i ChampionCardShareToken.

Idempotent + reversible. Wszystkie kolumny snapshot/branded są NULL-able tak
że istniejące rekrutacje nie wymagają backfillu w tej migracji (data-migration
dla snapshotu oryginalnego idzie osobno jako 0070_backfill_candidate_stage_cv).
"""

from alembic import op


revision = "0069_candidate_stage_cv"
down_revision = "0068_candidate_risk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── candidate_stage_cvs ─────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_stage_cvs (
            id SERIAL PRIMARY KEY,
            candidate_stage_id INTEGER NOT NULL UNIQUE,
            candidate_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,

            original_cv_filename VARCHAR(500) NULL,
            original_cv_content BYTEA NULL,
            original_cv_language VARCHAR(10) NULL,
            original_snapshot_at TIMESTAMPTZ NULL,
            original_snapshot_source VARCHAR(20) NULL,

            branded_status VARCHAR(20) NOT NULL DEFAULT 'none',
            branded_draft_html TEXT NULL,
            branded_template VARCHAR(20) NULL,
            branded_language VARCHAR(10) NULL,
            branded_updated_at TIMESTAMPTZ NULL,
            branded_updated_by INTEGER NULL,
            branded_finalized_at TIMESTAMPTZ NULL,
            branded_finalized_by INTEGER NULL,
            branded_snapshot_path VARCHAR(512) NULL,
            branded_snapshot_filename VARCHAR(255) NULL,
            branded_snapshot_size_bytes INTEGER NULL,

            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    # FK constraints (drop+recreate dla idempotencji na rerunach).
    for name, ddl in [
        (
            "fk_csv_candidate_stage_id",
            "ALTER TABLE candidate_stage_cvs "
            "ADD CONSTRAINT fk_csv_candidate_stage_id "
            "FOREIGN KEY (candidate_stage_id) REFERENCES candidate_stages(id) "
            "ON DELETE CASCADE",
        ),
        (
            "fk_csv_candidate_id",
            "ALTER TABLE candidate_stage_cvs "
            "ADD CONSTRAINT fk_csv_candidate_id "
            "FOREIGN KEY (candidate_id) REFERENCES candidates(id) "
            "ON DELETE CASCADE",
        ),
        (
            "fk_csv_job_id",
            "ALTER TABLE candidate_stage_cvs "
            "ADD CONSTRAINT fk_csv_job_id "
            "FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE",
        ),
        (
            "fk_csv_branded_updated_by",
            "ALTER TABLE candidate_stage_cvs "
            "ADD CONSTRAINT fk_csv_branded_updated_by "
            "FOREIGN KEY (branded_updated_by) REFERENCES users(id) "
            "ON DELETE SET NULL",
        ),
        (
            "fk_csv_branded_finalized_by",
            "ALTER TABLE candidate_stage_cvs "
            "ADD CONSTRAINT fk_csv_branded_finalized_by "
            "FOREIGN KEY (branded_finalized_by) REFERENCES users(id) "
            "ON DELETE SET NULL",
        ),
    ]:
        op.execute(
            f"ALTER TABLE candidate_stage_cvs DROP CONSTRAINT IF EXISTS {name}"
        )
        op.execute(ddl)

    # Indeksy (UNIQUE na candidate_stage_id już z CREATE TABLE).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_csv_candidate_id "
        "ON candidate_stage_cvs (candidate_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_csv_job_id "
        "ON candidate_stage_cvs (job_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_csv_branded_finalized "
        "ON candidate_stage_cvs (candidate_stage_id) "
        "WHERE branded_status = 'finalized'"
    )

    # ── cv_share_tokens ─────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cv_share_tokens (
            token VARCHAR(64) PRIMARY KEY,
            candidate_stage_cv_id INTEGER NOT NULL,
            created_by INTEGER NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NULL,
            revoked BOOLEAN NOT NULL DEFAULT false
        )
        """
    )
    for name, ddl in [
        (
            "fk_cvst_candidate_stage_cv_id",
            "ALTER TABLE cv_share_tokens "
            "ADD CONSTRAINT fk_cvst_candidate_stage_cv_id "
            "FOREIGN KEY (candidate_stage_cv_id) REFERENCES candidate_stage_cvs(id) "
            "ON DELETE CASCADE",
        ),
        (
            "fk_cvst_created_by",
            "ALTER TABLE cv_share_tokens "
            "ADD CONSTRAINT fk_cvst_created_by "
            "FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL",
        ),
    ]:
        op.execute(f"ALTER TABLE cv_share_tokens DROP CONSTRAINT IF EXISTS {name}")
        op.execute(ddl)

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cvst_candidate_stage_cv_id "
        "ON cv_share_tokens (candidate_stage_cv_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cvst_live "
        "ON cv_share_tokens (candidate_stage_cv_id) WHERE revoked IS FALSE"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_cvst_live")
    op.execute("DROP INDEX IF EXISTS ix_cvst_candidate_stage_cv_id")
    op.execute("DROP TABLE IF EXISTS cv_share_tokens")

    op.execute("DROP INDEX IF EXISTS ix_csv_branded_finalized")
    op.execute("DROP INDEX IF EXISTS ix_csv_job_id")
    op.execute("DROP INDEX IF EXISTS ix_csv_candidate_id")
    op.execute("DROP TABLE IF EXISTS candidate_stage_cvs")
