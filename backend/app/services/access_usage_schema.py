"""DDL licznika użycia obszarów (0630) — jedno źródło dla migracji i entrypointu.

Jeden wiersz na osobę × obszar × dzień. Bez treści, bez identyfikatorów rekordów
i bez parametrów zapytań, patrz ``docs/claude/uprawnienia/licznik-uzycia-obszarow.md``.

Lustro 1:1 w ``entrypoint.sh`` — pilnuje ``test_access_usage.py``.
"""

TABLE_DDL = (
    """CREATE TABLE IF NOT EXISTS access_usage_daily (
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        area VARCHAR(32) NOT NULL,
        day DATE NOT NULL,
        entries INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, area, day)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_access_usage_daily_day ON access_usage_daily (day)",
)
