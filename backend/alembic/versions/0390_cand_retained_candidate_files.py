"""Pliki CV usuniętych kandydatów zostają — rejestr kluczy (runda 9, R9-N7-12).

Revision ID: 0390_cand_retained_candidate_files
Revises: 0388_purged_candidates

Twarde usunięcie kandydata kaskadą kasowało CV trzymane w bazie (BYTEA), a
pliki w magazynie obiektów zostawały bez wskaźnika. Decyzja Artura 26.09.2026:
„nie usuwać nigdy żadnych CV”. Handler przenosi bajty do magazynu obiektów
i zapisuje tu każdy klucz pliku tej osoby — pod pseudonimem, bez id i nazwiska.
Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony) — pilnuje
``tests/test_retained_candidate_files_mirror.py``.
"""

from alembic import op

revision = "0390_cand_retained_candidate_files"
down_revision = "0388_purged_candidates"
branch_labels = None
depends_on = None

CREATE_RETAINED_CANDIDATE_FILES = """CREATE TABLE IF NOT EXISTS retained_candidate_files (
    id BIGSERIAL PRIMARY KEY,
    subject_ref VARCHAR(64) NOT NULL,
    source VARCHAR(40) NOT NULL,
    storage_key VARCHAR(512) NOT NULL,
    content_type VARCHAR(100) NULL,
    size_bytes BIGINT NULL,
    content_sha256 VARCHAR(64) NULL,
    retained_at TIMESTAMPTZ NOT NULL DEFAULT now()
)"""

CREATE_SUBJECT_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_retained_candidate_files_subject_ref "
    "ON retained_candidate_files (subject_ref)"
)

DDL_STATEMENTS = [CREATE_RETAINED_CANDIDATE_FILES, CREATE_SUBJECT_INDEX]


def upgrade() -> None:
    for statement in DDL_STATEMENTS:
        op.execute(statement)


# Jedyny wskaźnik do zachowanych CV — downgrade nie może go skasować po cichu.
REFUSE_WITH_ROWS = """DO $$
BEGIN
    IF to_regclass('retained_candidate_files') IS NOT NULL THEN
        IF EXISTS (SELECT 1 FROM retained_candidate_files) THEN
            RAISE EXCEPTION 'Downgrade 0390 odmawia: retained_candidate_files wskazuje zachowane CV usuniętych kandydatów. Zostaw tę rewizję albo przenieś wpisy ręcznie.';
        END IF;
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_ROWS)
    op.execute("DROP TABLE IF EXISTS retained_candidate_files")
