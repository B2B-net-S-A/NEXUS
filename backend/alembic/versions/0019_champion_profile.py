"""Phase 10: Champion Profile + recruiter screening answers

Revision ID: 0019
Revises: 0018
Create Date: 2026-04-17 14:30:00.000000

Adds two JSONB buckets:

1. `jobs.champion_profile` — the Delivery Lead fills this once per recruitment.
   Mirrors the internal "Profil Championa" Word template: project context,
   screening questions with ideal answers + deal-breakers, sourcing strategy.

   Shape:
   {
     "basics": {
       "onsite_days_per_week": int|null,
       "candidate_location_pref": str|null,
       "language": str|null
     },
     "project_context": {
       "about": str, "responsibilities": str, "selling_points": str
     },
     "screening_questions": [
       {"id": "q1", "question": str, "ideal_answer": str, "deal_breaker": str}
     ],
     "historical_client_questions": str,
     "internal_consultant_insight": str,
     "sourcing": {
       "sources": ["internal_base","linkedin","ad","referrals","other"],
       "keywords": str,
       "target_companies": str,
       "notes": str
     }
   }

2. `candidate_stages.screening_answers` — recruiter-captured responses. This
   column *already exists* from Phase 3 (scorecard_answers); we re-use its
   shape and add a separate field to avoid colliding with the stage scorecard
   feature.

   Shape:
   {
     "answered_at": iso8601,
     "answered_by": user_id,
     "answers": [
       {"question_id": "q1", "response": str, "deal_breaker_hit": bool}
     ],
     "overall_fit": "fit|uncertain|miss",
     "notes": str
   }
"""

from alembic import op
import sqlalchemy as sa


revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001_initial's Base.metadata.create_all may have already produced these
    # columns on a fresh CI DB. Keep the migration idempotent.
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS champion_profile JSONB")
    op.execute(
        "ALTER TABLE candidate_stages ADD COLUMN IF NOT EXISTS screening_answers JSONB"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_stages_has_screening "
        "ON candidate_stages ((screening_answers IS NOT NULL)) "
        "WHERE screening_answers IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_candidate_stages_has_screening")
    op.execute("ALTER TABLE candidate_stages DROP COLUMN IF EXISTS screening_answers")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS champion_profile")
