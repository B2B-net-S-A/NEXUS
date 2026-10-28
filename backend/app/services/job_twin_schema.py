"""DDL bliźniaczych rekrutacji (0614) — jedno źródło dla migracji i entrypointu.

Decyzje Artura z 28.10.2026 (makiety https://claude.ai/artifact/83ybsjjmstNhKAzHYNraFw):
bliźniak to rodzaj połączenia w istniejącej ``job_similar_links``
(``kind = 'twin'``), z parami pytań screeningowych potwierdzonymi przy
łączeniu. Pary, które Head of Recruitment odrzucił („To nie bliźniak”),
leżą w ``job_twin_dismissals`` i nie wracają na listę propozycji.

Lustro 1:1 w ``entrypoint.sh`` — pilnuje ``test_job_twins.py``.
"""

ENUM_DDL = "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'job_twin_linked'"

COLUMN_DDL = (
    "ALTER TABLE job_similar_links "
    "ADD COLUMN IF NOT EXISTS kind VARCHAR(16) NOT NULL DEFAULT 'similar'",
    "ALTER TABLE job_similar_links ADD COLUMN IF NOT EXISTS question_pairs JSONB NULL",
    """DO $$ BEGIN
        ALTER TABLE job_similar_links
            ADD CONSTRAINT ck_job_similar_links_kind
            CHECK (kind IN ('similar', 'twin'));
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    "CREATE INDEX IF NOT EXISTS ix_job_similar_links_twins "
    "ON job_similar_links (job_id) WHERE kind = 'twin'",
)

DISMISSALS_DDL = (
    """CREATE TABLE IF NOT EXISTS job_twin_dismissals (
        id BIGSERIAL PRIMARY KEY,
        job_low_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        job_high_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        dismissed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_job_twin_dismissals_pair UNIQUE (job_low_id, job_high_id),
        CONSTRAINT ck_job_twin_dismissals_order CHECK (job_low_id < job_high_id)
    )""",
)

ALL_DDL = (*COLUMN_DDL, *DISMISSALS_DDL)
