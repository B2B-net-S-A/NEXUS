"""Plakietki ostrzezen przy osobie (Insights → Rekrutacja).

DynaReporter pokazuje pod nazwiskiem „Slabe wyniki" i „Procedury" z wolnym
komentarzem; NEXUS nie mial tego modelu wcale. Wiersz tej tabeli to imienna
OCENA PRACOWNIKA widoczna kazdej zalogowanej roli (decyzja D7), wiec schemat
wymusza trzy rzeczy, ktorych sam kod aplikacji nie utrzyma:

* wygaszenie zamiast kasowania — CHECK `..._clear_coherence` nie dopuszcza
  ani flagi „aktywnej, ale zdjetej", ani „zdjetej bez daty"; sciezki DELETE
  w API nie ma wcale, bo historia oceny musi przetrwac zdjecie plakietki,
* atrybucje — `created_by`/`cleared_by` z `ON DELETE SET NULL`: usuniecie
  konta autora gubi podpis, nie tresc oceny (CASCADE skasowalby ocene razem
  z odejsciem osoby, ktora ja postawila),
* jedna AKTYWNA flaga danego typu na osobe — czesciowy indeks unikalny, bo
  drugi zapis tego samego typu renderowalby te sama plakietke dwa razy.

Katalog typow jest zamkniety CHECK-iem (`weak_results` | `procedures`).
Stale opisy plakietek („Bardzo slabe wyniki, wymagana nagla poprawa") zostaja
w KODZIE — w bazie siedzi wylacznie to, co czlowiek napisal sam (`note`).

Revision ID: 0258_user_performance_flags
Revises: 0257_user_workday_periods
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0258_user_performance_flags"
down_revision = "0257_user_workday_periods"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_performance_flags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("flag_type", sa.String(32), nullable=False),
        # Wolny komentarz autora. Opcjonalny — sama plakietka bywa cala
        # wiadomoscia, a wymuszony komentarz produkuje wypelniacze.
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        # NULLABLE wylacznie z powodu `ON DELETE SET NULL`. API zawsze stempluje
        # autora, wiec NULL znaczy „konto autora zniknelo", nie „nikt nie wie".
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cleared_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "flag_type IN ('weak_results', 'procedures')",
            name="ck_user_performance_flags_type",
        ),
        # `cleared_by` swiadomie NIE jest wymagane przy wygaszeniu: FK ma
        # SET NULL, wiec twardy warunek zablokowalby usuniecie konta osoby,
        # ktora plakietke zdjela.
        sa.CheckConstraint(
            "(is_active AND cleared_at IS NULL AND cleared_by IS NULL)"
            " OR (NOT is_active AND cleared_at IS NOT NULL)",
            name="ck_user_performance_flags_clear_coherence",
        ),
    )
    op.create_index(
        "ix_user_performance_flags_user_id", "user_performance_flags", ["user_id"]
    )
    op.create_index(
        "ix_user_performance_flags_active",
        "user_performance_flags",
        ["user_id", "is_active"],
    )
    op.create_index(
        "uq_user_performance_flags_active_type",
        "user_performance_flags",
        ["user_id", "flag_type"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    # Samosprawdzenie: migracja, ktora cicho nic nie zrobila, jest gorsza niz
    # taka, ktora padla — bo wyglada na wdrozona. Sprawdzamy tabele I OBA
    # CHECK-i, bo to one, a nie kod, trzymaja „wygaszamy, nie kasujemy".
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = 'user_performance_flags'
            ) THEN
                RAISE EXCEPTION 'Samosprawdzenie: user_performance_flags nie istnieje po migracji';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_user_performance_flags_clear_coherence'
            ) THEN
                RAISE EXCEPTION 'Samosprawdzenie: brak CHECK-a spojnosci wygaszenia';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_user_performance_flags_type'
            ) THEN
                RAISE EXCEPTION 'Samosprawdzenie: brak CHECK-a katalogu typow';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_index(
        "uq_user_performance_flags_active_type", table_name="user_performance_flags"
    )
    op.drop_index(
        "ix_user_performance_flags_active", table_name="user_performance_flags"
    )
    op.drop_index(
        "ix_user_performance_flags_user_id", table_name="user_performance_flags"
    )
    op.drop_table("user_performance_flags")
