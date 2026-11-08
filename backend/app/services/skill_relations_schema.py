"""Powiązania haseł słownika umiejętności — SQL migracji 0660 i lustra w ``entrypoint.sh``.

JEDNO źródło instrukcji dla ``alembic/versions/0660_skill_relations.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony). Model:
``app.models.skill_relation``.
"""

from __future__ import annotations

TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS skill_relations ("
    "id SERIAL PRIMARY KEY, "
    "from_skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE, "
    "to_skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE, "
    "kind VARCHAR(12) NOT NULL, "
    "status VARCHAR(10) NOT NULL DEFAULT 'proposed', "
    "source VARCHAR(10) NOT NULL DEFAULT 'data', "
    "support INTEGER NOT NULL DEFAULT 0, "
    "share NUMERIC(5, 4) NULL, "
    "reason TEXT NULL, "
    "model VARCHAR(80) NULL, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "curated_by VARCHAR(255) NULL, "
    "curated_at TIMESTAMPTZ NULL, "
    "CONSTRAINT uq_skill_relations_pair UNIQUE (from_skill_id, to_skill_id, kind), "
    "CONSTRAINT ck_skill_relations_not_self CHECK (from_skill_id <> to_skill_id), "
    "CONSTRAINT ck_skill_relations_kind CHECK "
    "(kind IN ('implies', 'part_of', 'alternative', 'typical')), "
    "CONSTRAINT ck_skill_relations_status CHECK "
    "(status IN ('proposed', 'accepted', 'rejected')), "
    "CONSTRAINT ck_skill_relations_source CHECK "
    "(source IN ('data', 'glossary', 'model', 'manual'))"
    ")",
    "CREATE INDEX IF NOT EXISTS ix_skill_relations_status "
    "ON skill_relations (status, kind)",
)

DOWNGRADE_DDL = ("DROP TABLE IF EXISTS skill_relations",)
