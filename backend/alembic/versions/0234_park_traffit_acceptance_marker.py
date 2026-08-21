"""Marker „[akcept]" z imienia: parkowany jako tag, potem zdejmowany.

Revision ID: 0234_park_traffit_acceptance_marker
Revises: 0233_order_lifecycle_cost_and_dl_alerts
Create Date: 2026-08-18

Trzeci marker z tej samej rodziny co „[zatrudniony]" (0165) i „[BLACKLIST]"
(0232): Traffit nie miał pola, więc rekruter wkleił fakt w imię —
„[akcept]Mateusz", „[akcept] Rajan". Znaczy „zaakceptowany przez klienta".

Różnica wobec 0232 jest sednem tej migracji. Blacklistę dało się przenieść do
`candidates.status`, bo to cecha OSOBY. Akceptacja jest faktem z KONKRETNEJ
rekrutacji: pole na nią istnieje (`PipelineStage.acceptance` — „Klient
akceptuje kandydata"), ale wiersz etapu wymaga oferty i daty, a marker w imieniu
nie niesie ani jednego. Dopisanie etapu „na oko" byłoby sfabrykowaniem historii
rekrutacyjnej — a z niej liczone są lejek, KPI i premie. Dlatego:

  1. Osoby, które MAJĄ już realny etap `acceptance` albo dalszy
     (`negotiation` / `onboarding` / `hired`), dostają tylko zdjęcie markera —
     fakt jest już zapisany strukturalnie, marker był jego powtórzeniem.
  2. Osoby BEZ takiego etapu dostają trwały tag (wzorzec z 0165: `tags` nie są
     nadpisywane przez upsert Traffita), który zachowuje sygnał i robi z nich
     listę do przypisania przez człowieka.

Idempotentna: powtórny bieg nie znajduje markerów, a tag jest strzeżony przed
duplikatem. Dane, nie schemat — downgrade pusty.
"""

from alembic import op


revision = "0234_park_traffit_acceptance_marker"
down_revision = "0233_order_lifecycle_cost_and_dl_alerts"
branch_labels = None
depends_on = None


# Lustro `mappers._STATUS_MARKER_RE` zawężone do rodziny „akcept". Grupy
# ZWYKŁE `(...)`, nie `(?:...)` — `op.execute()` opakowuje SQL w SQLAlchemy
# `text()`, które czyta `:` w `(?:` jako parametr bindowany.
_WORD = r"(akcept[a-ząćęłńóśźż]*)"
_MARKER = r"[[(/]\s*" + _WORD + r"\s*[])/]?" + r"|" + r"[[(/]?\s*" + _WORD + r"\s*[])/]"

# Akceptacja klienta zapisana tam, gdzie jej miejsce. „Kiedykolwiek osiągnięty",
# nie „bieżący": klient zaakceptował kandydata także wtedy, gdy proces poszedł
# potem dalej albo się rozsypał.
#
# DWA źródła, bo enum sam nie wystarcza: importer Traffita mapuje TYPY stanów
# (`end-good` → `hired`, `client_verification` → `cv_sent`) i **w praktyce nigdy
# nie produkuje `acceptance`**. Fakt „Zaakceptowany" żyje w NAZWIE etapu
# szablonu (`pipeline_stage_defs.name`) — to ją widzi rekruter w interfejsie.
# Pytanie wyłącznie o enum parkowałoby tag komuś, kto ma akceptację widoczną
# na ekranie, czyli kazałoby „przypisać do rekrutacji" coś już przypisanego.
_HAS_ACCEPTANCE_STAGE = """
    EXISTS (
        SELECT 1 FROM candidate_stages cs
        LEFT JOIN pipeline_stage_defs psd ON psd.id = cs.stage_def_id
        WHERE cs.candidate_id = cand.id
          AND (
              cs.stage::text IN ('acceptance', 'negotiation', 'onboarding', 'hired')
              OR psd.name ILIKE '%akcept%'
              OR psd.terminal_type::text = 'hired'
          )
    )
"""

_PARK_TAG = '["Traffit: zaakceptowany przez klienta (do przypisania do rekrutacji)"]'


def upgrade() -> None:
    # 1. Zachowaj sygnał u tych, u których marker jest JEDYNYM jego nośnikiem.
    op.execute(
        f"""
        UPDATE candidates cand
        SET tags = COALESCE(cand.tags, '[]'::jsonb) || '{_PARK_TAG}'::jsonb
        WHERE (cand.name ~* '{_MARKER}' OR cand.lastname ~* '{_MARKER}')
          AND jsonb_typeof(COALESCE(cand.tags, '[]'::jsonb)) = 'array'
          AND NOT (COALESCE(cand.tags, '[]'::jsonb) @> '{_PARK_TAG}'::jsonb)
          AND NOT ({_HAS_ACCEPTANCE_STAGE})
        """
    )

    # 2. Marker znika z imienia i nazwiska.
    op.execute(
        rf"""
        UPDATE candidates
        SET name = COALESCE(NULLIF(btrim(regexp_replace(
                       regexp_replace(name, '{_MARKER}', ' ', 'gi'),
                       '\s+', ' ', 'g'), ' -–,;/'), ''), '?'),
            lastname = COALESCE(NULLIF(btrim(regexp_replace(
                       regexp_replace(lastname, '{_MARKER}', ' ', 'gi'),
                       '\s+', ' ', 'g'), ' -–,;/'), ''), '?')
        WHERE name ~* '{_MARKER}' OR lastname ~* '{_MARKER}'
        """
    )


def downgrade() -> None:
    # Porządkowanie danych: oryginalnego tekstu markera nie da się odtworzyć.
    pass
