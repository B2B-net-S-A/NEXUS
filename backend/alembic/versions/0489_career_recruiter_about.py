"""Strona kariery: „O mnie” rekrutera na stałym linku (20.10.2026).

Revision ID: 0489_career_recruiter_about
Revises: 0488_debrief_from_text

``candidate_invite_links.about`` — najwyżej dwa zdania (do 280 znaków), które
rekruter wpisuje w NEXUSIE („Mój link ogólny”) i które strona
``kariera.b2bnetwork.pl/<slug>`` pokazuje pod imieniem. Tylko na linku
``kind='recruiter'``; zapis przechodzi kontrolę strony kariery
(``api/career_links.py``). Kolumna na linku, nie na ``users``: tekst należy do
publicznej strony — zmiana adresu i odwołanie z odzyskaniem zostawiają ten sam
wiersz, a tabela kont nie dostaje pola, które czyta tylko strona kariery.

Lustro w ``entrypoint.sh`` — pilnuje ``tests/test_career_migration_mirror.py``.
"""

from alembic import op

revision = "0489_career_recruiter_about"
down_revision = "0488_debrief_from_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE candidate_invite_links "
        "ADD COLUMN IF NOT EXISTS about VARCHAR(300) NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE candidate_invite_links DROP COLUMN IF EXISTS about")
