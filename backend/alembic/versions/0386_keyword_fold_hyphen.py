"""Korpus złożony, wersja 2: myślnik jako spacja w ``candidate_keyword_fold``.

Revision ID: 0386_keyword_fold_hyphen
Revises: 0385_keyword_fold_fts

Porównanie starej i nowej ścieżki słów kluczowych na produkcji (26.09.2026):
parser tsvector rozbija „CI/CD-driven” na ``cd-driven``, ``cd``, ``driven``,
więc „cd” ląduje o pozycję dalej i fraza „ci/cd” nie łączy się z tekstem.
Myślnik zamieniamy na spację po obu stronach (dokument i zapytanie przechodzą
przez tę samą funkcję). Tylko DDL funkcji — zapisane kolumny przelicza pętla
``keyword_corpus_backfill`` (``FOLD_VERSION``), bez przepisywania tabel
w migracji. Lustro: ``entrypoint.sh`` (``keyword_corpus.schema_ddl()``).
"""

from alembic import op

from app.services import keyword_corpus as kc

revision = "0386_keyword_fold_hyphen"
down_revision = "0385_keyword_fold_fts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(kc.FOLD_FUNCTION_DDL)


# Runda 7 (R7-X3-3): ``FOLD_FUNCTION_DDL`` jest już w wersji 3, więc dawne
# ``replace("'/\\-', '   '", …)`` nic nie trafiało i downgrade zakładał
# z powrotem funkcję v3 ze znacznikiem v3. Wersję 1 składamy jawnie z v3.
_V3_HEAD = f"""    s text := coalesce(t, '');
BEGIN
    IF s ~ '{kc.COMBINING_CLASS_PG}' THEN
        s := regexp_replace(normalize(s, NFC), '{kc.COMBINING_CLASS_PG}+', '', 'g');
    END IF;
    s := translate(lower(translate(s, '{kc.FOLD_SRC}', '{kc.FOLD_DST}')), '/\\-<>', '     ');
"""
_V1_HEAD = f"""    s text := translate(
        lower(translate(coalesce(t, ''), '{kc.FOLD_SRC}', '{kc.FOLD_DST}')), '/\\', '  '
    );
BEGIN
"""


def v1_function_ddl() -> str:
    assert _V3_HEAD in kc.FOLD_FUNCTION_DDL, "zmieniła się funkcja — popraw downgrade"
    return kc.FOLD_FUNCTION_DDL.replace(_V3_HEAD, _V1_HEAD).replace(
        kc.fold_version_marker(3), kc.fold_version_marker(1)
    )


def downgrade() -> None:
    # Wersja 1 różni się myślnikiem (i tym, co dołożyła 0387); po cofnięciu
    # pętla przeliczy kolumny (inna wersja w app_settings niż w kodzie).
    op.execute(v1_function_ddl())
