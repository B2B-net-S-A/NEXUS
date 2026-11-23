"""Sesje zdalnego podpisu kwalifikowanego przez API CSC (E1).

Revision ID: 0759_b2b_esign_remote_sessions
Revises: 0758_b2b_mass_send

Kierunek K1 Artura z 22.11.2026: NEXUS zostaje przy swoich ekranach podpisu,
a od dostawcy usług zaufania bierze tylko potwierdzenie tożsamości, certyfikat
i podpis skrótu (API Cloud Signature Consortium). Tabela trzyma sesję jednego
zatwierdzenia (``state`` OAuth jako skrót, ważna 15 minut, jednorazowa).
SQL w ``app/services/b2b_esign/remote_schema.py`` (lustro w ``entrypoint.sh``).
Sama nowa tabela: stary kod działa na nowym schemacie.
"""

from alembic import op

from app.services.b2b_esign.remote_schema import TABLE_DDL

revision = "0759_b2b_esign_remote_sessions"
down_revision = "0758_b2b_mass_send"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in TABLE_DDL:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS b2b_esign_remote_sessions")
