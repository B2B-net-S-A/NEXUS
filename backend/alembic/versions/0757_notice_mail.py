"""Wypowiedzenia z poczty: propozycje z maili, nauczone adresy, archiwum administracja@.

Revision ID: 0757_notice_mail
Revises: 0756_client_form_upload_scale

Decyzje Artura 23.11.2026: czytnik spraw rozpoznaje wypowiedzenie, skrócenie
zamówienia przez klienta, zmianę daty i wycofanie, a karta w back office
proponuje komplet zmian do jednego „Potwierdź”. SQL
w ``app/services/notice_mail_schema.py`` (lustro w ``entrypoint.sh``).
Same nowe tabele: stary kod działa na nowym schemacie.
"""

from alembic import op

from app.services.notice_mail_schema import ALL_DDL, DROP_DDL

revision = "0757_notice_mail"
down_revision = "0756_client_form_upload_scale"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in ALL_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DROP_DDL:
        op.execute(statement)
