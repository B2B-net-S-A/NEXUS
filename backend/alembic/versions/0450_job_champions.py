"""Championi rekrutacji — osoby zamiast samej flagi i dwa typy dzwonków.

Revision ID: 0450_job_champions
Revises: 0449_rate_from_contracts

Zgłoszenie DL i rekruterów, decyzje Artura D1–D9 (15.10.2026): Delivery Lead
zaznacza jednego albo kilku championów na liście pod plakietką statusu
rekrutacji. ``jobs.champion_found_at`` zostaje i znaczy „nie szukamy” —
liczy ją serwis z tej tabeli (championi ∪ zatrudnieni ≥ liczba miejsc).

* żywy wiersz (``cleared_at IS NULL``) — jeden na parę (rekrutacja, kandydat);
* ``cleared_reason``: ``manual`` (lista w nagłówku) | ``card_closed`` (karta
  championa zamknięta) | ``removed_from_job`` (osoba usunięta z rekrutacji).

Bez danych wstecz: oznaczenia sprzed zmiany zostają jako sama flaga
(„Mamy championa” bez osoby), DL wskazuje osoby przy najbliższej okazji.

Typy dzwonków ``champions_changed`` (zapis listy) i ``champion_search_resumed``
(odpadł ostatni champion albo lista zdjęta — wracamy do szukania).

Lustro w ``entrypoint.sh`` — pilnuje ``test_job_champions_migration.py``.
"""

from alembic import op

revision = "0450_job_champions"
down_revision = "0449_rate_from_contracts"
branch_labels = None
depends_on = None

CREATE_TABLE = """CREATE TABLE IF NOT EXISTS job_champions (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    marked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    marked_by_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    cleared_at TIMESTAMPTZ NULL,
    cleared_reason VARCHAR(20) NULL,
    cleared_by_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT ck_job_champions_cleared_reason
        CHECK (cleared_reason IS NULL OR cleared_reason IN
            ('manual', 'card_closed', 'removed_from_job')),
    CONSTRAINT ck_job_champions_cleared
        CHECK ((cleared_at IS NULL) = (cleared_reason IS NULL))
)"""
CREATE_JOB_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_job_champions_job_id ON job_champions (job_id)"
)
CREATE_CANDIDATE_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_job_champions_candidate_id "
    "ON job_champions (candidate_id)"
)
CREATE_LIVE_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_job_champions_live "
    "ON job_champions (job_id, candidate_id) WHERE cleared_at IS NULL"
)

ADD_CHANGED_TYPE = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'champions_changed'"
)
ADD_RESUMED_TYPE = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'champion_search_resumed'"
)

# Wartości enuma zostają po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji ich nie zna — dzwonek tego typu dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text IN ('champions_changed', 'champion_search_resumed')
    ) THEN
        RAISE EXCEPTION 'Downgrade 0450 odmawia: notifications ma wpisy champions_changed/champion_search_resumed, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    op.execute(CREATE_TABLE)
    op.execute(CREATE_JOB_INDEX)
    op.execute(CREATE_CANDIDATE_INDEX)
    op.execute(CREATE_LIVE_INDEX)
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ADD_CHANGED_TYPE)
        op.execute(ADD_RESUMED_TYPE)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute("DROP TABLE IF EXISTS job_champions")
