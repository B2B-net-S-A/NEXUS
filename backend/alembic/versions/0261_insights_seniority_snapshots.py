"""Dziennik obserwacji poziomu seniority (append-only).

`insights_seniority` liczy poziom PRZY ODCZYCIE i świadomie go nie
przechowuje — pełne uzasadnienie w docstringu tamtego modułu. Ta migracja
NIE zmienia tej decyzji: poziom nadal nie ma tu swojej „prawdy". Tabela jest
DZIENNIKIEM OBSERWACJI i odpowiada na jedno pytanie, na które moduł liczący
przy odczycie odpowiedzieć nie może:

    czy komuś zmienił się poziom, mimo że ta osoba nic dziś nie zrobiła?

Poziom jest funkcją historii atrybucji, a ta się zmienia (import Traffita
dopisujący zaległe `hired`, przepięcie placementu na inne konto). Bez
dziennika taka zmiana jest NIEWIDOCZNA: przy odczycie widać tylko stan
bieżący, a poprzedni nie istnieje nigdzie.

Cztery decyzje, które trzymają ten dziennik uczciwym:

1. **Wiersz powstaje TYLKO przy zmianie**, nie co dobę. Codzienny wiersz dla
   niezmienionego poziomu zamieniłby dziennik w log niczego, w którym realna
   zmiana ginie wśród duplikatów — a przy ~60 osobach to 22 tys. wierszy
   rocznie po to, żeby ukryć kilkanaście istotnych.

2. **`previous_level` leży NA WIERSZU.** Zmiana ma być czytelna bez łączenia
   z wierszem poprzednim: to samo pytanie zadane self-joinem daje inną
   odpowiedź, gdy dziennik kiedykolwiek zostanie przycięty.

3. **`thresholds_fingerprint`** — poziom zmienia się też wtedy, gdy operator
   zmieni PRÓG w konfiguracji scoringu, a nie historia. Bez odcisku progów
   obniżenie poprzeczki wygląda w dzienniku identycznie jak cofnięcie
   atrybucji, czyli dziennik myli decyzję operatora z awarią danych.

4. **`is_regression` liczone przy ZAPISIE, nie przy odczycie.** Moduł liczący
   ma regułę „bez degradacji" (poziom raz osiągnięty zostaje), więc spadek
   ZAWSZE oznacza, że historia zmieniła się komuś pod nogami. To jest fakt
   o momencie obserwacji — wyliczanie go później z porównania z aktualnymi
   progami dałoby inną odpowiedź po każdej zmianie konfiguracji.

`ON DELETE CASCADE`: usunięty użytkownik nie ma podmiotu, o którym dziennik
mówi. RESTRICT zamieniłby dziennik w blokadę usunięcia konta.

Revision ID: 0261_insights_seniority_snapshots
Revises: 0260_seniority_alt_thresholds
"""

from alembic import op
import sqlalchemy as sa

revision = "0261_insights_seniority_snapshots"
down_revision = "0260_seniority_alt_thresholds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "insights_seniority_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("level", sa.String(length=16), nullable=False),
        # NULL = pierwsza obserwacja tej osoby. Świadomie różne od „poziom się
        # nie zmienił": pierwszy wiersz nie jest zmianą i nie może się liczyć
        # jako awans.
        sa.Column("previous_level", sa.String(length=16), nullable=True),
        sa.Column("total_placements", sa.Integer(), nullable=False),
        sa.Column("previous_total_placements", sa.Integer(), nullable=True),
        sa.Column("senior_since", sa.String(length=7), nullable=True),
        sa.Column("expert_since", sa.String(length=7), nullable=True),
        sa.Column("thresholds_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "is_regression",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Jedyne zapytanie tego dziennika brzmi „ostatnia obserwacja tej osoby",
    # więc indeks jest zstępujący po czasie w obrębie użytkownika.
    op.create_index(
        "ix_insights_seniority_snapshots_user_observed",
        "insights_seniority_snapshots",
        ["user_id", sa.text("observed_at DESC")],
    )
    op.create_check_constraint(
        "ck_insights_seniority_snapshots_level",
        "insights_seniority_snapshots",
        "level IN ('junior', 'senior', 'expert')",
    )
    op.create_check_constraint(
        "ck_insights_seniority_snapshots_previous_level",
        "insights_seniority_snapshots",
        "previous_level IS NULL OR previous_level IN ('junior', 'senior', 'expert')",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_insights_seniority_snapshots_user_observed",
        table_name="insights_seniority_snapshots",
    )
    op.drop_table("insights_seniority_snapshots")
