"""DDL „Nowości do przeklikania” (0625) — jedno źródło dla migracji i entrypointu.

Jeden wiersz na osobę × nowość: kiedy pierwszy raz zobaczyła kropkę, czy
zamknęła kartę, czy odłożyła okno zmiany procesu (raz) i czym zaliczyła
nowość — przeklikaniem (``tour``), użyciem w pracy (``used``) albo kliknięciem
drobiazgu (``dot``). Treść nowości żyje w ``app/data/novelties/novelties.json``,
więc ``novelty_id`` nie ma klucza obcego.

Lustro 1:1 w ``entrypoint.sh`` — pilnuje ``test_novelties.py``
(``TABLE_DDL``) i ``test_novelty_lessons.py`` (``LESSON_DDL``).
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

# Lekcje nowości (0757, decyzje Artura 23.11.2026): postęp osoby w lekcji
# (pokaz → sam → pytanie) i stan porcji dnia (odłożenie, pominięcie przez
# admina). Treść lekcji w ``app/data/novelties/lessons.json``, więc
# ``lesson_id`` nie ma klucza obcego.
LESSON_DDL = (
    """CREATE TABLE IF NOT EXISTS novelty_lesson_progress (
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        lesson_id VARCHAR(60) NOT NULL,
        shown_count INTEGER NOT NULL DEFAULT 0,
        shown_at TIMESTAMPTZ NULL,
        solo_failed_count INTEGER NOT NULL DEFAULT 0,
        solo_passed_at TIMESTAMPTZ NULL,
        quiz_wrong_count INTEGER NOT NULL DEFAULT 0,
        completed_at TIMESTAMPTZ NULL,
        reviewed_at TIMESTAMPTZ NULL,
        review_failed_at TIMESTAMPTZ NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (user_id, lesson_id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_novelty_lesson_progress_lesson "
    "ON novelty_lesson_progress (lesson_id)",
    """CREATE TABLE IF NOT EXISTS novelty_daily_state (
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        day DATE NOT NULL,
        postponed_until TIMESTAMPTZ NULL,
        skipped_at TIMESTAMPTZ NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (user_id, day)
    )""",
)

LESSON_DOWNGRADE_DDL = (
    "DROP TABLE IF EXISTS novelty_daily_state",
    "DROP TABLE IF EXISTS novelty_lesson_progress",
)
