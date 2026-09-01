"""Dni robocze uzytkownika w oknie czasu — mianownik wskaznikow „na dzien" (D5).

Do 2026-08-31 Power Calling dzielil tygodniowa liczbe weryfikacji przez stala
``5`` i publikowal imienna liste „ponizej progu", wiec osoba na urlopie
ladowala na niej pod nazwiskiem. NEXUS nie zna nieobecnosci; ta tabela je
przechowuje, zaciagane z COMPASSA.

CO TU TRAFIA: wylacznie LICZBY DNI. Nigdy typ nieobecnosci ani notatka —
``leave_type`` przyjmuje w COMPASSIE ``sick_leave``/``parental_leave`` (dane
o zdrowiu), a ``note`` zawiera wolny tekst medyczny. Kontrakt jest wymuszony
po obu stronach: sygnatura funkcji eksportujacej w COMPASSIE tez ich nie oddaje.

OKNO, NIE MIESIAC: kolumny to domkniety przedzial [period_start, period_end],
bo Power Calling raportuje TYDZIEN ISO, a wskazniki MD miesiac. Przyblizanie
tygodnia z miesiecznej sredniej byloby zgadywaniem — tym samym defektem co
dzielenie przez sztywne 5, tylko z ladniejszym mianownikiem.

Revision ID: 0257_user_workday_periods
Revises: 0256_insights_scoring_config
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0257_user_workday_periods"
down_revision = "0256_insights_scoring_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_workday_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("business_days", sa.Integer(), nullable=False),
        # NUMERIC, nie INTEGER: COMPASS dopuszcza pol dnia urlopu (`half_day`),
        # wiec zaokraglenie cicho gubiloby polowki.
        sa.Column("absence_days", sa.Numeric(5, 1), nullable=False),
        sa.Column("working_days", sa.Numeric(5, 1), nullable=False),
        # Czym ta liczba JEST — jedzie do UI razem z nia. Chorobowe dla B2B
        # jest w COMPASSIE strukturalnie niezapisywalne, a rekruterzy sa
        # w wiekszosci B2B, wiec to „dni robocze minus urlop", nie
        # „dni przepracowane". Podpisanie inaczej odtworzyloby defekt.
        sa.Column(
            "basis",
            sa.String(64),
            nullable=False,
            server_default="business_days_minus_approved_leave",
        ),
        sa.Column("source", sa.String(32), nullable=False, server_default="compass"),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "user_id", "period_start", "period_end", name="uq_user_workday_period"
        ),
    )
    op.create_index(
        "ix_user_workday_periods_user_id", "user_workday_periods", ["user_id"]
    )
    op.create_index(
        "ix_user_workday_periods_window",
        "user_workday_periods",
        ["period_start", "period_end"],
    )

    # Samosprawdzenie: migracja, ktora cicho nic nie zmienila, jest gorsza niz
    # taka, ktora padla — bo wyglada na wdrozona.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'user_workday_periods'
            ) THEN
                RAISE EXCEPTION 'Samosprawdzenie: user_workday_periods nie istnieje po migracji';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_user_workday_periods_window", table_name="user_workday_periods")
    op.drop_index("ix_user_workday_periods_user_id", table_name="user_workday_periods")
    op.drop_table("user_workday_periods")
