"""Merge OAuth and CV storage heads.

Revision ID: 0082_merge_oauth_storage_heads
Revises: 0081_merge_autenti_cv_storage, 0081_user_oauth_fields
Create Date: 2026-05-08 10:00:00.000000

Pure merge migration — joins two parallel ``0081`` heads:
- ``0081_merge_autenti_cv_storage`` (merge of autenti + cv_storage 0080s)
- ``0081_user_oauth_fields``        (Microsoft SSO + auth_exchange_codes)

Both branches mergeowały tę samą parę 0080 (autenti_signatures + cv_storage_key)
niezależnie, co dało dwa równoległe heady. Ten plik je rejoinuje, żeby
single-head policy (z ``project_alembic_state.md``) była spełniona.

No-op upgrade/downgrade — same struktura schematu, tylko topologia.
"""

revision = "0082_merge_oauth_storage_heads"
down_revision = (
    "0081_merge_autenti_cv_storage",
    "0081_user_oauth_fields",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
