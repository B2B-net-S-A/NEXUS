"""Nagrobek: kandydat skasowany w Traffitcie zostaje w Nexusie, ale oznaczony.

Do tej pory 404/410 z Traffita było wyłącznie LICZONE (`gone_upstream`).
Licznik znika razem ze statystykami biegu, więc informacja „tej osoby nie ma
już u źródła" nie docierała nigdzie indziej: rekrutet widział zwykły profil,
`reconcile` pokazywał rozjazd bez wyjaśnienia, a każdy kolejny sweep pytał
Traffita o tego samego nieistniejącego kandydata.

Wiersza NIE kasujemy i nie planujemy kasować. Profil w Nexusie ma własną
wartość niezależną od Traffita — notatki, historia etapów, ślady RODO,
powiązania z rekrutacjami. Usunięcie źródła nie jest zgodą na usunięcie
naszych danych; to osobna decyzja, którą podejmuje człowiek.

Revision ID: 0221_candidate_external_deleted
Revises: 0220_service_accounts
"""

from alembic import op

revision = "0221_candidate_external_deleted"
down_revision = "0220_service_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE candidates "
        "ADD COLUMN IF NOT EXISTS external_deleted_at TIMESTAMP WITH TIME ZONE NULL"
    )
    # Indeks CZĘŚCIOWY — nagrobki są (i mają pozostać) rzadkie, więc pełny
    # indeks na 57 tys. wierszy kosztowałby tyle samo co skan, a interesuje nas
    # wyłącznie garstka z wartością niepustą.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidates_external_deleted_at "
        "ON candidates (external_deleted_at) "
        "WHERE external_deleted_at IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_candidates_external_deleted_at")
    op.execute("ALTER TABLE candidates DROP COLUMN IF EXISTS external_deleted_at")
