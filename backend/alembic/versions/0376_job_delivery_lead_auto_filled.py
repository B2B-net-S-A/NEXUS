"""DL rekrutacji wpisany automatycznie idzie za głównym DL-em klienta (audyt 24.09.2026).

Revision ID: 0376_job_delivery_lead_auto_filled
Revises: 0375_md_import_row_overflow

``job_delivery_lead_fill`` (#1783) wpisał głównego DL-a klienta w ~270 otwartych
rekrutacji. Reguła „nigdy nadpis” sprawiła, że przy zmianie głównego DL-a
klienta te rekrutacje zostawały przy poprzednim: nowy DL nie widział przeglądu
DL, a gdy stary odszedł (konto nieaktywne), przegląd i alerty DL trafiały
donikąd. Znacznik ``delivery_lead_auto_filled`` mówi, że DL wpisał automat —
takie wiersze idą za zmianą głównego DL-a; ręczna zmiana w rekrutacji go
zeruje i od tej chwili DL jest nietykalny.

Jednorazowo (znacznik w ``app_settings``) otwarte rekrutacje, których DL jest
dziś głównym DL-em klienta, dostają ``true`` — tak wyglądają rekrutacje
uzupełnione 24.09 (i założone z głównym DL-em przez ``resolve_default_owners``).

Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony) — pilnuje
``test_job_delivery_lead_auto_filled.py``.
"""

from alembic import op

revision = "0376_job_delivery_lead_auto_filled"
down_revision = "0375_md_import_row_overflow"
branch_labels = None
depends_on = None

ADD_COLUMN = (
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS delivery_lead_auto_filled "
    "BOOLEAN NOT NULL DEFAULT false"
)

BACKFILL = """
    WITH marker AS (
        INSERT INTO app_settings (key, value)
        VALUES ('0376_job_delivery_lead_auto_filled', 'true'::jsonb)
        ON CONFLICT (key) DO NOTHING
        RETURNING key
    ), heads AS (
        SELECT DISTINCT ON (a.client_id) a.client_id, a.delivery_lead_user_id AS dl_id
          FROM delivery_lead_client_assignments a
          JOIN users u ON u.id = a.delivery_lead_user_id AND u.is_active
         WHERE a.is_head
         ORDER BY a.client_id, a.id
    )
    UPDATE jobs j SET delivery_lead_auto_filled = true
      FROM heads h
     WHERE j.client_id = h.client_id
       AND j.delivery_lead_id = h.dl_id
       AND j.status IN ('draft', 'published')
       AND NOT j.delivery_lead_auto_filled
       AND EXISTS (SELECT 1 FROM marker)
"""


def upgrade() -> None:
    op.execute(ADD_COLUMN)
    op.execute(BACKFILL)


def downgrade() -> None:
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS delivery_lead_auto_filled")
    op.execute(
        "DELETE FROM app_settings WHERE key = '0376_job_delivery_lead_auto_filled'"
    )
