"""Trzy rubryki rekrutacji: dni w biurze (kandydat + oferta) i remote_policy bez domyślnej.

Rekrutacja w firmie stoi na trzech rubrykach: must-have, stawka PLN/h,
obecność w biurze (dni/tydz. + miasto). Dwie pierwsze mają już kolumny
(``rate_budget_hourly``, must-skills); trzeciej brakowało zupełnie po stronie
kandydata, a po stronie oferty ``remote_policy`` miało twardą domyślną
``hybrid`` wstawianą na sztywno przez importer Traffita — więc KAŻDA
zaimportowana oferta „chciała biura", nawet gdy nikt tego nie potwierdził.
Kandydat bez zadeklarowanego limitu i oferta bez zadeklarowanego trybu mają
być nieodróżnialne od siebie: „nieznane", nie „hybrydowe".

Cztery zmiany schematu:
1. ``candidates.max_onsite_days_per_week`` (nowa) — 0 = wyłącznie zdalnie.
2. ``jobs.onsite_days_per_week`` (nowa) — wymagana liczba dni w biurze.
3. ``jobs.remote_policy`` traci ``NOT NULL``.
4. ``jobs.remote_policy`` traci domyślną ``'hybrid'``.

I cztery jednorazowe naprawy danych:

- **S1** — literówka trybu pracy kandydata. Formularz zapisywał ``on_site``,
  backend porównywał z ``onsite`` bez walidacji, więc kandydaci, którzy
  wprost zaznaczyli „Stacjonarnie", byli liczeni jako odmawiający pracy
  biurowej i znikali z filtra „Stacjonarnie". Predykat jest idempotentny —
  bez markera.
- **S2** — zdejmuje stempel ``hybrid`` z ofert Traffita, które nikt ręcznie
  nie edytował (``activities`` bez wpisu ``updated`` niosącego klucz
  ``remote_policy`` w ``details``) — ręczna edycja jest nietykalna, nawet
  jeśli ustawiła z powrotem ``hybrid``.
- **S3** — przenosi to, co Champion już wie (budżet, dni w biurze, tryb,
  miasto), do kolumn oferty czytanych przez scoring i dealbreakery — FILL
  EMPTY, nigdy nie nadpisuje ręcznie wpisanej wartości. Musi iść PO S2:
  inaczej odstemplowanie i backfill Championa rywalizowałyby o tę samą
  kolumnę w nieprzewidywalnej kolejności.
- **S4** — kandydat, którego notatki AI oznaczyły jako ``remote_only``, ale
  który nie ma jeszcze limitu dni w biurze, dostaje ``0`` (te dwa fakty
  zawsze się zgadzają — „tylko zdalnie" i „zero dni w biurze" to to samo
  zdanie o tej samej osobie).

Zero CHECK-ów na zakres 0..7 — wejście jest już typowane po obu stronach
(Pydantic ``ge=0, le=7``, ``ChampionBasics`` też, ekstraktor notatek przycina,
SQL-owe fixy używają ``~ '^[0-7]$'``). CHECK na 57k-wierszowej gorącej tabeli
przy każdym boocie kontenera to klasa incydentu z 03.09.2026 — nie warto tu
tego ryzyka dla kolumny, którą i tak pilnuje typ w aplikacji.

Zdublowane w safety-net ``entrypoint.sh`` — prod alembic bywa orphaned.

Revision ID: 0278_office_presence_rubric
Revises: 0277_recruitment_allocation
"""

from alembic import op

revision = "0278_office_presence_rubric"
down_revision = "0277_recruitment_allocation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Surowy SQL, bit w bit ten sam co lustro w ``entrypoint.sh``.
    op.execute(
        "ALTER TABLE candidates "
        "ADD COLUMN IF NOT EXISTS max_onsite_days_per_week INTEGER NULL"
    )
    op.execute(
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS onsite_days_per_week INTEGER NULL"
    )
    # Idempotentne — no-op, gdy kolumna jest już nullable / bez domyślnej.
    op.execute("ALTER TABLE jobs ALTER COLUMN remote_policy DROP NOT NULL")
    op.execute("ALTER TABLE jobs ALTER COLUMN remote_policy DROP DEFAULT")

    # S1 — `on_site` -> `onsite` w `candidates.preferences.remote_modes`.
    # Predykat jest idempotentny (drugi bieg nie znajduje już `on_site`),
    # więc świadomie BEZ markera w app_settings.
    op.execute(
        """
        UPDATE candidates
        SET preferences = jsonb_set(preferences, '{remote_modes}',
              (SELECT COALESCE(jsonb_agg(DISTINCT CASE WHEN m = 'on_site' THEN 'onsite' ELSE m END), '[]'::jsonb)
                 FROM jsonb_array_elements_text(preferences->'remote_modes') AS m))
        WHERE jsonb_typeof(preferences->'remote_modes') = 'array'
          AND preferences->'remote_modes' ? 'on_site'
        """
    )

    # S2 — zdejmuje stempel importera Traffita z ofert, których nikt ręcznie
    # nie edytował. Marker chroni przed ponownym odstemplowaniem oferty, na
    # której admin świadomie ustawił `hybrid` po tym biegu.
    op.execute(
        """
        WITH marker AS (
            INSERT INTO app_settings (key, value)
            VALUES ('0278_traffit_remote_policy_unstamped', 'true'::jsonb)
            ON CONFLICT (key) DO NOTHING
            RETURNING key
        )
        UPDATE jobs SET remote_policy = NULL
        WHERE external_source = 'traffit' AND remote_policy = 'hybrid'
          AND NOT EXISTS (
              SELECT 1 FROM activities a
              WHERE a.entity_type = 'job' AND a.entity_id = jobs.id
                AND a.action = 'updated' AND a.details ? 'remote_policy'
          )
          AND EXISTS (SELECT 1 FROM marker)
        """
    )

    # S3 — Champion -> kolumny oferty (FILL_EMPTY). MUSI iść PO S2, inaczej
    # odstemplowanie i ten backfill rywalizowałyby o tę samą kolumnę.
    # `champion_view.basics()` podnosi legacy pola płasko, ale nie
    # `onsite_days_per_week` (tylko w `basics`), a legacy lokalizacja biura
    # to top-level `location` — stąd COALESCE obu kształtów JSONB.
    # Zagnieżdżony CASE jest celowy: Postgres nie gwarantuje kolejności
    # operandów AND, więc rzutowanie ::numeric siedzi w gałęzi za regexem.
    op.execute(
        r"""
        WITH marker AS (
            INSERT INTO app_settings (key, value)
            VALUES ('0278_champion_basics_to_job_columns', 'true'::jsonb)
            ON CONFLICT (key) DO NOTHING
            RETURNING key
        ),
        src AS (
          SELECT id,
            NULLIF(trim(COALESCE(champion_profile->'basics'->>'rate_value', champion_profile->>'rate_value')), '') AS rate_txt,
            NULLIF(trim(champion_profile->'basics'->>'onsite_days_per_week'), '') AS days_txt,
            lower(trim(COALESCE(champion_profile->'basics'->>'work_mode', champion_profile->>'work_mode'))) AS wm,
            NULLIF(trim(COALESCE(champion_profile->'basics'->>'candidate_location_pref', champion_profile->>'location')), '') AS loc
          FROM jobs WHERE jsonb_typeof(champion_profile) = 'object' AND champion_profile <> '{}'::jsonb)
        UPDATE jobs j SET
          rate_budget_hourly = COALESCE(j.rate_budget_hourly,
             CASE WHEN s.rate_txt ~ '^[0-9]+(\.[0-9]+)?$'
                  THEN (CASE WHEN s.rate_txt::numeric > 0 AND s.rate_txt::numeric <= 2000 THEN s.rate_txt::numeric(8,2) END) END),
          onsite_days_per_week = COALESCE(j.onsite_days_per_week, CASE WHEN s.days_txt ~ '^[0-7]$' THEN s.days_txt::int END),
          remote_policy = COALESCE(j.remote_policy,
             CASE WHEN s.wm LIKE 'zdaln%' THEN 'remote'::remotepolicy
                  WHEN s.wm LIKE 'hybryd%' THEN 'hybrid'::remotepolicy
                  WHEN s.wm LIKE 'stacjonar%' THEN 'onsite'::remotepolicy END),
          location = COALESCE(j.location, left(s.loc, 255))
        FROM src s WHERE s.id = j.id AND EXISTS (SELECT 1 FROM marker)
        """
    )

    # S4 — kandydat oznaczony przez notatki jako `remote_only` bez jeszcze
    # ustawionego limitu dostaje `0` (oba fakty opisują to samo).
    op.execute(
        """
        WITH marker AS (
            INSERT INTO app_settings (key, value)
            VALUES ('0278_remote_only_onsite_days_zero', 'true'::jsonb)
            ON CONFLICT (key) DO NOTHING
            RETURNING key
        )
        UPDATE candidates SET max_onsite_days_per_week = 0
        WHERE max_onsite_days_per_week IS NULL AND jsonb_typeof(cv_extracted_data) = 'object'
          AND cv_extracted_data->'_notes_insights'->'preferences'->>'remote_only' = 'true'
          AND EXISTS (SELECT 1 FROM marker)
        """
    )


def downgrade() -> None:
    # S1-S4 są nieodwracalne (naprawy danych, nie stan schematu) — downgrade
    # cofa tylko schemat, tak jak przed tą migracją.
    op.execute("UPDATE jobs SET remote_policy = 'hybrid' WHERE remote_policy IS NULL")
    op.execute("ALTER TABLE jobs ALTER COLUMN remote_policy SET NOT NULL")
    op.execute("ALTER TABLE jobs ALTER COLUMN remote_policy SET DEFAULT 'hybrid'")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS onsite_days_per_week")
    op.execute("ALTER TABLE candidates DROP COLUMN IF EXISTS max_onsite_days_per_week")
