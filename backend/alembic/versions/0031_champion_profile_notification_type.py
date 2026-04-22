"""Add champion_profile_updated to notificationtype enum

Revision ID: 0031
Revises: 0030
Create Date: 2026-04-21 14:00:00.000000

Rozszerzamy enum `notificationtype` o wartość `champion_profile_updated`,
używaną przez Phase 11 (realtime CP): gdy Delivery Lead/admin edytuje Profil
Championa dla joba, osoby przypisane (recruiter_id + job_collaborators)
dostają powiadomienie w bellu + live refetch otwartego edytora.

Schema dedup jest już na miejscu z 0029 (related_entity_type/_id +
partial unique index ix_notif_dedup_daily). Nic więcej nie dodajemy.

NB: `ALTER TYPE ... ADD VALUE` wymaga autocommit — analogicznie do 0029.
"""

from alembic import op


revision = "0031_champion_profile_notification_type"
down_revision = "0030_candidate_created_by"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'champion_profile_updated'"
        )


def downgrade() -> None:
    # Nie usuwamy enum value — PG nie wspiera DROP VALUE bez rebudowy typu,
    # a istniejące notyfikacje mogłyby wskazywać na tę wartość. Zgodne
    # z konwencją migracji 0029.
    pass
