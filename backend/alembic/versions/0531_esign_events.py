"""Podpis umowy w NEXUSIE: dziennik zdarzeń wniosku i odcisk danych umowy.

Revision ID: 0531_esign_events
Revises: 0529_consent_screenshot_check

Pytanie zespołu z 27.10.2026: co, jeśli link do podpisu wygaśnie? Dotąd nowa
wysyłka robiła nowy PDF z Worda, a LibreOffice daje za każdym razem inne bajty
(data utworzenia, /ID), więc plik podpisany przed terminem był odrzucany
i kontraktor podpisywał drugi raz. Teraz „Przedłuż termin” i „Wyślij nowy
link” zostają na tym samym zamrożonym PDF-ie.

- ``events`` — przedłużenia, nowe linki, prośby kontraktora i wcześniejsze
  przypomnienia (pola stanu nadpisuje kolejny termin, historia ma je znać);
- ``source_payload_sha256`` — odcisk danych umowy przy wysyłce: nowy link na
  starym PDF-ie tylko, gdy umowy od tamtej chwili nikt nie poprawił;
- typ powiadomienia ``signature_renewal_requested`` — kontraktor prosi o nowy
  link (wartość enumu zostaje po downgrade, Postgres nie ma DROP VALUE).

Lustro w ``entrypoint.sh``.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0531_esign_events"
down_revision = "0529_consent_screenshot_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notificationtype "
            "ADD VALUE IF NOT EXISTS 'signature_renewal_requested'"
        )
    op.add_column(
        "b2b_signing_requests",
        sa.Column(
            "events",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "b2b_signing_requests",
        sa.Column("source_payload_sha256", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("b2b_signing_requests", "source_payload_sha256")
    op.drop_column("b2b_signing_requests", "events")
