"""Faza A: promote Traffit notes z `activities` do `notes` table (dual-source).

Revision ID: 0077_promote_traffit_notes
Revises: 0076_traffit_phase_a
Create Date: 2026-05-05 14:30:00.000000

Po imporcie 343k aktywności w Faza 5b, 36k z nich to `traffit:Notatka`,
4k to `traffit:Email`, 2k `traffit:Reply`, 300 rozmów, 6 spotkań — łącznie
~43k notatek z pełnym contentem w `activities.details`.

Notatki istniejące w activities zostają (timeline/audit log), a tu
kopiujemy je też do dedykowanej tabeli `notes` żeby zakładka "Notatki"
w UI (`CandidateDetailV2.tsx > NotatkiTab`) je zobaczyła. Frontend już
czyta z `notes` table — bez zmian po migracji.

Idempotent: NOT EXISTS check on (candidate_id, created_at).

UWAGA: powinno być uruchomione **PO** A4 re-run activities (żeby author_id
był poprawny — re-run aktualizuje `activities.user_id` z większego
user_id_map po imporcie 131 brakujących userów).
"""

from alembic import op
import sqlalchemy as sa

revision = "0077_promote_traffit_notes"
down_revision = "0076_traffit_phase_a"
branch_labels = None
depends_on = None


PROMOTE_SQL = """
INSERT INTO notes (
    candidate_id, content, note_type, author_id,
    created_at, updated_at
)
SELECT
    a.entity_id,
    -- Niektóre Traffit Notatki mają nested {content: {content: "<html>"}};
    -- inne mają content jako plain string. COALESCE pokrywa oba przypadki.
    LEFT(
        COALESCE(
            a.details #>> '{content,content}',
            a.details ->> 'content',
            ''
        ),
        50000  -- guard against absurdly large notes (PG TEXT no limit but UI cap)
    ),
    CASE
        WHEN a.action = 'traffit:Email' THEN 'email'::notetype
        WHEN a.action = 'traffit:Reply' THEN 'email'::notetype
        WHEN a.action = 'traffit:Rozmowa telefoniczna' THEN 'call'::notetype
        WHEN a.action = 'traffit:Spotkanie' THEN 'meeting'::notetype
        WHEN a.details ->> 'traffit_type_value' ILIKE '%interview%' THEN 'interview'::notetype
        ELSE 'general'::notetype
    END,
    a.user_id,
    a.created_at,
    a.updated_at
FROM activities a
WHERE a.external_source = 'traffit'
  AND a.action IN (
      'traffit:Notatka',
      'traffit:Email',
      'traffit:Reply',
      'traffit:Rozmowa telefoniczna',
      'traffit:Spotkanie'
  )
  AND a.entity_type = 'candidate'
  AND a.entity_id IS NOT NULL
  -- Skip empty notes (some Traffit records have NULL content)
  AND COALESCE(
      a.details #>> '{content,content}',
      a.details ->> 'content',
      ''
  ) <> ''
  -- Idempotent: skipuje już istniejące notatki o tym samym candidate+timestamp
  AND NOT EXISTS (
      SELECT 1 FROM notes n
      WHERE n.candidate_id = a.entity_id
        AND n.created_at = a.created_at
  );
"""


def upgrade() -> None:
    op.execute(sa.text(PROMOTE_SQL))


def downgrade() -> None:
    # Cofa tylko notatki które przyszły z tego promote (po created_at < migration date,
    # a author_id w 131 imported userów lub NULL i content matched activities).
    # Bezpieczniejsza alternatywa: oznaczyć w migracji 0076 nową kolumną
    # `notes.imported_from_activity_id`. Tutaj zostawiam no-op żeby nie
    # przypadkiem usunąć notatki ręcznie dodane na prodzie.
    pass
