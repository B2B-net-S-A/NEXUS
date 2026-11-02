"""Dzienne wejścia na linki aplikacyjne: SQL migracji ``0637_invite_link_visit_days``.

JEDNO źródło instrukcji dla migracji i ``entrypoint.sh``; każda instrukcja
idempotentna. Decyzja Artura 02.11.2026: do tej pory link miał tylko licznik od
początku (``visit_count``), więc konwersji wejście → zgłoszenie w okresie nie dało
się policzyć. Liczby dzienne są dopiero od dnia wdrożenia, wstecz ich nie ma.
"""

TABLE_DDL = [
    """
    CREATE TABLE IF NOT EXISTS candidate_invite_link_visit_days (
        link_token TEXT NOT NULL
            REFERENCES candidate_invite_links (token) ON DELETE CASCADE,
        day DATE NOT NULL,
        visits INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (link_token, day)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_candidate_invite_link_visit_days_day
        ON candidate_invite_link_visit_days (day)
    """,
]
