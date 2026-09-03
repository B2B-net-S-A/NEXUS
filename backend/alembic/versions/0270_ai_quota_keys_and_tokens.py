"""Dwa ostatnie klucze kwot AI + tokeny w ``ai_usage_log``.

Revision ID: 0270_ai_quota_keys_and_tokens
Revises: 0269_configurable_section_rbac

Domyka audyt z 02.09 (``docs/talent-radar-and-ai-features-audit-2026-09-02.md``).

**``uop_check``** — sprawdzenie znamion umowy o pracę w Generatorze Umów B2B.
Stało całkowicie poza systemem kwot: potwierdzone na produkcji 02.09, że
wywołanie trwa 15,4 s, a licznik w Ustawieniach → AI nie drga. Klucz jest też
WARUNKIEM zdjęcia ``cv_generator_b2b/ai_client.py`` z ``_RAW_CLIENT_BASELINE``:
po tamtej zmianie ``_assert_declared`` zaczyna widzieć tę trasę, a handler łapie
wyłącznie ``CVGeneratorAIError``/``ValueError`` — ``AIQuotaUngated`` przeszłoby
oba i dało nieobsłużone 500.

**``cv_name_backfill``** — uzupełnianie imion z tekstu CV w nocnym syncu
Traffita. Osobny kubełek od ``cv_backfill`` mimo mylnie podobnych nazw modułów:
tamten należy do ``cv_field_backfill.py`` i przy wyczerpanej kwocie ZATRZYMUJE
bieg, a ta ścieżka ma tylko pominąć płatny krok. Dwa przeciwne zachowania pod
jednym kluczem są nie do wytłumaczenia operatorowi.

**Tokeny** — ``ai_usage_log.input_tokens`` / ``output_tokens``. Alarm o skoku
wydatków (jedyna ochrona budżetu po decyzji z 24.08 o braku sufitów) liczy dziś
WYWOŁANIA, więc jedna generacja CV B2B waży w nim tyle co jedna linia MINDY.
``BigInteger``, bo jeden bieg masowy z 08.2026 zjadł 105,8 mln tokenów
wejściowych — przy sumowaniu miesięcznym ``int4`` przepełni się.

Kalka 0236/0240: ADD VALUE w autocommit (wymóg ``ALTER TYPE``), seed poza
blokiem i idempotentny. Zdublowane w safety-net ``entrypoint.sh`` — prod alembic
bywa orphaned.
"""

import sqlalchemy as sa
from alembic import op

revision = "0270_ai_quota_keys_and_tokens"
down_revision = "0269_configurable_section_rbac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD VALUE musi biec w autocommicie: Postgres nie pozwala użyć nowej
    # etykiety enuma w tej samej transakcji, w której ją dodano — a seed niżej
    # używa jej jako literału.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'uop_check'")
        op.execute("ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'cv_name_backfill'")

    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        "SELECT 'uop_check', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS (SELECT 1 FROM ai_features WHERE feature = 'uop_check')"
    )
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        "SELECT 'cv_name_backfill', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS (SELECT 1 FROM ai_features WHERE feature = 'cv_name_backfill')"
    )

    # `server_default="0"` obowiązkowy: kolumna jest NOT NULL, a tabela ma na
    # prodzie wiersze historyczne, którym nikt nie policzy tokenów wstecz.
    op.add_column(
        "ai_usage_log",
        sa.Column(
            "input_tokens",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "ai_usage_log",
        sa.Column(
            "output_tokens",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_usage_log", "output_tokens")
    op.drop_column("ai_usage_log", "input_tokens")
    # PostgreSQL nie kasuje wartości enuma in-place — zostają w typie
    # (bezpieczne, nieużywane po usunięciu seedu).
    op.execute("DELETE FROM ai_features WHERE feature = 'cv_name_backfill'")
    op.execute("DELETE FROM ai_features WHERE feature = 'uop_check'")
