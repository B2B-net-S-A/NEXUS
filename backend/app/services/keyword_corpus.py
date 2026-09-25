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

Obie utrzymuje trigger (migracja 0350), nie kolumna generowana: ``ADD COLUMN …
GENERATED STORED`` przepisałby tabelę z 171 MB CV pod blokadą ``ACCESS
EXCLUSIVE``. Istniejące wiersze uzupełnia pętla ``keyword_corpus_backfill`` po
starcie (NIE migracja — backfill 0143 w starcie kontenera dał 6 minut 502).
Do czasu jej końca zapytania dla wierszy bez korpusu wracają do starych kolumn
(``ready()``).

Korpus złożony (migracja 0385, audyt szybkości 25.09.2026):

* ``candidates.keyword_fold_fts`` — ``to_tsvector('simple', fold(profil + CV))``,
  gdzie ``fold`` (``candidate_keyword_fold``) zdejmuje polskie znaki, zmienia
  ukośnik na spację i zapisuje ``c++``/``c#``/``f#``/``.net`` jako zwykłe słowa.
  Zastępuje w zapytaniu regex po ``keyword_doc``: ten rozpakowywał tekst z TOAST
  dla każdego pasującego kandydata (629 z 918 ms przy „java”, a dokładał 2 osoby
  z 15 710). Przy okazji: „krakow” znajduje „Kraków” także w CV, a „scrum” —
  zapis „Agile/Scrum” (parser tsvector trzyma go jako jedno słowo).
* ``notes.content_fold_fts`` — to samo dla notatek, po rozpakowaniu treści
  zapisanej przez import z Traffita jako JSON (``note_search_text``).

Zapytanie przechodzi na nowe kolumny dopiero przy ``KEYWORD_SEARCH_FOLDED_FTS``
i po uzupełnieniu (``fold_ready()`` / ``notes_ready()``).
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Optional

from app.services.keyword_terms import DOT_PREFIXES, WORD_CLASS_PG

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

FOLD_FUNCTION = "candidate_keyword_fold"
NOTE_TEXT_FUNCTION = "note_search_text"
NOTE_TRIGGER_FUNCTION = "notes_fold_fts_refresh"
NOTE_TRIGGER_NAME = "trg_notes_fold_fts"
FOLD_FTS_INDEX = "ix_candidates_keyword_fold_fts"
NOTE_FOLD_FTS_INDEX = "ix_notes_content_fold_fts"
NOTE_CAP = 200_000

# Słowa ze znakami, które parser tsvector gubi („c#” → „c”, „c++” → „c”). Zapis
# jako zwykłe słowo po obu stronach (dokument i zapytanie przechodzą przez tę
# samą funkcję SQL), więc „c#” znajduje „C#”, a nie każde „C”. Spacja po tokenie
# zachowuje dzisiejszą regułę: ``c++`` znajduje „C++17” (granica słowa tylko po
# stronie litery). ``.net`` jak ``pg_regex``: po granicy słowa albo po
# ``asp|ado|vb`` — „B2B.net” z klauzuli zgody zostaje nietknięte.
SPECIAL_TOKENS: tuple[tuple[str, str], ...] = (
    ("c++", "cplusplus"),
    ("c#", "csharp"),
    ("f#", "fsharp"),
    (".net", "dotnet"),
)
_DOT_PREFIXES_SQL = "|".join(DOT_PREFIXES)


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


# Tekst do korpusu złożonego: bez polskich znaków, małe litery, ukośnik jako
# spacja, słowa specjalne jako zwykłe słowa. Ta SAMA funkcja składa zapytanie
# (``phraseto_tsquery('simple', candidate_keyword_fold(:term))``), więc dokument
# i zapytanie nie mogą się rozjechać. Regexy tylko przy znakach, które je
# potrzebują — trigger liczy się przy każdym zapisie kandydata z importu.
FOLD_FUNCTION_DDL = rf"""
CREATE OR REPLACE FUNCTION {FOLD_FUNCTION}(t text)
RETURNS text LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE
    s text := translate(
        lower(translate(coalesce(t, ''), '{FOLD_SRC}', '{FOLD_DST}')), '/\', '  '
    );
BEGIN
    IF s ~ '[#+]|\.net' THEN
        s := regexp_replace(s, '(^|[^{WORD_CLASS_PG}])c\+\+', '\1 cplusplus ', 'g');
        s := regexp_replace(s, '(^|[^{WORD_CLASS_PG}])c#', '\1 csharp ', 'g');
        s := regexp_replace(s, '(^|[^{WORD_CLASS_PG}])f#', '\1 fsharp ', 'g');
        s := regexp_replace(
            s,
            '(^|[^{WORD_CLASS_PG}]|{_DOT_PREFIXES_SQL})\.net($|[^{WORD_CLASS_PG}])',
            '\1 dotnet \2',
            'g'
        );
    END IF;
    RETURN s;
END;
$$;
"""

# Import z Traffita zapisywał treść notatki jako cały obiekt JSON
# (``{"content":"<div>Toruń…","state":…}``) — Traffit wysyła ``content``
# jako NAPIS z JSON-em w środku, a promocja brała go w całości. Profil
# rozpakowuje to przy wyświetlaniu, ale wyszukiwanie widziało ``ń``
# zamiast „ń”. Tę funkcję woła promocja notatek (``traffit/importer.py``),
# indeks notatek i jednorazowa naprawa w pętli uzupełniania.
NOTE_UNWRAP_FUNCTION = "note_unwrap_json"
NOTE_UNWRAP_FUNCTION_DDL = f"""
CREATE OR REPLACE FUNCTION {NOTE_UNWRAP_FUNCTION}(c text)
RETURNS text LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE
    j jsonb;
BEGIN
    IF c IS NULL OR left(c, 1) <> '{{' OR NOT pg_input_is_valid(c, 'jsonb') THEN
        RETURN c;
    END IF;
    j := c::jsonb;
    IF jsonb_typeof(j) = 'object' AND jsonb_typeof(j -> 'content') = 'string'
       AND coalesce(j ->> 'content', '') <> '' THEN
        RETURN j ->> 'content';
    END IF;
    RETURN c;
END;
$$;
"""

NOTE_TEXT_FUNCTION_DDL = f"""
CREATE OR REPLACE FUNCTION {NOTE_TEXT_FUNCTION}(c text)
RETURNS text LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE
    s text := coalesce({NOTE_UNWRAP_FUNCTION}(c), '');
    j jsonb;
BEGIN
    -- Inny JSON (np. maile z formularza: to/subject/body) — same wartości tekstowe,
    -- bez kluczy, jak w korpusie kandydata.
    IF left(s, 1) = '{{' AND pg_input_is_valid(s, 'jsonb') THEN
        j := s::jsonb;
        s := coalesce((
            SELECT string_agg(v #>> '{{}}', ' ')
            FROM jsonb_path_query(j, 'strict $.** ? (@.type() == "string")') AS v
        ), '');
    END IF;
    s := regexp_replace(s, '<[^>]*>', ' ', 'g');
    s := replace(replace(replace(s, '&nbsp;', ' '), '&amp;', '&'), '&quot;', '"');
    s := replace(replace(replace(s, '&#39;', ''''), '&apos;', ''''), '&oacute;', 'ó');
    s := replace(s, '&Oacute;', 'Ó');
    s := regexp_replace(s, '&#?[[:alnum:]]+;', ' ', 'g');
    RETURN {FOLD_FUNCTION}(left(s, {NOTE_CAP}));
END;
$$;
"""

NOTE_TRIGGER_FUNCTION_DDL = f"""
CREATE OR REPLACE FUNCTION {NOTE_TRIGGER_FUNCTION}()
RETURNS trigger AS $$
BEGIN
    NEW.content_fold_fts := to_tsvector('simple', {NOTE_TEXT_FUNCTION}(NEW.content));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

NOTE_TRIGGER_DDL = f"""
CREATE OR REPLACE TRIGGER {NOTE_TRIGGER_NAME}
BEFORE INSERT OR UPDATE OF content ON notes
FOR EACH ROW EXECUTE FUNCTION {NOTE_TRIGGER_FUNCTION}();
"""

# Wersja z migracji 0350 — zamrożona: łańcuch migracji na świeżej bazie
# przechodzi przez 0351–0384 BEZ kolumny ``keyword_fold_fts``, więc trigger
# z 0350 nie może jej jeszcze dotykać. Bieżącą wersję zakłada 0385.
TRIGGER_FUNCTION_DDL_0350 = f"""
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
    NEW.keyword_fold_fts := to_tsvector(
        'simple',
        {FOLD_FUNCTION}(profile || ' ' || coalesce(left(NEW.raw_cv_text, {CV_CAP}), ''))
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


# Korpus złożony (0385). Osobno od COLUMN_DDL/INDEX_DDL, bo tamte czyta
# migracja 0350 — historia migracji nie może zmieniać znaczenia.
FOLD_COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS keyword_fold_fts tsvector",
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS content_fold_fts tsvector",
)
FOLD_FUNCTION_DDLS: tuple[str, ...] = (
    FOLD_FUNCTION_DDL,
    NOTE_UNWRAP_FUNCTION_DDL,
    NOTE_TEXT_FUNCTION_DDL,
    NOTE_TRIGGER_FUNCTION_DDL,
    NOTE_TRIGGER_DDL,
    TRIGGER_FUNCTION_DDL,
    TRIGGER_DDL,
)
FOLD_INDEX_DDL: tuple[str, ...] = (
    f"CREATE INDEX {{concurrently}} IF NOT EXISTS {FOLD_FTS_INDEX} "
    "ON candidates USING GIN (keyword_fold_fts)",
    f"CREATE INDEX {{concurrently}} IF NOT EXISTS {NOTE_FOLD_FTS_INDEX} "
    "ON notes USING GIN (content_fold_fts)",
)


def fold_index_ddl(*, concurrently: bool) -> list[str]:
    word = "CONCURRENTLY" if concurrently else ""
    return [stmt.format(concurrently=word) for stmt in FOLD_INDEX_DDL]


def schema_ddl() -> list[str]:
    """Pełny, idempotentny DDL korpusu dla siatki w ``entrypoint.sh``."""
    return [
        *COLUMN_DDL,
        *FOLD_COLUMN_DDL,
        JSON_TEXT_FUNCTION_DDL,
        *FOLD_FUNCTION_DDLS,
    ]


def schema_index_ddl() -> list[str]:
    return [*index_ddl(concurrently=True), *fold_index_ddl(concurrently=True)]


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


# Korpus złożony: paczki po kluczu ``id > :after`` (bez ponownego skanu NULL-i
# od początku tabeli przy każdej paczce). ``SET keyword_doc = NULL`` odpala
# trigger, który liczy wszystkie trzy kolumny.
FOLD_BACKFILL_BATCH_SQL = (
    "UPDATE candidates SET keyword_doc = NULL WHERE id IN ("
    " SELECT id FROM candidates WHERE keyword_fold_fts IS NULL AND id > :after"
    " ORDER BY id LIMIT :limit"
    ") RETURNING id, keyword_fold_fts IS NOT NULL"
)
FOLD_PENDING_EXISTS_SQL = (
    "SELECT EXISTS (SELECT 1 FROM candidates WHERE keyword_fold_fts IS NULL)"
)

# Notatki: jedna aktualizacja uzupełnia indeks i rozpakowuje treść zapisaną
# przez import jako JSON. Dla pozostałych notatek ``note_unwrap_json`` zwraca
# treść bez zmian (``SET content = content`` — odpala trigger). ``updated_at``
# zostaje nietknięte: od niego zależy odcisk nocnej analizy notatek przez AI
# (zmiana = ponowna płatna analiza wszystkich). Notatka w kształcie
# ``{"content":"…"}`` jest zawsze nieedytowana — edycja w interfejsie zapisuje
# ją już rozpakowaną (``unwrapNoteContent`` w formularzu).
NOTES_BACKFILL_BATCH_SQL = (
    f"UPDATE notes SET content = {NOTE_UNWRAP_FUNCTION}(content) WHERE id IN ("
    " SELECT id FROM notes WHERE content_fold_fts IS NULL AND id > :after"
    " ORDER BY id LIMIT :limit"
    ") RETURNING id, content_fold_fts IS NOT NULL"
)
NOTES_PENDING_EXISTS_SQL = (
    "SELECT EXISTS (SELECT 1 FROM notes WHERE content_fold_fts IS NULL)"
)
NOTES_WRAPPED_COUNT_SQL = (
    "SELECT count(*) FROM notes WHERE content LIKE '{\"content\":%' "
    f"AND {NOTE_UNWRAP_FUNCTION}(content) IS DISTINCT FROM content"
)
NOTES_UNWRAP_RECEIPT_KEY = "0385_traffit_note_content_unwrap"


# ── Gotowość (czy wszystkie wiersze mają korpus) ─────────────────────────────

_ready = False
_fold_ready = False
_notes_ready = False


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


def fold_ready() -> bool:
    """Każdy kandydat ma ``keyword_fold_fts`` (stan procesu, jak ``ready()``)."""
    return _fold_ready


def mark_fold_ready(value: bool = True) -> None:
    global _fold_ready
    _fold_ready = value


def notes_ready() -> bool:
    """Każda notatka ma ``content_fold_fts``."""
    return _notes_ready


def mark_notes_ready(value: bool = True) -> None:
    global _notes_ready
    _notes_ready = value


def folded_search_enabled() -> bool:
    """Nowa ścieżka słów kluczowych: przełącznik ON i korpus złożony gotowy.

    ContextVar ``force_folded_search`` wygrywa — skrypt porównujący i testy
    liczą tę samą prośbę starą i nową ścieżką w jednym procesie.
    """
    forced = _FORCE_FOLDED.get()
    if forced is not None:
        return forced
    from app.core.config import settings  # noqa: PLC0415

    return bool(getattr(settings, "KEYWORD_SEARCH_FOLDED_FTS", False)) and _fold_ready


def notes_folded_search_enabled() -> bool:
    forced = _FORCE_FOLDED.get()
    if forced is not None:
        return forced
    return folded_search_enabled() and _notes_ready


_FORCE_FOLDED: ContextVar[Optional[bool]] = ContextVar(
    "keyword_force_folded_search", default=None
)


@contextmanager
def force_folded_search(value: bool) -> Iterator[None]:
    token = _FORCE_FOLDED.set(value)
    try:
        yield
    finally:
        _FORCE_FOLDED.reset(token)


# ── Lustro w Pythonie: składanie tekstu (wycinki pod wynikiem) ──────────────

_FOLD_MAP = str.maketrans(FOLD_SRC + "/\\", FOLD_DST + "  ")


def fold_text(value: str) -> str:
    """Polskie znaki → ASCII, małe litery, ukośnik → spacja.

    Lustro pierwszego kroku ``candidate_keyword_fold`` BEZ słów specjalnych —
    zachowuje długość tekstu (poza rzadkimi znakami, których ``lower`` zmienia
    długość), więc pozycje trafienia w tekście złożonym wskazują to samo
    miejsce w oryginale. Wołający sprawdza długość, zanim użyje pozycji.
    """
    return value.translate(_FOLD_MAP).lower()


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
