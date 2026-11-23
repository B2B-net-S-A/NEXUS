"""Formularz klienta wgrany z dysku i reguła „doświadczenie = 10/10” (CEZ).

Revision ID: 0756_client_form_upload_scale
Revises: 0755_contract_partner_reads

Prośba DL Centrum e-Zdrowia (20.11.2026), decyzje Artura 23.11.2026:
wypełniony poza NEXUSEM formularz (Word/PDF) albo tabela punktowa (Excel)
należy do pary osoba × rekrutacja (`candidate_client_forms.uploaded_*`),
a pola „w skali 1–10” dostają 10 przy doświadczeniu w wierszu
(`clients.client_form_scale_full_on_experience`, CEZ raz znacznikiem).
SQL i powód: ``app/services/client_form_schema.py``. Lustro w ``entrypoint.sh``.
Same dodania kolumn z NULL albo wartością domyślną: stary kod działa na nowym
schemacie.
"""

from alembic import op

from app.services import client_form_schema as schema

revision = "0756_client_form_upload_scale"
down_revision = "0755_contract_partner_reads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in schema.UPLOAD_SCALE_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in schema.UPLOAD_SCALE_DOWNGRADE_DDL:
        op.execute(statement)
