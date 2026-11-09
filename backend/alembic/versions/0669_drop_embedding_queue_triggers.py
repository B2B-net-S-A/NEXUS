"""Zdejmuje triggery martwej kolejki ``embedding_index_queue``.

Revision ID: 0669_drop_embedding_queue_trg
Revises: 0668_cortex_first_seen_not_null

Kolejka powstała w 0165 (#701), a rewert #713 usunął migrację, nie obiekty:
triggery zostały w bazie, choć nic ich nie czyta ani nie definiuje. Decyzja
Artura z 08.11.2026: tabela i funkcja zostają, bo DROP tabeli cofa tylko
backup, a triggery odtwarza downgrade.

Lustro w ``entrypoint.sh`` zdejmuje je przy każdym starcie, więc po samym
downgradzie następny start skasuje je ponownie. Trwałe cofnięcie wymaga też
usunięcia kroku ``embedding-queue-triggers`` z entrypointu.
"""

from alembic import op

revision = "0669_drop_embedding_queue_trg"
down_revision = "0668_cortex_first_seen_not_null"
branch_labels = None
depends_on = None

DROP_TRIGGERS = (
    "DROP TRIGGER IF EXISTS trg_candidates_embedding_index ON candidates",
    "DROP TRIGGER IF EXISTS trg_jobs_embedding_index ON jobs",
)

_CREATE_CANDIDATES = (
    "CREATE TRIGGER trg_candidates_embedding_index "
    "AFTER INSERT OR DELETE OR UPDATE OF name, lastname, competence_category, "
    "competence_category_id, years_it_experience, skills, verified_tech, "
    "experience, tags, preferences, ai_summary, raw_cv_text, languages "
    "ON public.candidates FOR EACH ROW "
    "EXECUTE FUNCTION nexus_enqueue_embedding_index('candidate')"
)
_CREATE_JOBS = (
    "CREATE TRIGGER trg_jobs_embedding_index "
    "AFTER INSERT OR DELETE OR UPDATE OF title, description, requirements, "
    "seniority, subcategory, industry, train_name, champion_profile, "
    "must_skills, nice_skills, competence_category_id, work_mode "
    "ON public.jobs FOR EACH ROW "
    "EXECUTE FUNCTION nexus_enqueue_embedding_index('job')"
)


def _recreate_if_possible(drop: str, create: str) -> str:
    """Czysta baza nie ma funkcji ani tabeli z usuniętej 0165, więc nic nie robi."""
    return f"""
        DO $$
        BEGIN
            IF to_regprocedure('public.nexus_enqueue_embedding_index()') IS NOT NULL
               AND to_regclass('public.embedding_index_queue') IS NOT NULL THEN
                {drop};
                {create};
            END IF;
        END $$
    """


def upgrade() -> None:
    for statement in DROP_TRIGGERS:
        op.execute(statement)


def downgrade() -> None:
    op.execute(_recreate_if_possible(DROP_TRIGGERS[0], _CREATE_CANDIDATES))
    op.execute(_recreate_if_possible(DROP_TRIGGERS[1], _CREATE_JOBS))
