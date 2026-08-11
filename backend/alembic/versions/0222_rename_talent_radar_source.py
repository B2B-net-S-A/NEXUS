"""Źródło importu `talent_radar` → `tr_legacy`, żeby nazwa została dla modułu.

Talent Radar to od teraz nazwa produktowa wyszukiwarki ad-hoc
(`/api/talent-radar/search`). Ta sama nazwa oznaczała dotąd system źródłowy,
z którego jednorazowo zaciągnięto ludzi — i obie rzeczy zaczęły sąsiadować
w routingu (`/api/admin/import-talent-radar` obok `/api/talent-radar/search`).
Dwuznaczność w kodzie, w zapytaniach do bazy i w rozmowach z zespołem.

SKALA, ZMIERZONA A NIE ZAŁOŻONA. Docstring importera mówi o 40 745 wierszach
pobranych z Supabase, ale importer SCALA ludzi w istniejące rekordy — jako
`external_source='talent_radar'` ląduje wyłącznie ten, kto jest naprawdę nowy.
Na produkcji (2026-08-11):

    candidates.external_source = 'talent_radar'                    15 wierszy
    candidate_languages.provenance = 'talent_radar'                 0
    candidate_source_identity_reviews.source_kind='talent_radar_cv' 0

Czyli piętnaście wierszy i dwa CHECK-i, nie migracja na czterdzieści tysięcy.

OBA CHECK-I PRZYJMUJĄ STARĄ I NOWĄ WARTOŚĆ. To nie jest niezdecydowanie:
rollback w tym repo znaczy redeploy poprzedniego obrazu, a tamten importer pisze
`talent_radar`. Zawężenie od razu sprawiłoby, że cofnięcie się wywala na
naruszeniu constraintu. Starą wartość można wyciąć osobnym PR-em, gdy nowa
utrzyma się na prodzie — i wtedy będzie to zmiana bez żadnego okna ryzyka.

Revision ID: 0222_rename_talent_radar_source
Revises: 0221_candidate_external_deleted
"""

from alembic import op

revision = "0222_rename_talent_radar_source"
down_revision = "0221_candidate_external_deleted"
branch_labels = None
depends_on = None


_LANG_PROVENANCE = (
    "'manual', 'cv', 'traffit', 'talent_radar', 'tr_legacy', "
    "'csv', 'legacy', 'unknown'"
)
_REVIEW_KIND = "'note', 'document', 'legacy_cv', 'talent_radar_cv', 'tr_legacy_cv'"


def upgrade() -> None:
    # Widen first, rewrite second: at no point may a writer hit a constraint
    # that rejects the value it is about to write.
    op.execute(
        "ALTER TABLE candidate_languages "
        "DROP CONSTRAINT IF EXISTS ck_candidate_languages_provenance"
    )
    op.execute(
        "ALTER TABLE candidate_languages ADD CONSTRAINT "
        "ck_candidate_languages_provenance "
        f"CHECK (provenance IN ({_LANG_PROVENANCE}))"
    )
    op.execute(
        "ALTER TABLE candidate_source_identity_reviews "
        "DROP CONSTRAINT IF EXISTS ck_candidate_source_identity_review_kind"
    )
    op.execute(
        "ALTER TABLE candidate_source_identity_reviews ADD CONSTRAINT "
        "ck_candidate_source_identity_review_kind "
        f"CHECK (source_kind IN ({_REVIEW_KIND}))"
    )

    op.execute(
        "UPDATE candidates SET external_source = 'tr_legacy' "
        "WHERE external_source = 'talent_radar'"
    )
    op.execute(
        "UPDATE candidate_languages SET provenance = 'tr_legacy' "
        "WHERE provenance = 'talent_radar'"
    )
    op.execute(
        "UPDATE candidate_source_identity_reviews SET source_kind = 'tr_legacy_cv' "
        "WHERE source_kind = 'talent_radar_cv'"
    )


def downgrade() -> None:
    # The CHECKs already accept both spellings, so only the data moves back.
    op.execute(
        "UPDATE candidates SET external_source = 'talent_radar' "
        "WHERE external_source = 'tr_legacy'"
    )
    op.execute(
        "UPDATE candidate_languages SET provenance = 'talent_radar' "
        "WHERE provenance = 'tr_legacy'"
    )
    op.execute(
        "UPDATE candidate_source_identity_reviews SET source_kind = 'talent_radar_cv' "
        "WHERE source_kind = 'tr_legacy_cv'"
    )
