"""Osoby dodane z pulpitu dostają trwały wpis w zespole rekrutacji (12.10.2026).

Revision ID: 0429_recruiter_member_backfill
Revises: 0428_job_files

Osoba dodana do requestu z pulpitu „Requesty i obłożenie” miała samo
przypisanie (``job_work_assignments``), które automat zwalnia, gdy request
wychodzi z „Szukamy” — znikała wtedy z filtra „Rekruter”, choć prowadzący
i osoby dopisane w panelu „Zespół” zostawały. Od tej zmiany każde ręczne
dopisanie zakłada też wiersz ``job_collaborators`` (``source = 'manual'``,
``job_team.add_manual_member``).

Jednorazowo (znacznik w ``app_settings``) ten sam wiersz dostają osoby, które
już mają aktywne ręczne przypisanie i nie są prowadzącym. Wiersz ``auto_cc``
(cała kategoria) albo zdjęty wcześniej staje się ręczny. Przypisań automatu
nie ruszamy — te automat zwalnia za urlop.

Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony) — pilnuje
``test_recruiter_member_backfill.py``.
"""

from alembic import op

revision = "0429_recruiter_member_backfill"
down_revision = "0428_job_files"
branch_labels = None
depends_on = None

BACKFILL = """
    WITH marker AS (
        INSERT INTO app_settings (key, value)
        VALUES ('0429_recruiter_member_backfill', 'true'::jsonb)
        ON CONFLICT (key) DO NOTHING
        RETURNING key
    )
    INSERT INTO job_collaborators (job_id, user_id, added_by, source)
    SELECT a.job_id, a.user_id, a.assigned_by, 'manual'::jobcollaboratorsource
      FROM job_work_assignments a
      JOIN jobs j ON j.id = a.job_id
      JOIN users u ON u.id = a.user_id AND u.is_active
     WHERE a.state = 'active'
       AND a.source = 'manual'
       AND j.recruiter_id IS DISTINCT FROM a.user_id
       AND EXISTS (SELECT 1 FROM marker)
    ON CONFLICT (job_id, user_id) DO UPDATE
       SET source = 'manual'::jobcollaboratorsource,
           removed_from_auto_cc = false,
           removed_at = NULL,
           added_by = EXCLUDED.added_by
     WHERE job_collaborators.source <> 'manual'::jobcollaboratorsource
        OR job_collaborators.removed_from_auto_cc
"""


def upgrade() -> None:
    op.execute(BACKFILL)


def downgrade() -> None:
    # Wierszy nie da się odróżnić od dopisanych ręcznie po wdrożeniu — zostają.
    op.execute("DELETE FROM app_settings WHERE key = '0429_recruiter_member_backfill'")
