"""Merge two 0080 heads: Autenti signatures + candidates.cv_storage_key.

Revision ID: 0081_merge_autenti_cv_storage
Revises: 0080_autenti_signatures, 0080_candidates_cv_storage_key
Create Date: 2026-05-07 15:00:00.000000

Po feature merges PR #102 (Autenti) i audit-2026-05-07 round 2 (CV
storage migration) w main wylądowały dwie migracje 0080 z tym samym
``down_revision = 0079_candidate_documents_storage_key``. Coolify
entrypoint używa ``alembic upgrade heads`` (plural) więc obie
zostały zastosowane na prod, ale ``alembic heads`` zwracał teraz
2 heads — przyszłe migracje wymagają explicit single-head parent.

Ta migracja jest **no-op merge** — łączy dwa heads w jeden punkt.
Bez DDL changes; tylko porządki w drzewie revision.

Single-head invariant zachowany (project_alembic_state memory).
"""

revision = "0081_merge_autenti_cv_storage"
down_revision = ("0080_autenti_signatures", "0080_candidates_cv_storage_key")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
