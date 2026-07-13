"""Diacritic-insensitive candidate search (search_doc_unaccented + GIN trigram).

Revision ID: 0159_candidate_search_doc_unaccented
Revises: 0158_cortex_skill_facts
Create Date: 2026-07-13 12:00:00.000000

Why this exists
---------------
Recruiters routinely type a Polish name WITHOUT the diacritics — ``lukasz
gradzki`` for „Łukasz Grądzki", ``krakow`` for „Kraków" — and got **0 results**.
Both search paths in ``app.services.advanced_candidate_search`` are
diacritic-SENSITIVE:

* the FTS path (``search_fts @@ to_tsquery('simple', 'lukasz:*')``) — the
  ``'simple'`` config lowercases + tokenizes but never folds accents, so the
  stored token ``łukasz`` is not reachable from the query ``lukasz``;
* the substring path (``search_doc ILIKE '%lukasz%'``) — ``Łukasz`` contains
  ``ł`` (U+0142), a distinct letter, so ``%lukasz%`` never matches.

Postgres ``unaccent`` is **not installed** on prod, and it is a superuser
``CREATE EXTENSION`` + a chained text-search config to wire up. Instead we fold
with pure SQL ``translate()`` — Polish diacritics are all single precomposed
(NFC) codepoints, so a 1:1 character map is exact, and ``translate`` /
``lower`` are both ``IMMUTABLE`` (usable in a ``STORED`` generated column).

What it adds
------------
1. ``candidates.search_doc_unaccented`` — a ``STORED`` generated ``text`` column
   that is the diacritic-folded, lowercased mirror of ``search_doc`` (migration
   0126): the SAME 16 non-CV text fields, wrapped in
   ``lower(translate(<doc>, 'ąćęłńóśźż…', 'acelnoszz…'))``. Generated → no
   app-side maintenance, always consistent on UPDATE. Excludes ``raw_cv_text``
   (like ``search_doc``) so the ``ADD COLUMN`` rewrite never detoasts the ~171MB
   of CV text — the ``ACCESS EXCLUSIVE`` lock is only a few seconds. The ORM
   never maps it; it is referenced as a bare column in the search WHERE only.

2. ``ix_candidates_search_doc_unaccent_trgm`` — GIN (gin_trgm_ops) on the folded
   column so the folded ``ILIKE`` is an index scan, not a 47.6K-row seq scan.
   Built CONCURRENTLY (prod has live writes).

The query layer folds the user's phrase with the SAME map (see
``advanced_candidate_search.fold_polish``) and unions a
``search_doc_unaccented ILIKE '%<folded>%'`` branch into every phrase match, so
``?q=lukasz`` and ``?q=Łukasz`` both resolve to the same candidates. The change
is purely ADDITIVE — the existing exact ``search_doc`` / ``search_fts`` branches
stay, so diacritic-present queries keep matching exactly (no regression).

Why CONCURRENTLY (and the autocommit block): the index build must not lock
candidate writes during deploy; ``CREATE INDEX CONCURRENTLY`` cannot run in a
transaction, and Alembic wraps upgrades in one by default.
"""

from alembic import op

revision = "0159_candidate_search_doc_unaccented"
down_revision = "0158_cortex_skill_facts"
branch_labels = None
depends_on = None


# Field list mirrors search_doc (migration 0126) EXACTLY, in the same order, so
# search_doc_unaccented is literally the folded form of search_doc.
_TEXT_COLS = (
    "name",
    "lastname",
    "email",
    "phone",
    "location",
    "city",
    "linkedin_current_title",
    "linkedin_current_company",
    "ai_summary",
    "competence_category",
    "engagement_notes",
)
_JSON_COLS = ("experience", "skills", "tags", "education", "languages")

# Polish diacritic → ASCII fold. Single precomposed (NFC) codepoints, both cases.
# MUST stay in sync with advanced_candidate_search._POLISH_FOLD_SRC/_DST and the
# entrypoint.sh safety-net copy.
_FOLD_SRC = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"
_FOLD_DST = "acelnoszzACELNOSZZ"


def _doc_expr() -> str:
    parts = [f"coalesce({c}, '')" for c in _TEXT_COLS]
    parts += [f"coalesce({c}::text, '')" for c in _JSON_COLS]
    return " || ' ' || ".join(parts)


def _folded_expr() -> str:
    return f"lower(translate({_doc_expr()}, '{_FOLD_SRC}', '{_FOLD_DST}'))"


def upgrade() -> None:
    # pg_trgm already enabled by 0013/0126; idempotent guard for safety.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute(
        f"""
        ALTER TABLE candidates
        ADD COLUMN IF NOT EXISTS search_doc_unaccented text
        GENERATED ALWAYS AS ({_folded_expr()}) STORED;
        """
    )

    # CONCURRENTLY requires running outside a transaction. Alembic wraps upgrades
    # in a transaction by default; end the implicit transaction before the DDL.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_candidates_search_doc_unaccent_trgm "
            "ON candidates USING GIN (search_doc_unaccented gin_trgm_ops);"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_candidates_search_doc_unaccent_trgm;"
        )
    op.execute("ALTER TABLE candidates DROP COLUMN IF EXISTS search_doc_unaccented;")
