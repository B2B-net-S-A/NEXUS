"""Statystyki sprzed 2026 z wpisów rekruterów uzupełnionych ręcznie.

Revision ID: 0472_kpi_milestones_manual_fill
Revises: 0471_client_sales_invoices

Decyzja Artura 18.10.2026: czego DynaReporter nie prowadził, zespół uzupełnia
ręcznie (``scripts/import_dr_manual_fill.py``) w tych samych tabelach ``dr_*``.
0467 brało tygodnie rekruterów dopiero od 1.01.2026, więc wpis za 2025 nie
liczyłby się nigdzie. Teraz widok ``analytics_kpi_milestones``:

* ruchy Tablicy — tylko od 12.10.2026 (``nexus``), bez zmian;
* tygodnie rekruterów — każdy wpis sprzed 12.10.2026 (``dynareporter``);
* przed 2026 placementy firmy z raportu Rady (``dynareporter_board``) to już
  tylko RESZTA bez osoby: placementy Rady w miesiącu minus placementy z wpisów
  rekruterów tego miesiąca (nie mniej niż 0). Suma firmy zostaje taka jak
  w raporcie Rady, a wpisane osoby dostają swoje placementy — żaden placement
  nie liczy się dwa razy.

Bez ręcznych wpisów sprzed 2026 widok daje to samo co 0467. Lustro
w ``entrypoint.sh`` stoi po lustrze 0467 (ostatnie wygrywa). Pilnuje
``tests/test_kpi_milestones_dynareporter.py``.
"""

from alembic import op

revision = "0472_kpi_milestones_manual_fill"
down_revision = "0471_client_sales_invoices"
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
        CROSS JOIN LATERAL (
            SELECT COALESCE(sum(GREATEST(COALESCE(w.placements, 0), 0)), 0) AS n
            FROM dr_kpi_body_leasing w
            WHERE w.is_draft IS FALSE
              AND w.report_date >= b.report_month
              AND w.report_date < b.report_month + INTERVAL '1 month'
        ) AS entered
        CROSS JOIN LATERAL generate_series(
            1, GREATEST(COALESCE(b.placements, 0) - entered.n, 0)
        )
        WHERE b.report_month < DATE '2026-01-01'"""

PREVIOUS_VIEW_REVISION = "0467_kpi_milestones_history_only_dr"


def upgrade() -> None:
    op.execute(CREATE_VIEW)


def downgrade() -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).with_name(f"{PREVIOUS_VIEW_REVISION}.py")
    spec = importlib.util.spec_from_file_location("m0467", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    op.execute(module.CREATE_VIEW)
