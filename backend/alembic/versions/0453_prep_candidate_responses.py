"""Prepy: odpowiedź kandydata z Outlooka i powiadomienia zespołu pary (D5–D8).

Revision ID: 0453_prep_candidate_responses
Revises: 0452_blacklist_contract_only

Zgłoszenie Delivery Leada (17.10.2026): DL-e nie wiedzieli, że kandydat
przyjął prep albo że poprosił o inny termin — NEXUS w ogóle nie czytał
odpowiedzi z zaproszenia, a mail „Zaakceptowano” dostawał tylko organizator.
Kolumny na wierszu prepu: odpowiedź kandydata, kiedy przyszła, proponowany
termin i kiedy NEXUS ostatnio sprawdził spotkanie w Outlooku. ``NULL`` w
``candidate_response`` = jeszcze nie sprawdzano (wiersz sprzed tej rewizji).

Pięć typów powiadomień w ikonie „Kalendarz”: odpowiedź kandydata (przyjął /
może), odmowa albo inny termin, zmiana prepu przez kogoś z pary (u siebie
i w cudzym kalendarzu) i brak odpowiedzi na dobę przed prepem.

Lustro w ``entrypoint.sh`` — pilnuje ``test_prep_candidate_responses_migration.py``.
"""

from alembic import op

revision = "0453_prep_candidate_responses"
down_revision = "0452_blacklist_contract_only"
branch_labels = None
depends_on = None

ADD_COLUMNS = (
    "ALTER TABLE prep_meetings ADD COLUMN IF NOT EXISTS candidate_response VARCHAR(20) NULL",
    "ALTER TABLE prep_meetings ADD COLUMN IF NOT EXISTS candidate_response_at TIMESTAMPTZ NULL",
    "ALTER TABLE prep_meetings ADD COLUMN IF NOT EXISTS proposed_start TIMESTAMPTZ NULL",
    "ALTER TABLE prep_meetings ADD COLUMN IF NOT EXISTS proposed_end TIMESTAMPTZ NULL",
    "ALTER TABLE prep_meetings ADD COLUMN IF NOT EXISTS outlook_checked_at TIMESTAMPTZ NULL",
)
ADD_RESPONSE_CHECK = """DO $$ BEGIN
        ALTER TABLE prep_meetings ADD CONSTRAINT ck_prep_meetings_candidate_response
            CHECK (candidate_response IS NULL
                   OR candidate_response IN ('none', 'accepted', 'tentative', 'declined'));
    EXCEPTION WHEN duplicate_object THEN NULL; END $$"""

NOTIFICATION_TYPES = (
    "prep_candidate_response",
    "prep_candidate_declined",
    "prep_changed",
    "prep_changed_yours",
    "prep_no_response",
)
ADD_NOTIFICATION_TYPES = tuple(
    f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'"
    for value in NOTIFICATION_TYPES
)

# Wartości enuma zostają po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji ich nie zna — powiadomienie takiego typu dałoby 500.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text IN ('prep_candidate_response',
            'prep_candidate_declined', 'prep_changed', 'prep_changed_yours',
            'prep_no_response')
    ) THEN
        RAISE EXCEPTION 'Downgrade 0453 odmawia: notifications ma wpisy prepów, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    for statement in ADD_COLUMNS:
        op.execute(statement)
    op.execute(ADD_RESPONSE_CHECK)
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        for statement in ADD_NOTIFICATION_TYPES:
            op.execute(statement)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(
        "ALTER TABLE prep_meetings DROP CONSTRAINT IF EXISTS "
        "ck_prep_meetings_candidate_response"
    )
    for column in (
        "outlook_checked_at",
        "proposed_end",
        "proposed_start",
        "candidate_response_at",
        "candidate_response",
    ):
        op.execute(f"ALTER TABLE prep_meetings DROP COLUMN IF EXISTS {column}")
