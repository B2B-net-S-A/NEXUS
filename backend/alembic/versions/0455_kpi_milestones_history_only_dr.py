"""Statystyki sprzed 12.10.2026 wyłącznie z DynaReportera — także przed 2026.

Revision ID: 0455_kpi_milestones_history_only_dr
Revises: 0454_kpi_milestones_dynareporter

Decyzja Artura 18.10.2026: zespół używa NEXUS-a od 12.10.2026, więc ruchy
Tablicy sprzed tego dnia (import z Traffita) nie trafiają do statystyk w ogóle.
0454 zostawiało je przed 2026. Teraz widok ``analytics_kpi_milestones``:

* ruchy Tablicy — tylko od 12.10.2026 (``nexus``),
* 1.01–11.10.2026 — tygodniowe wpisy rekruterów (``dynareporter``, jak w 0454),
* przed 2026 — placementy firmy z miesięcznego raportu Rady DynaReportera
  (``dr_board_monthly_report``, ``dynareporter_board``): bez osoby, kandydata
  i rekrutacji, dzień = pierwszy dzień miesiąca. Weryfikacji, rekomendacji
  i rozmów sprzed 2026 DynaReporter nie prowadził — ich nie ma („brak danych”).

Lustro w ``entrypoint.sh`` stoi po lustrze 0454 (ostatnie wygrywa). Pilnuje
``tests/test_kpi_milestones_dynareporter.py``.
"""

from alembic import op

revision = "0455_kpi_milestones_history_only_dr"
down_revision = "0454_kpi_milestones_dynareporter"
branch_labels = None
depends_on = None

CREATE_VIEW = """CREATE OR REPLACE VIEW analytics_kpi_milestones AS
        SELECT
            afm.candidate_id,
            afm.job_id,
            afm.stage,
            afm.first_reached_at,
            afm.first_moved_by,
            afm.candidate_stage_id,
            'nexus'::text AS source
        FROM analytics_first_milestones afm
        WHERE afm.first_reached_at
                >= (TIMESTAMP '2026-10-12 00:00' AT TIME ZONE 'Europe/Warsaw')
        UNION ALL
        SELECT
            NULL::integer AS candidate_id,
            NULL::integer AS job_id,
            counted.stage::pipelinestage AS stage,
            (k.report_date + TIME '12:00') AT TIME ZONE 'Europe/Warsaw'
                AS first_reached_at,
            k.user_id AS first_moved_by,
            NULL::integer AS candidate_stage_id,
            'dynareporter'::text AS source
        FROM dr_kpi_body_leasing k
        CROSS JOIN LATERAL (
            VALUES
                ('verified', k.verifications),
                ('cv_sent', k.recommendations),
                ('client_interview', k.interviews),
                ('hired', k.placements)
        ) AS counted (stage, n)
        CROSS JOIN LATERAL generate_series(1, GREATEST(COALESCE(counted.n, 0), 0))
        WHERE k.is_draft IS FALSE
          AND k.report_date >= DATE '2026-01-01'
          AND k.report_date < DATE '2026-10-12'
        UNION ALL
        SELECT
            NULL::integer AS candidate_id,
            NULL::integer AS job_id,
            'hired'::pipelinestage AS stage,
            (b.report_month + TIME '12:00') AT TIME ZONE 'Europe/Warsaw'
                AS first_reached_at,
            NULL::integer AS first_moved_by,
            NULL::integer AS candidate_stage_id,
            'dynareporter_board'::text AS source
        FROM dr_board_monthly_report b
        CROSS JOIN LATERAL generate_series(1, GREATEST(COALESCE(b.placements, 0), 0))
        WHERE b.report_month < DATE '2026-01-01'"""

# Widok sprzed tej rewizji — downgrade wraca do 0454.
PREVIOUS_VIEW_REVISION = "0454_kpi_milestones_dynareporter"


def upgrade() -> None:
    op.execute(CREATE_VIEW)


def downgrade() -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).with_name(f"{PREVIOUS_VIEW_REVISION}.py")
    spec = importlib.util.spec_from_file_location("m0454", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    op.execute(module.CREATE_VIEW)
