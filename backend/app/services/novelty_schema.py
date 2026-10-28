"""DDL „Nowości do przeklikania” (0614) — jedno źródło dla migracji i entrypointu.

Jeden wiersz na osobę × nowość: kiedy pierwszy raz zobaczyła kropkę, czy
zamknęła kartę, czy odłożyła okno zmiany procesu (raz) i czym zaliczyła
nowość — przeklikaniem (``tour``), użyciem w pracy (``used``) albo kliknięciem
drobiazgu (``dot``). Treść nowości żyje w ``app/data/novelties/novelties.json``,
więc ``novelty_id`` nie ma klucza obcego.

Lustro 1:1 w ``entrypoint.sh`` — pilnuje ``test_novelties.py``.
"""

COMPLETED_VIA = ("tour", "used", "dot")

TABLE_DDL = (
    """CREATE TABLE IF NOT EXISTS novelty_progress (
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        novelty_id VARCHAR(60) NOT NULL,
        first_seen_at TIMESTAMPTZ NULL,
        seen_count INTEGER NOT NULL DEFAULT 0,
        card_dismissed_at TIMESTAMPTZ NULL,
        postponed_until TIMESTAMPTZ NULL,
        completed_at TIMESTAMPTZ NULL,
        completed_via VARCHAR(10) NULL,
        reminded_at TIMESTAMPTZ NULL,
        reminded_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (user_id, novelty_id),
        CONSTRAINT ck_novelty_progress_completed_via CHECK (
            completed_via IS NULL OR completed_via IN ('tour', 'used', 'dot')
        )
    )""",
    "CREATE INDEX IF NOT EXISTS ix_novelty_progress_novelty "
    "ON novelty_progress (novelty_id)",
)
