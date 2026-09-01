"""Kampanie rekrutacyjne — cel netto na oknie czasu (baner Insights → Rekrutacja).

Tabela trzyma WYŁĄCZNIE definicję kampanii: nazwę, emoji, okno i cel netto.
Liczniki (placementy, rezygnacje, netto) są liczone przy odczycie
z `analytics_first_milestones` i z `contracts`, więc nie ma tu ani jednej
kolumny na wynik.

Powód, dla którego wyniku nie przechowujemy: przesunięcie etapu albo
zakończenie kontraktu wstecz unieważnia zapisaną liczbę, a nic w systemie
tego nie zauważa. Baner pokazywałby „30 / 60" tam, gdzie naprawdę jest 27,
i nie byłoby żadnego błędu do zdiagnozowania.

DWIE WARSTWY WALIDACJI OKNA, I TO NIE JEST DUPLIKAT
---------------------------------------------------
`CHECK ck_recruitment_campaigns_window` (`end_date >= start_date`) broni
bazy przed importem i ręcznym SQL-em. API broni tego samego WCZEŚNIEJ, żeby
operator dostał czytelne 422 po polsku, a nie surowy `IntegrityError`.

Limit DŁUGOŚCI okna (366 dni) świadomie NIE ma odpowiednika w bazie: nie
wynika z integralności danych, tylko z `resolve_period(kind="custom")`,
przez który okno kampanii wyrażamy kanonicznym `Period` (żeby klucz cache'u
niósł granice). Zapisanie go jako `CHECK` przywiązałoby schemat do stałej
z warstwy analitycznej.

Revision ID: 0259_recruitment_campaigns
Revises: 0258_user_performance_flags
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0259_recruitment_campaigns"
down_revision = "0258_user_performance_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recruitment_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        # Emoji opcjonalne; 16 znaków, bo sekwencje ZWJ zajmują kilka punktów
        # kodowych, a limit 1-2 obciąłby je w połowie.
        sa.Column("emoji", sa.String(length=16), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column(
            "target_net", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        # `SET NULL`: usunięcie konta autora nie może skasować trwającej
        # kampanii — ginie wyłącznie atrybucja.
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Okno odwrócone daje `resolve_period("custom", ...)` pusty przedział,
        # więc baner pokazałby „0 z N" i „0 dni do końca" — liczby poprawne
        # arytmetycznie, opisujące nieistniejącą kampanię. Dziś pilnuje tego
        # tylko API; warunek w bazie zostaje także dla importów i ręcznych
        # poprawek SQL-em.
        sa.CheckConstraint(
            "end_date >= start_date",
            name="ck_recruitment_campaigns_window",
        ),
    )
    # Jedyne zapytanie na gorącej ścieżce to „aktywna kampania, najświeższa" —
    # indeks jest dokładnie pod nie.
    op.create_index(
        "ix_recruitment_campaigns_active",
        "recruitment_campaigns",
        ["is_active", "start_date"],
    )

    # Samosprawdzenie: migracja, która cicho nic nie zrobiła, jest gorsza niż
    # taka, która padła — bo wygląda na wdrożoną.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = 'recruitment_campaigns'
            ) THEN
                RAISE EXCEPTION 'Samosprawdzenie: recruitment_campaigns nie istnieje po migracji';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_recruitment_campaigns_window'
            ) THEN
                RAISE EXCEPTION 'Samosprawdzenie: brak CHECK-a odwroconego okna kampanii';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_recruitment_campaigns_active", table_name="recruitment_campaigns")
    op.drop_table("recruitment_campaigns")
