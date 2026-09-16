"""E-mail i telefon kandydata na kontrakcie (ticket: kontakt w widoku kontraktu).

Dwie kolumny NADPISUJĄCE, nie migawka całej prawdy: wartość trafia tu wyłącznie
wtedy, gdy przyszła z generatora umów B2B (``render_payload->>'partner_email'``
/ ``'partner_phone'``) albo gdy ktoś wpisał ją ręcznie w widoku kontraktu.
Pusta kolumna znaczy „weź z profilu kandydata" — dlatego wyczyszczenie pola
przywraca fallback, a nie zostawia dziury.

``VARCHAR(30)`` dla telefonu to lustro ``candidates.phone``; e-mail 255 jak
``contracts.client_pm_email``. Bez UNIQUE — to kontakt lokalny dla umowy, a nie
druga tożsamość kandydata (``candidates.email`` jest UNIQUE i tak ma zostać).

Przepisanie DANYCH (kontakt z generatora na istniejące kontrakty) robi
jednorazowa korekta w ``entrypoint.sh``
(``app/services/contract_candidate_contact_backfill.py``), bo potrzebuje logiki
ORM i paragonu; ta migracja jest wyłącznie schematem.
Lustro DDL: ``entrypoint.sh`` (prod alembic bywa osierocony).
"""

from alembic import op

revision = "0318_contract_candidate_contact"
down_revision = "0317_pipeline_stage_posting"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("candidate_email", "VARCHAR(255)"),
    ("candidate_phone", "VARCHAR(30)"),
)


def upgrade():
    for column, ddl_type in _COLUMNS:
        op.execute(
            f"ALTER TABLE contracts ADD COLUMN IF NOT EXISTS {column} {ddl_type}"
        )


def downgrade():
    for column, _ in _COLUMNS:
        op.execute(f"ALTER TABLE contracts DROP COLUMN IF EXISTS {column}")
