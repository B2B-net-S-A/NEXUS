"""Indeksy po audycie 25.09.2026: follow-upy z kandydatem i retencja Jarvisa.

Revision ID: 0384_audit_indexes
Revises: 0383_legacy_interview_questions

`candidate_followups._WAITING_SQL` szuka wysłań CV od stałej daty
(`CANDIDATE_FOLLOWUP_SINCE`, 24.09.2026), więc okno rośnie bez końca, a
`GET /api/board-tasks` pyta o nie co 5 minut z każdej otwartej karty.
`candidate_stages` nie ma indeksu po `(stage, moved_at)` — częściowy indeks
na samych `cv_sent` jest mały i wystarcza temu zapytaniu.

`jarvis_retention` co godzinę kasuje `jarvis_ui_events` po `created_at`,
a jedyny indeks zaczyna się od `event` — bez osobnego indeksu DELETE skanuje
całą tabelę (retencja 90 dni).

Lustro w `entrypoint.sh` (`_INDEX_STATEMENTS`) — prod alembic bywa osierocony.
"""

from alembic import op

revision = "0384_audit_indexes"
down_revision = "0383_legacy_interview_questions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CONCURRENTLY: `candidate_stages` to gorąca tabela (każdy ruch w pipeline).
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_candidate_stages_cv_sent_moved_at "
            "ON candidate_stages (moved_at) WHERE stage = 'cv_sent'"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_jarvis_ui_events_created_at "
            "ON jarvis_ui_events (created_at)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_jarvis_ui_events_created_at")
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_candidate_stages_cv_sent_moved_at"
        )
