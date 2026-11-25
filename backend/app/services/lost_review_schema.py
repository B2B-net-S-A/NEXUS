"""DDL modułu „Przegrane” w Insights (0783) — jedno źródło dla migracji i entrypointu.

- ``job_loss_reviews``: „Co zdecydowało?” i „Skąd wiesz?” przegranej rekrutacji
  (okno zamknięcia albo spotkanie z DL). Wiersz należy do jednego zamknięcia:
  ``closed_at`` to ``jobs.closed_at`` z chwili zapisu, więc po ponownym otwarciu
  i zamknięciu stary wybór przestaje się liczyć bez kasowania.
- ``lost_review_lessons``: „Co zmieniamy?” ze spotkania — dla rekrutacji, klienta
  albo wszystkich. Wniosek „ten klient” to zasada klienta.

Reguła: ``docs/claude/finanse-insights/przegrane-przeglad-z-dl.md``.
Lustro 1:1 w ``entrypoint.sh`` — pilnuje ``test_lost_review.py``.
"""

AI_FEATURE_KEY = "lost_review_summary"

TABLE_DDL = (
    """CREATE TABLE IF NOT EXISTS job_loss_reviews (
        job_id INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
        closed_at TIMESTAMPTZ NOT NULL,
        why VARCHAR(32)[] NOT NULL DEFAULT '{}',
        source VARCHAR(16) NULL CONSTRAINT ck_job_loss_reviews_source CHECK (source IN ('client', 'ours', 'unknown')),
        updated_by_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        ask_reminded_at TIMESTAMPTZ NULL
    )""",
    """CREATE TABLE IF NOT EXISTS lost_review_lessons (
        id SERIAL PRIMARY KEY,
        scope VARCHAR(16) NOT NULL CONSTRAINT ck_lost_review_lessons_scope CHECK (scope IN ('job', 'client', 'all')),
        client_id INTEGER NULL REFERENCES clients(id) ON DELETE CASCADE,
        job_id INTEGER NULL REFERENCES jobs(id) ON DELETE SET NULL,
        text VARCHAR(300) NOT NULL,
        created_by_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        archived_at TIMESTAMPTZ NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_lost_review_lessons_client ON lost_review_lessons (client_id, created_at DESC)",
)

AI_FEATURE_DDL = (
    "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
    f"SELECT '{AI_FEATURE_KEY}', TRUE, 0, now(), now() "
    "WHERE NOT EXISTS "
    f"(SELECT 1 FROM ai_features WHERE feature = '{AI_FEATURE_KEY}')",
)
