"""Karta rekomendacji: tabela `recommendation_cards` i odcisk notatki.

Revision ID: 0413_recommendation_cards
Revises: 0412_note_kind

Rekruterzy piszą kartę rekomendacji jako wolny tekst w notatce (ok. 640
miesięcznie, głównie w Traffit). Od tej migracji karta jest danymi: jedna na
parę (kandydat, rekrutacja), składana z notatek i z pól wpisanych w NEXUSIE.
Import z notatek stoi za flagą ``RECOMMENDATION_CARD_IMPORT_ENABLED``
(domyślnie wyłączona) — sama migracja niczego nie przelicza.

SQL ma jedno źródło (``app/services/recommendation_card_schema.py``) — to samo
czyta lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services import recommendation_card_schema as schema

revision = "0413_recommendation_cards"
down_revision = "0412_note_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(schema.TABLE_DDL)
    for stmt in schema.COLUMN_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # Pola wpisane ręcznie żyją tylko w tej tabeli — nie kasujemy ich po cichu.
    bind = op.get_bind()
    manual = bind.exec_driver_sql(
        "SELECT count(*) FROM recommendation_cards WHERE fields_manual <> '{}'::jsonb"
    ).scalar()
    if manual:
        raise RuntimeError(
            f"recommendation_cards ma {manual} kart z polami wpisanymi ręcznie — "
            "downgrade skasowałby je bez śladu."
        )
    op.execute("DROP INDEX IF EXISTS ix_notes_card_kinds")
    op.execute("ALTER TABLE notes DROP COLUMN IF EXISTS card_parsed_hash")
    op.execute("DROP TABLE IF EXISTS recommendation_cards")
