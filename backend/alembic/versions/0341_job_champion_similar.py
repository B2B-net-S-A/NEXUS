"""Rekrutacje: „Mamy championa", podobne rekrutacje i przepięcia.

Revision ID: 0341_job_champion_similar
Revises: 0340_career_public_title

* ``jobs.champion_found_at`` / ``champion_found_by`` — Delivery Lead oznacza,
  że ma już kandydata („championa") i dalej nie szukamy. Do tej chwili status
  requestu na liście to „Szukamy" (decyzja Artura 22.09.2026).
* ``job_similar_links`` — rekrutacje wskazane jako podobne. Wiersz jest
  kierunkowy (``job_id`` przyjmuje osoby z ``similar_job_id``), ale serwis
  zakłada zawsze OBA kierunki naraz — podobieństwo requestu jest symetryczne.
* ``job_proposals.source`` dostaje ``reassign`` — przepięcie: osoba wysłana do
  klienta w podobnej rekrutacji trafia do „Do przejrzenia".

Lustro w ``entrypoint.sh`` — pilnuje ``tests/test_job_similar_links.py``.
"""

from alembic import op

revision = "0341_job_champion_similar"
down_revision = "0340_career_public_title"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS champion_found_at TIMESTAMPTZ NULL"
    )
    op.execute(
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS champion_found_by INTEGER NULL "
        "REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute(
        """CREATE TABLE IF NOT EXISTS job_similar_links (
            id BIGSERIAL PRIMARY KEY,
            job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            similar_job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_job_similar_links_pair UNIQUE (job_id, similar_job_id),
            CONSTRAINT ck_job_similar_links_not_self CHECK (job_id <> similar_job_id)
        )"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_similar_links_similar_job_id "
        "ON job_similar_links (similar_job_id)"
    )
    op.execute(
        """DO $$ BEGIN
            ALTER TABLE job_proposals DROP CONSTRAINT IF EXISTS ck_job_proposals_source;
            ALTER TABLE job_proposals ADD CONSTRAINT ck_job_proposals_source CHECK (
                source IN ('full_base', 'new_cv', 'similar_projects',
                           'recommendation', 'marketplace', 'reassign'));
        END $$"""
    )


def downgrade() -> None:
    op.execute("DELETE FROM job_proposals WHERE source = 'reassign'")
    op.execute(
        """DO $$ BEGIN
            ALTER TABLE job_proposals DROP CONSTRAINT IF EXISTS ck_job_proposals_source;
            ALTER TABLE job_proposals ADD CONSTRAINT ck_job_proposals_source CHECK (
                source IN ('full_base', 'new_cv', 'similar_projects',
                           'recommendation', 'marketplace'));
        END $$"""
    )
    op.execute("DROP TABLE IF EXISTS job_similar_links")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS champion_found_by")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS champion_found_at")
