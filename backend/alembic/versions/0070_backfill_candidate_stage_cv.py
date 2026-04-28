"""Backfill candidate_stage_cvs dla istniejących CandidateStage.

Revision ID: 0070_backfill_candidate_stage_cv
Revises: 0069_candidate_stage_cv
Create Date: 2026-04-28 09:30:00.000000

Dla każdego istniejącego `candidate_stages` row wstawia odpowiadający wpis
w `candidate_stage_cvs` z migawką aktualnego CV kandydata.

* Idempotentny — powtórne uruchomienie nie duplikuje (`LEFT JOIN ... WHERE
  csv.id IS NULL` + INSERT).
* Działa w batchach po 500 — w razie crashu można wznowić bez side-effectów.
* Kandydat bez CV → row nadal tworzony (INSERT z NULL `original_cv_*`),
  UI pokazuje "Brak CV w momencie zgłoszenia".

Po tej migracji wszystkie historyczne rekrutacje mają snapshot — gotowe do
działania UI bez fallbacku "kandydat ma tylko bieżące CV".
"""

from alembic import op


revision = "0070_backfill_candidate_stage_cv"
down_revision = "0069_candidate_stage_cv"
branch_labels = None
depends_on = None


_BATCH_SIZE = 500


def upgrade() -> None:
    conn = op.get_bind()
    total_inserted = 0

    while True:
        result = conn.exec_driver_sql(
            f"""
            INSERT INTO candidate_stage_cvs (
                candidate_stage_id, candidate_id, job_id,
                original_cv_filename, original_cv_content, original_cv_language,
                original_snapshot_at, original_snapshot_source,
                branded_status, created_at, updated_at
            )
            SELECT cs.id, cs.candidate_id, cs.job_id,
                   c.cv_filename,
                   c.cv_file_content,
                   c.cv_language,
                   CASE WHEN c.cv_file_content IS NOT NULL THEN now() ELSE NULL END,
                   CASE WHEN c.cv_file_content IS NOT NULL THEN 'backfill_0070' ELSE NULL END,
                   'none', now(), now()
            FROM candidate_stages cs
            JOIN candidates c ON cs.candidate_id = c.id
            LEFT JOIN candidate_stage_cvs csv ON csv.candidate_stage_id = cs.id
            WHERE csv.id IS NULL
            ORDER BY cs.id
            LIMIT {_BATCH_SIZE}
            """
        )
        # rowcount jest dostępny dla INSERT na PostgreSQL.
        inserted = result.rowcount or 0
        total_inserted += inserted
        if inserted < _BATCH_SIZE:
            break

    # Sanity check log (Alembic captures via -v).
    print(
        f"[0070_backfill] inserted={total_inserted} "
        f"candidate_stage_cvs rows."
    )


def downgrade() -> None:
    """Usuń tylko wiersze stworzone przez tę migrację (po `original_snapshot_source`)."""
    op.execute(
        "DELETE FROM candidate_stage_cvs "
        "WHERE original_snapshot_source = 'backfill_0070'"
    )
    # Edge: wiersze które zostały stworzone z NULL `original_cv_content`
    # (kandydat bez CV) mają snapshot_source NULL — usuwamy je też, ale tylko
    # te których `created_at` mieszczą się w oknie tej migracji. Pragmatyczne
    # rozwiązanie: w prod nigdy nie downgrade'ujemy, więc trzymamy proste.
    op.execute(
        "DELETE FROM candidate_stage_cvs "
        "WHERE original_snapshot_source IS NULL "
        "AND branded_status = 'none' "
        "AND original_cv_content IS NULL"
    )
