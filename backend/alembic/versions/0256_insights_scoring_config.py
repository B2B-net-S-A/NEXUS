"""Konfigurowalna punktacja Insights: Liga Mistrzów + progi Ścieżki rozwoju.

Klucz-wartość z wartościami całkowitymi. Tabela trzyma wyłącznie ODSTĘPSTWA
od wartości domyślnych zapisanych w kodzie
(`app.services.insights_scoring_config.SCORING_DEFAULTS`), więc brak wiersza
znaczy „obowiązuje domyślna", a nie „brak danych".

Seed wstawia komplet domyślnych mimo to — po to, żeby ekran ustawień pokazywał
datę i autora ostatniej zmiany od pierwszego dnia, a nie dopiero po pierwszym
zapisie. `ON CONFLICT DO NOTHING` zostawia nietknięte wartości ustawione
wcześniej przez człowieka, więc migracja jest idempotentna i bezpieczna także
wtedy, gdy tabelę dowiózł wcześniej safety-net z `entrypoint.sh`.

Ta migracja NIE dotyka `competition_winners`. Zamrożone podium jest
write-once, a nowa formuła obowiązuje od najbliższego niezamkniętego kwartału
(decyzja D3) — przeliczenie historii zmieniłoby wynik konkursu, za którym
poszły już pieniądze.

Revision ID: 0256_insights_scoring_config
Revises: 0255_client_cv_rules
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0256_insights_scoring_config"
down_revision = "0255_client_cv_rules"
branch_labels = None
depends_on = None


# (klucz, wartość domyślna) — LUSTRO `SCORING_DEFAULTS`. Migracje nie mogą
# importować kodu aplikacji (uruchamiają się też na starym obrazie), więc
# kopia jest tu świadoma; strażnikiem zgodności jest test
# `test_insights_scoring_config.py::test_migration_seed_matches_code_defaults`.
_DEFAULTS: list[tuple[str, int]] = [
    ("league_points_placement", 150),
    ("league_points_interview", 15),
    ("league_points_recommendation", 5),
    ("league_min_placements_month1", 1),
    ("league_min_placements_month2", 2),
    ("league_min_placements_month3", 3),
    ("seniority_senior_placements", 6),
    ("seniority_senior_window_months", 6),
    ("seniority_expert_placements", 12),
    ("seniority_expert_window_months", 12),
]


def upgrade() -> None:
    op.create_table(
        "insights_scoring_config",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column(
            "updated_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    conn = op.get_bind()
    for key, value in _DEFAULTS:
        conn.execute(
            sa.text(
                "INSERT INTO insights_scoring_config (key, value) "
                "VALUES (:key, :value) ON CONFLICT (key) DO NOTHING"
            ),
            {"key": key, "value": value},
        )


def downgrade() -> None:
    op.drop_table("insights_scoring_config")
