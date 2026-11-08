"""Szybkie wyszukiwanie kandydatów: indeksy GIN pod jedno wyrażenie (08.11.2026).

Revision ID: 0662_candidate_quick_search_indexes
Revises: 0661_cv_title_with_reference

Po #3145 wyszukiwarka globalna składała polskie znaki przez ``translate()`` na
pięciu osobnych wyrażeniach, a telefon przez ``regexp_replace()``. Żadne nie
pasowało do ``ix_candidates_identity_trgm``, więc fraza bez trafienia to był
seq scan 68 tys. wierszy (336 ms; audyt 08.11.2026, S4/W6). Zapytanie
(``api/search.py``) sprawdza teraz jedno wyrażenie, a te indeksy je pokrywają.

Tekst wyrażeń musi się zgadzać z ``_CANDIDATE_IDENTITY_FOLDED_SQL`` i
``PHONE_DIGITS_SQL`` co do znaku (``test_candidate_quick_search_index.py``).
Lustro DDL: ``_INDEX_STATEMENTS`` w ``entrypoint.sh``.
"""

from alembic import op

revision = "0662_candidate_quick_search_indexes"
down_revision = "0661_cv_title_with_reference"
branch_labels = None
depends_on = None

_IDENTITY_INDEX = "ix_candidates_quick_identity_trgm"
_PHONE_INDEX = "ix_candidates_phone_digits_trgm"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_IDENTITY_INDEX} "
            "ON candidates USING GIN ((translate("
            "coalesce(name, '') || ' ' || coalesce(lastname, '') "
            "|| ' ' || coalesce(email, '') "
            "|| ' ' || coalesce(lastname, '') "
            "|| ' ' || coalesce(name, ''), "
            "'ąćęłńóśźżĄĆĘŁŃÓŚŹŻ', 'acelnoszzACELNOSZZ')) gin_trgm_ops)"
        )
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_PHONE_INDEX} "
            "ON candidates USING GIN ("
            "(regexp_replace(coalesce(phone, ''), '[^0-9]', '', 'g')) gin_trgm_ops)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_IDENTITY_INDEX}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_PHONE_INDEX}")
