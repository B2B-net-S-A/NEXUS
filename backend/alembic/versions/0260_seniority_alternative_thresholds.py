"""Ścieżka rozwoju: DWA alternatywne progi na poziom (korekta D6).

Oryginał (DynaReporter) awansuje regułą „6 placementów w 6 miesięcy **LUB**
12 w 12" i analogicznie „12 w 6 LUB 24 w 12" na Eksperta. Pierwsze podejście
zamodelowało tylko jedną regułę na poziom, więc osoba dowożąca stabilnie
przez rok — zamiast zrywem — nie awansowała nigdy: liczba w krótkim oknie nie
rośnie, jeśli tempo się nie zmienia.

Ta migracja robi dwie rzeczy:

1. Dosiewa cztery klucze alternatywnych progów (`ON CONFLICT DO NOTHING`, więc
   wartości ustawione wcześniej przez człowieka zostają).
2. Poprawia okno Eksperta 12 → 6 miesięcy — WYŁĄCZNIE na wierszach, których
   nikt nie dotknął (`updated_by IS NULL`) i które wciąż niosą starą wartość
   domyślną. Ten wiersz zasiała migracja 0256 jako odbicie kodu, a nie jako
   decyzję operatora; nadpisanie cudzego strojenia byłoby jednak cofnięciem
   świadomej zmiany, więc warunek jest zawężony do obu przesłanek naraz.

Nie ruszamy `competition_winners` — zamrożone podium jest write-once
(decyzja D3), a poziomy Ścieżki rozwoju i tak liczą się na żywo z historii
placementów, więc korekta progu działa od najbliższego odczytu.

Revision ID: 0260_seniority_alt_thresholds
Revises: 0259_recruitment_campaigns
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0260_seniority_alt_thresholds"
down_revision = "0259_recruitment_campaigns"
branch_labels = None
depends_on = None


# LUSTRO `SCORING_DEFAULTS`. Migracje nie importują kodu aplikacji (biegną też
# na starym obrazie) — strażnikiem zgodności jest
# `test_insights_scoring_config.py::test_migration_seed_matches_code_defaults`.
_NEW_DEFAULTS: list[tuple[str, int]] = [
    ("seniority_senior_alt_placements", 12),
    ("seniority_senior_alt_window_months", 12),
    ("seniority_expert_alt_placements", 24),
    ("seniority_expert_alt_window_months", 12),
]

_EXPERT_WINDOW_KEY = "seniority_expert_window_months"
_EXPERT_WINDOW_OLD = 12
_EXPERT_WINDOW_NEW = 6


def upgrade() -> None:
    conn = op.get_bind()

    for key, value in _NEW_DEFAULTS:
        conn.execute(
            sa.text(
                "INSERT INTO insights_scoring_config (key, value) "
                "VALUES (:key, :value) ON CONFLICT (key) DO NOTHING"
            ),
            {"key": key, "value": value},
        )

    conn.execute(
        sa.text(
            "UPDATE insights_scoring_config "
            "SET value = :new "
            "WHERE key = :key AND value = :old AND updated_by IS NULL"
        ),
        {
            "key": _EXPERT_WINDOW_KEY,
            "old": _EXPERT_WINDOW_OLD,
            "new": _EXPERT_WINDOW_NEW,
        },
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Symetrycznie: cofamy okno tylko tam, gdzie nadal stoi nasza wartość
    # i nikt jej po drodze nie zmienił.
    conn.execute(
        sa.text(
            "UPDATE insights_scoring_config "
            "SET value = :old "
            "WHERE key = :key AND value = :new AND updated_by IS NULL"
        ),
        {
            "key": _EXPERT_WINDOW_KEY,
            "old": _EXPERT_WINDOW_OLD,
            "new": _EXPERT_WINDOW_NEW,
        },
    )

    conn.execute(
        sa.text("DELETE FROM insights_scoring_config WHERE key = ANY(:keys)"),
        {"keys": [key for key, _ in _NEW_DEFAULTS]},
    )
