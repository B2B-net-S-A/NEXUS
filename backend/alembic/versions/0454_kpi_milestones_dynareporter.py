"""Statystyki 2026 sprzed NEXUS-a: kamienie milowe KPI z DynaReportera.

Revision ID: 0454_kpi_milestones_dynareporter
Revises: 0453_prep_candidate_responses

Decyzja Artura 17.10.2026: zespół klika w NEXUS-ie od 12.10.2026, a od 1.01
do 11.10.2026 wynik rekrutera to tygodniowy wpis w DynaReporterze (tabela
``dr_kpi_body_leasing``, rozliczona skryptem
``settle_competitions_from_dynareporter``). Statystyki liczone z historii
Traffita dawały w tych dniach więcej rekomendacji i inne osoby niż raport.

Widok ``analytics_kpi_milestones`` ma kolumny ``analytics_first_milestones``
plus ``source``:

* ruchy pipeline'u przed 1.01.2026 i od 12.10.2026 — bez zmian (``nexus``),
* 1.01–11.10.2026 — każdy licznik wpisu DynaReportera rozwinięty na tyle
  wierszy, ile wynosi (``dynareporter``), bez kandydata i rekrutacji; dzień
  wiersza to ``report_date`` (pierwszy dzień tygodnia w obrębie miesiąca),
  południe w Warszawie. Rozmowy z DynaReportera to rozmowy u klienta
  (``client_interview``); etapów ``interview`` i ``acceptance`` DynaReporter
  nie prowadził, więc w tych dniach ich nie ma.

Granice to fakty biznesowe, nie ustawienia — te same co
``app/services/competition_history.py`` (``DR_HISTORY_START``,
``RESULTS_CUTOVER``); pilnuje ``tests/test_kpi_milestones_dynareporter.py``.
Lustro w ``entrypoint.sh`` (alembic na produkcji bywa osierocony).
"""

from alembic import op

revision = "0454_kpi_milestones_dynareporter"
down_revision = "0453_prep_candidate_responses"
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
                < (TIMESTAMP '2026-01-01 00:00' AT TIME ZONE 'Europe/Warsaw')
           OR afm.first_reached_at
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
          AND k.report_date < DATE '2026-10-12'"""

DROP_VIEW = "DROP VIEW IF EXISTS analytics_kpi_milestones"


def upgrade() -> None:
    op.execute(CREATE_VIEW)


def downgrade() -> None:
    op.execute(DROP_VIEW)
