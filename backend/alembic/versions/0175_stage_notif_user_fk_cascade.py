"""stage notification specific_user FK: ON DELETE SET NULL -> CASCADE.

M4 audyt P1.16 (plan PR-01): FK ``specific_user_id`` miało ``ON DELETE SET
NULL``, ale CHECK (``ck_stage_notif_specific_user`` / analogiczny na
overrides) wymaga non-NULL ``specific_user_id`` dla
``recipient_type='specific_user'``. Usunięcie użytkownika wskazywanego przez
regułę kończyło się naruszeniem CHECK zamiast czystym cleanupem. Reguła
powiadomień wskazująca usuniętego odbiorcę jest bezprzedmiotowa — CASCADE
usuwa ją razem z użytkownikiem. Dotyczy OBU tabel:
``stage_notification_rules`` i ``client_stage_notification_overrides``.

Mirror w ``backend/entrypoint.sh`` (_COLUMN_STATEMENTS) — prod alembic jest
orphaned, więc safety net wykonuje te same pary DROP+ADD (rerun-safe).

Revision ID: 0175_stage_notif_user_fk_cascade
Revises: 0174_analytics_v1_foundation
"""

from alembic import op

revision = "0175_stage_notif_user_fk_cascade"
down_revision = "0174_analytics_v1_foundation"
branch_labels = None
depends_on = None

_TABLES = ("stage_notification_rules", "client_stage_notification_overrides")


def _swap(delete_rule: str) -> None:
    for table in _TABLES:
        fk = f"{table}_specific_user_id_fkey"
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {fk}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {fk} "
            "FOREIGN KEY (specific_user_id) REFERENCES users(id) "
            f"ON DELETE {delete_rule}"
        )


def upgrade() -> None:
    _swap("CASCADE")


def downgrade() -> None:
    _swap("SET NULL")
