"""Korpus złożony, wersja 3: znaki łączące w ``candidate_keyword_fold``.

Revision ID: 0387_keyword_fold_combining
Revises: 0386_keyword_fold_hyphen

Porównanie starej i nowej ścieżki słów kluczowych na produkcji (26.09.2026):
133 CV i 41 notatek zapisują polskie litery jako literę i osobny znak akcentu
(„o” + U+0301), więc „łódź” ani „zarządzanie” ich nie znajdowały. Przed
składaniem tekst przechodzi przez NFC, a pozostałe znaki łączące znikają.
„<” i „>” to spacja: ukośnik jako spacja (wersja 1) zamieniał `</script>`
w `< script>`, parser tsvector nie znajdował końca „skryptu” i połykał resztę CV
(4 CV, 11 906 znaków, m.in. „Łódź” — stara ścieżka ich nie traciła).
Tylko DDL funkcji — zapisane kolumny przelicza pętla ``keyword_corpus_backfill``
(``FOLD_VERSION``). Lustro: ``entrypoint.sh`` (``keyword_corpus.schema_ddl()``).
"""

from alembic import op

from app.services import keyword_corpus as kc

revision = "0387_keyword_fold_combining"
down_revision = "0386_keyword_fold_hyphen"
branch_labels = None
depends_on = None

_V3_HEAD = f"""    s text := coalesce(t, '');
BEGIN
    IF s ~ '{kc.COMBINING_CLASS_PG}' THEN
        s := regexp_replace(normalize(s, NFC), '{kc.COMBINING_CLASS_PG}+', '', 'g');
    END IF;
    s := translate(lower(translate(s, '{kc.FOLD_SRC}', '{kc.FOLD_DST}')), '/\\-<>', '     ');
"""
_V2_HEAD = f"""    s text := translate(
        lower(translate(coalesce(t, ''), '{kc.FOLD_SRC}', '{kc.FOLD_DST}')), '/\\-', '   '
    );
BEGIN
"""


def upgrade() -> None:
    op.execute(kc.FOLD_FUNCTION_DDL)


def downgrade() -> None:
    # Wersja 2 różni się wyłącznie znakami łączącymi i „<>”; po cofnięciu
    # pętla przeliczy kolumny (inna wersja w app_settings niż w kodzie).
    assert _V3_HEAD in kc.FOLD_FUNCTION_DDL, "zmieniła się funkcja — popraw downgrade"
    op.execute(kc.FOLD_FUNCTION_DDL.replace(_V3_HEAD, _V2_HEAD))
