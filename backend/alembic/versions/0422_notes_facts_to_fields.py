"""Dane z notatek do pól: wpis „X/Y” w „Stawce od” i języki z notatek.

Revision ID: 0422_notes_facts_to_fields
Revises: 0421_recommendation_card_assist

* Wyzwalacz ``trg_rate_from_notes`` — wpis Delivery Leada „X/Y” (stawka do
  klienta / oczekiwanie kandydata) jest obserwacją „Stawki od”, więc zmiana
  takiej notatki kolejkuje przeliczenie kandydata (także przy surowym SQL-u
  importu Traffita).
* ``ck_candidate_languages_provenance`` przyjmuje źródło ``notes``.
* Jednorazowo: kandydaci z istniejącymi wpisami „X/Y” do kolejki przeliczeń.

SQL ma jedno źródło (``app/services/notes_facts_schema.py``) — ten sam moduł
importuje ``entrypoint.sh``.
"""

from alembic import op

from app.services import notes_facts_schema as schema

revision = "0422_notes_facts_to_fields"
down_revision = "0421_recommendation_card_assist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    bind = op.get_bind()
    from_notes = bind.exec_driver_sql(
        "SELECT count(*) FROM candidate_languages WHERE provenance = 'notes'"
    ).scalar()
    if from_notes:
        raise RuntimeError(
            f"candidate_languages ma {from_notes} języków z notatek — węższy "
            "CHECK nie przyjąłby tych wierszy."
        )
    op.execute("DROP TRIGGER IF EXISTS trg_rate_from_notes ON notes")
    op.execute("DROP FUNCTION IF EXISTS trg_rate_from_notes()")
    op.execute(
        "ALTER TABLE candidate_languages DROP CONSTRAINT IF EXISTS "
        "ck_candidate_languages_provenance"
    )
    op.execute(
        "ALTER TABLE candidate_languages ADD CONSTRAINT "
        "ck_candidate_languages_provenance CHECK (provenance IN ('manual', 'cv', "
        "'traffit', 'talent_radar', 'tr_legacy', 'csv', 'legacy', 'unknown'))"
    )
