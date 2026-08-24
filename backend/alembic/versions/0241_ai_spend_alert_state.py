"""Stempel alertu o zużyciu AI — trwały, bo Coolify restartuje przy każdym pushu.

Rewizja 0241.

Kolumny na `ai_features`, NIE na `ai_usage_log`: alert dotyczy FUNKCJI
w danym okresie, a `ai_usage_log` ma ziarno `(feature, user, period)` — stempel
per użytkownik wysyłałby jedno ostrzeżenie na każdą osobę, która danej nocy
uruchomiła pętlę.

Dlaczego stempel w bazie, a nie zbiór w pamięci: prod restartuje się przy KAŻDYM
pushu na main (Coolify), a przy `--workers > 1` każdy proces miałby własny zbiór.
Ten sam błąd naprawiono już w `slack_sla_alerts` (komentarz w tamtym module
opisuje ponowne alertowanie po restarcie).
"""

from alembic import op
import sqlalchemy as sa

revision = "0241_ai_spend_alert_state"
down_revision = "0240_cv_generator_mindy_ai_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_features",
        sa.Column("spend_alert_period", sa.Date(), nullable=True),
    )
    op.add_column(
        "ai_features",
        sa.Column("spend_alert_level", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_features", "spend_alert_level")
    op.drop_column("ai_features", "spend_alert_period")
