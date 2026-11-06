"""Propozycje do słownika umiejętności — SQL migracji 0658 i lustra w ``entrypoint.sh``.

JEDNO źródło instrukcji dla ``alembic/versions/0658_skill_proposals.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony). Model:
``app.models.skill_proposal``.
"""

from __future__ import annotations

TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS skill_proposals ("
    "id SERIAL PRIMARY KEY, "
    "family_key VARCHAR(200) NOT NULL, "
    "display_name VARCHAR(200) NOT NULL, "
    "names JSONB NOT NULL DEFAULT '[]'::jsonb, "
    "cand_count INTEGER NOT NULL DEFAULT 0, "
    "cv_count INTEGER NOT NULL DEFAULT 0, "
    "job_count INTEGER NOT NULL DEFAULT 0, "
    "weight INTEGER NOT NULL DEFAULT 0, "
    "decision VARCHAR(10) NULL, "
    "canonical VARCHAR(200) NULL, "
    "target_skill_id INTEGER NULL REFERENCES skills(id) ON DELETE SET NULL, "
    "category VARCHAR(64) NULL, "
    "replacements JSONB NOT NULL DEFAULT '[]'::jsonb, "
    "confidence VARCHAR(4) NULL, "
    "review_note TEXT NULL, "
    "status VARCHAR(10) NOT NULL DEFAULT 'open', "
    "model VARCHAR(80) NULL, "
    "computed_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "classified_at TIMESTAMPTZ NULL, "
    "curated_by VARCHAR(255) NULL, "
    "curated_at TIMESTAMPTZ NULL, "
    "CONSTRAINT uq_skill_proposals_family_key UNIQUE (family_key), "
    "CONSTRAINT ck_skill_proposals_status CHECK (status IN ('open', 'accepted', 'rejected')), "
    "CONSTRAINT ck_skill_proposals_decision CHECK (decision IS NULL OR decision IN "
    "('new', 'alias', 'generic', 'soft', 'noise')), "
    "CONSTRAINT ck_skill_proposals_confidence CHECK (confidence IS NULL OR confidence IN "
    "('high', 'low'))"
    ")",
    "CREATE INDEX IF NOT EXISTS ix_skill_proposals_status_weight "
    "ON skill_proposals (status, weight DESC)",
)

DOWNGRADE_DDL = ("DROP TABLE IF EXISTS skill_proposals",)
