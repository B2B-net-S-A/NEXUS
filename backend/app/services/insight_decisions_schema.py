"""DDL decyzji z zakładki „Wnioski” (0647) — jedno źródło dla migracji i entrypointu.

Wiersz na każde kliknięcie, nic się nie nadpisuje: stan sprawy to ostatni wiersz, a
historia zostaje. Patrz ``docs/claude/finanse-insights/zakladka-wnioski.md``.

Lustro 1:1 w ``entrypoint.sh`` — pilnuje ``test_insights_wnioski.py``.
"""

TABLE_DDL = (
    """CREATE TABLE IF NOT EXISTS insight_decisions (
        id SERIAL PRIMARY KEY,
        insight_key VARCHAR(64) NOT NULL,
        state VARCHAR(16) NOT NULL CONSTRAINT ck_insight_decisions_state CHECK (state IN ('approved', 'later', 'rejected')),
        decided_by_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        count_at_decision INTEGER NOT NULL,
        number_at_decision VARCHAR(32) NOT NULL,
        return_on DATE NULL,
        review_on DATE NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_insight_decisions_key_at ON insight_decisions (insight_key, decided_at DESC, id DESC)",
)
