"""Korpus słów kluczowych kandydata — to, w czym szuka „Zawiera wszystkie / którekolwiek / żadne”.

Powód (porównanie z Traffitem na produkcji, 22.09.2026, próbka 3 250 osób ×
18 zapytań): NEXUS znajdował ~84% osób, które znajduje Traffit, a ~8% jego
wyników Traffit nie zwracał. Rozjazd nie siedział w dopasowaniu słów, tylko
w KORPUSIE — polach, po których szukamy:

* ``search_fts`` / ``search_doc`` (0126, 0143) biorą ``ai_summary``. Podsumowanie
  AI wymienia branże, których nie ma w CV: „bankowość” dawała 9 794 osoby, Traffit
  810 — 467 z 494 osób „tylko w NEXUSIE” w próbce miało to słowo WYŁĄCZNIE
  w podsumowaniu AI.
* JSON-y są indeksowane jako surowy tekst, z kluczami i poziomami:
  ``{"name": "Java", "level": "junior"}``. „junior” miało 26 609 osób (poziom
  umiejętności), więc „java NIE junior” dawało 4 579 zamiast ~11 tys.
* Pola własne Traffita (``cv_extracted_data.traffit_technologie``,
  ``traffit_Position``, ``traffit_certificates``, ``traffit_previous_employers``…)
  i „Kandydat o sobie” (``profile_about``) nie były przeszukiwane wcale — a to
  z nich Traffit brał dużą część trafień („kafka”: 21 z 32 osób „tylko
  w Trafficie” miało słowo wyłącznie w ``traffit_technologie``).

Ten moduł jest JEDNYM źródłem listy pól: SQL-a triggera
(``profile_text_sql``) oraz lustra w Pythonie do wycinków pod wynikiem
(``json_text``, ``title_text``, ``skills_text``). Kolumny:

* ``candidates.keyword_doc`` — tekst profilu (bez CV) bez polskich znaków,
  małymi literami; indeks trigramowy, regex z granicą słowa i wariant bez
  polskich znaków.
* ``candidates.keyword_fts`` — ``to_tsvector('simple', profil + CV)``; indeks GIN,
  całe słowa i frazy.

Obie utrzymuje trigger (migracja 0346), nie kolumna generowana: ``ADD COLUMN …
GENERATED STORED`` przepisałby tabelę z 171 MB CV pod blokadą ``ACCESS
EXCLUSIVE``. Istniejące wiersze uzupełnia pętla ``keyword_corpus_backfill`` po
starcie (NIE migracja — backfill 0143 w starcie kontenera dał 6 minut 502).
Do czasu jej końca zapytania dla wierszy bez korpusu wracają do starych kolumn
(``ready()``).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Klucze w elementach tablic JSON, które niosą TREŚĆ. Reszta to metadane
# (daty, poziomy, lata, źródło, znaczniki) — wpuszczone do korpusu dopasowywały
# się u wszystkich („junior”, „cv”, „years”).
EXPERIENCE_KEYS: tuple[str, ...] = (
    "role",
    "company",
    "desc",
    "technologies",
    "location",
    "client",
)
SKILL_KEYS: tuple[str, ...] = ("name",)
EDUCATION_KEYS: tuple[str, ...] = ("school", "field", "degree")
LANGUAGE_KEYS: tuple[str, ...] = ("lang", "name")
# Tagi: wyłącznie napisy. Obiekty to źródła z Traffita
# (``{"type": "traffit_source", "domain": "linkedin.com"}``) — „linkedin”
# znalazłby wtedy 90 tys. osób.
TAG_KEYS: tuple[str, ...] = ()

# Pola własne Traffita w ``cv_extracted_data`` (``mappers.traffit_employee_to_candidate``).
# ``traffit_experience`` („5+”, „Poniżej 2”) to koszyk stażu, nie tekst.
TRAFFIT_TEXT_KEYS: tuple[str, ...] = (
    "traffit_Position",
    "traffit_technologie",
    "traffit_certificates",
    "traffit_previous_employers",
    "traffit_education",
    "traffit_nationality",
)

PLAIN_COLUMNS: tuple[str, ...] = (
    "name",
    "lastname",
    "email",
    "phone",
    "location",
    "city",
    "linkedin_current_title",
    "linkedin_current_company",
    "engagement_notes",
    "profile_about",
)

JSON_COLUMNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("experience", EXPERIENCE_KEYS),
    ("skills", SKILL_KEYS),
    ("tags", TAG_KEYS),
    ("education", EDUCATION_KEYS),
    ("languages", LANGUAGE_KEYS),
)

# Kolumny, których zmiana przelicza korpus (lista ``UPDATE OF`` triggera).
# ``keyword_doc`` na końcu: backfill robi ``SET keyword_doc = NULL`` i to ono
# odpala trigger dla wierszy sprzed migracji.
SOURCE_COLUMNS: tuple[str, ...] = (
    PLAIN_COLUMNS
    + tuple(col for col, _ in JSON_COLUMNS)
    + ("cv_extracted_data", "raw_cv_text", "keyword_doc")
)

CV_CAP = 200_000
# Profil bez CV też bywa długi (opisy stanowisk) — sufit chroni limit 1 MB tsvector.
PROFILE_CAP = 200_000

FOLD_SRC = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"
FOLD_DST = "acelnoszzACELNOSZZ"

JSON_TEXT_FUNCTION = "candidate_keyword_json_text"
TRIGGER_FUNCTION = "candidates_keyword_corpus_refresh"
TRIGGER_NAME = "trg_candidates_keyword_corpus"
FTS_INDEX = "ix_candidates_keyword_fts"
DOC_INDEX = "ix_candidates_keyword_doc_trgm"


def _sql_array(keys: tuple[str, ...]) -> str:
    if not keys:
        return "ARRAY[]::text[]"
    return "ARRAY[" + ", ".join(f"'{k}'" for k in keys) + "]"


JSON_TEXT_FUNCTION_DDL = f"""
CREATE OR REPLACE FUNCTION {JSON_TEXT_FUNCTION}(doc jsonb, keys text[])
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    -- Starsze importy zapisały listę jako JEDEN napis JSON
    -- ('["Go", "Rust"]') — bierzemy go w całości, jak dotąd search_fts.
    SELECT CASE WHEN jsonb_typeof(doc) = 'string' THEN doc #>> '{{}}' ELSE (
        SELECT string_agg(t, ' ')
        FROM (
            SELECT CASE
                       WHEN jsonb_typeof(e) = 'string' THEN e #>> '{{}}'
                       WHEN jsonb_typeof(e) = 'object' THEN (
                           SELECT string_agg(e ->> k, ' ') FROM unnest(keys) AS k
                       )
                   END AS t
            FROM jsonb_array_elements(
                CASE WHEN jsonb_typeof(doc) = 'array' THEN doc ELSE '[]'::jsonb END
            ) AS e
        ) AS s
    ) END
$$;
"""


def profile_text_sql(prefix: str = "NEW.") -> str:
    """Tekst profilu (bez CV) jako wyrażenie SQL. ``prefix`` = ``NEW.`` w triggerze."""
    parts = [f"{prefix}{col}" for col in PLAIN_COLUMNS]
    parts += [
        f"{JSON_TEXT_FUNCTION}({prefix}{col}, {_sql_array(keys)})"
        for col, keys in JSON_COLUMNS
    ]
    parts += [
        f"CASE WHEN jsonb_typeof({prefix}cv_extracted_data) = 'object' "
        f"THEN {prefix}cv_extracted_data ->> '{key}' END"
        for key in TRAFFIT_TEXT_KEYS
    ]
    return f"left(concat_ws(' ', {', '.join(parts)}), {PROFILE_CAP})"


TRIGGER_FUNCTION_DDL = f"""
CREATE OR REPLACE FUNCTION {TRIGGER_FUNCTION}()
RETURNS trigger AS $$
DECLARE
    profile text := {profile_text_sql("NEW.")};
BEGIN
    NEW.keyword_doc := lower(translate(profile, '{FOLD_SRC}', '{FOLD_DST}'));
    NEW.keyword_fts := to_tsvector(
        'simple',
        profile || ' ' || coalesce(left(NEW.raw_cv_text, {CV_CAP}), '')
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

TRIGGER_DDL = f"""
CREATE OR REPLACE TRIGGER {TRIGGER_NAME}
BEFORE INSERT OR UPDATE OF {", ".join(SOURCE_COLUMNS)} ON candidates
FOR EACH ROW EXECUTE FUNCTION {TRIGGER_FUNCTION}();
"""

COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS keyword_doc text",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS keyword_fts tsvector",
)

INDEX_DDL: tuple[str, ...] = (
    f"CREATE INDEX {{concurrently}} IF NOT EXISTS {FTS_INDEX} "
    "ON candidates USING GIN (keyword_fts)",
    f"CREATE INDEX {{concurrently}} IF NOT EXISTS {DOC_INDEX} "
    "ON candidates USING GIN (keyword_doc gin_trgm_ops)",
)


def index_ddl(*, concurrently: bool) -> list[str]:
    word = "CONCURRENTLY" if concurrently else ""
    return [stmt.format(concurrently=word) for stmt in INDEX_DDL]


# Wiersz bez korpusu = ``keyword_doc IS NULL`` (trigger zawsze wpisuje napis,
# choćby pusty). ``SET keyword_doc = NULL`` odpala trigger (``UPDATE OF``),
# który od razu wylicza obie kolumny.
# ``RETURNING`` czyta wartość PO triggerze: wiersz, który wrócił z NULL-em,
# znaczy, że triggera nie ma (siatka DDL przegrała blokadę) — pętla wtedy
# staje, zamiast w nieskończoność przepisywać NULL na NULL.
BACKFILL_BATCH_SQL = (
    "UPDATE candidates SET keyword_doc = NULL WHERE id IN ("
    " SELECT id FROM candidates WHERE keyword_doc IS NULL ORDER BY id LIMIT :limit"
    ") RETURNING keyword_doc IS NOT NULL"
)
PENDING_EXISTS_SQL = (
    "SELECT EXISTS (SELECT 1 FROM candidates WHERE keyword_doc IS NULL)"
)


# ── Gotowość (czy wszystkie wiersze mają korpus) ─────────────────────────────

_ready = False


def ready() -> bool:
    """Wszystkie wiersze mają korpus → zapytania nie potrzebują starych kolumn.

    Stan procesu (backend to jeden uvicorn). Ustawia go pętla backfillu; po
    restarcie wraca na ``False``, dopóki pętla nie sprawdzi bazy (pierwsze
    sprawdzenie jest natychmiast po starcie). ``False`` nie psuje wyników —
    tylko dokłada gałąź zapasową po starych kolumnach dla wierszy bez korpusu.
    """
    return _ready


def mark_ready(value: bool = True) -> None:
    global _ready
    _ready = value


# ── Lustro w Pythonie (wycinki pod wynikiem) ─────────────────────────────────


def json_text(doc: Any, keys: tuple[str, ...]) -> str:
    """Lustro ``candidate_keyword_json_text``: napisy + wartości wskazanych kluczy."""
    if isinstance(doc, str):
        return doc
    if not isinstance(doc, list):
        return ""
    out: list[str] = []
    for item in doc:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            for key in keys:
                value = item.get(key)
                if value is None:
                    continue
                if isinstance(value, (list, dict)):
                    out.append(json_join(value))
                else:
                    out.append(str(value))
    return " ".join(s for s in out if s)


def json_join(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(json_join(v) for v in value if v is not None)
    if isinstance(value, dict):
        return ", ".join(json_join(v) for v in value.values() if v is not None)
    return str(value)


def traffit_value(candidate: Any, key: str) -> str:
    data = getattr(candidate, "cv_extracted_data", None)
    if not isinstance(data, dict):
        return ""
    value = data.get(key)
    if value is None:
        return ""
    return json_join(value) if isinstance(value, (list, dict)) else str(value)


def title_text(candidate: Any, roles: Optional[str] = None) -> str:
    """Stanowiska: role z doświadczenia + stanowisko z Traffita."""
    parts = [roles or "", traffit_value(candidate, "traffit_Position")]
    return " · ".join(p for p in parts if p)


def skills_text(candidate: Any) -> str:
    """Umiejętności: nazwy (bez poziomów) + technologie z Traffita."""
    parts = [
        json_text(getattr(candidate, "skills", None), SKILL_KEYS),
        traffit_value(candidate, "traffit_technologie"),
    ]
    return " · ".join(p for p in parts if p)
