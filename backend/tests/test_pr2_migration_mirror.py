"""0358 i 0359 mają lustro w entrypoincie (alembic na prodzie bywa osierocony)."""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ENTRYPOINT = re.sub(r"\s+", " ", (BACKEND / "entrypoint.sh").read_text())
VERSIONS = BACKEND / "alembic" / "versions"


def _migration(name: str) -> str:
    return re.sub(r"\s+", " ", (VERSIONS / name).read_text())


def test_application_confirmation_table_is_mirrored():
    migration = _migration("0358_application_confirmation.py")
    for needle in (
        "CREATE TABLE IF NOT EXISTS application_confirmation_sends",
        "UNIQUE (email_key, link_key)",
        "uq_application_confirmation_sends_pair",
    ):
        assert needle in migration, needle
        assert needle in ENTRYPOINT, needle


def test_order_group_cancel_schema_is_mirrored():
    migration = _migration("0359_order_group_cancel.py")
    for needle in (
        "status_before_cancel",
        "cancelled_at",
        "cancelled_by_user_id",
        "cancellation_reason",
        "ck_client_order_groups_cancel_coherence",
        "'order_cancelled', 'order_restored'",
    ):
        assert needle in migration, needle
        assert needle in ENTRYPOINT, needle
    # Każda definicja CHECK statusu grupy w entrypoincie zna 'cancelled' —
    # stara lista w innym bloku zawęziłaby więz z powrotem przy starcie.
    for match in re.finditer(
        r"ADD CONSTRAINT ck_client_order_groups_status CHECK \((.*?)\)", ENTRYPOINT
    ):
        assert "'cancelled'" in match.group(1), match.group(0)


def test_chain_is_linear():
    assert 'revision = "0358_application_confirmation"' in _migration(
        "0358_application_confirmation.py"
    )
    cancel = _migration("0359_order_group_cancel.py")
    assert 'down_revision = "0358_application_confirmation"' in cancel
