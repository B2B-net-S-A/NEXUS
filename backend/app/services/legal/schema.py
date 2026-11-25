"""Korpus prawa asystenta prawnego (część A planu, 25.11.2026): SQL migracji
``0784_legal_corpus`` i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0784_legal_corpus.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``).

Tabele:

* ``legal_acts`` — akt z rejestru ``services/legal/acts.py`` (klucz ``kc``,
  ``kp``, ``rodo`` …), źródło ``eli`` albo ``eurlex``, stan ostatniego
  sprawdzenia w API.
* ``legal_act_versions`` — tekst jednolity (ELI) albo wersja skonsolidowana
  (EUR-Lex) z datą obowiązywania od–do, adresem, skrótem treści i listą zmian
  wobec poprzedniej wersji. **Nowy wiersz z ``previous_version_id`` to
  zdarzenie „zmienił się tekst przepisu”** dla Przepisów (część H planu) —
  ``corpus.changes_since``.
* ``legal_provisions`` — jednostka redakcyjna (``art. 61 § 1``) z tekstem
  całego poddrzewa i kolejnością. ``search_vector`` liczy baza z tekstu bez
  polskich znaków (ranking po słowach bez Qdranta). Wektory leżą w Qdrancie
  ``nexus_legal_corpus`` z id punktu = id przepisu, bez tekstu w payloadzie.

Same dane publiczne (teksty aktów), bez danych firmy i osób.
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted
from app.services.legal.acts import SOURCE_ELI, SOURCE_EURLEX
from app.services.legal.parse import KINDS

SOURCES: tuple[str, ...] = (SOURCE_ELI, SOURCE_EURLEX)
#: ``pending`` = akt w rejestrze, jeszcze bez tekstu; ``ok`` = ostatnie
#: sprawdzenie się udało; ``failed`` = API nie odpowiedziało albo tekst się
#: nie dał podzielić (zostaje poprzednia wersja).
FETCH_STATUSES: tuple[str, ...] = ("pending", "ok", "failed")
FORMATS: tuple[str, ...] = ("html", "pdf", "xhtml")

ACT_KEY_MAX = 32
IDENT_MAX = 40
TITLE_MAX = 400
SHORT_NAME_MAX = 60
URL_MAX = 500
ERROR_MAX = 255
REF_MAX = 120
HEADING_MAX = 300

CK_ACT_SOURCE = f"source IN ({quoted(SOURCES)})"
CK_ACT_STATUS = f"fetch_status IN ({quoted(FETCH_STATUSES)})"
CK_VERSION_FORMAT = f"format IN ({quoted(FORMATS)})"
CK_VERSION_DATES = "valid_to IS NULL OR valid_to >= valid_from"
CK_VERSION_CHANGES = "jsonb_typeof(changes) = 'object'"
CK_PROVISION_KIND = f"kind IN ({quoted(KINDS)})"

#: Tekst bez polskich znaków (jak ranking po słowach umów ramowych). ``simple``
#: bez stemmera: zapytanie idzie przedrostkami słów (``wypow:*``).
SEARCH_VECTOR_EXPR = (
    "to_tsvector('simple', translate(lower(coalesce(ref, '') || ' ' || text), "
    "'ąćęłńóśźżĄĆĘŁŃÓŚŹŻ', 'acelnoszzacelnoszz'))"
)

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS legal_acts (
    id SERIAL PRIMARY KEY,
    key VARCHAR({ACT_KEY_MAX}) NOT NULL,
    source VARCHAR(8) NOT NULL,
    ident VARCHAR({IDENT_MAX}) NOT NULL,
    short_name VARCHAR({SHORT_NAME_MAX}) NOT NULL,
    title VARCHAR({TITLE_MAX}) NOT NULL,
    url VARCHAR({URL_MAX}) NULL,
    fetch_status VARCHAR(8) NOT NULL DEFAULT 'pending',
    fetch_error VARCHAR({ERROR_MAX}) NULL,
    checked_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_legal_acts_key UNIQUE (key),
    CONSTRAINT ck_legal_acts_source CHECK ({CK_ACT_SOURCE}),
    CONSTRAINT ck_legal_acts_fetch_status CHECK ({CK_ACT_STATUS})
)""",
    f"""CREATE TABLE IF NOT EXISTS legal_act_versions (
    id SERIAL PRIMARY KEY,
    act_id INTEGER NOT NULL REFERENCES legal_acts(id) ON DELETE CASCADE,
    version_ident VARCHAR({IDENT_MAX}) NOT NULL,
    valid_from DATE NOT NULL,
    valid_to DATE NULL,
    published_on DATE NULL,
    url VARCHAR({URL_MAX}) NOT NULL,
    format VARCHAR(8) NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    provisions_count INTEGER NOT NULL DEFAULT 0,
    previous_version_id INTEGER NULL REFERENCES legal_act_versions(id) ON DELETE SET NULL,
    changes JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    meta JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_legal_act_versions_act_ident UNIQUE (act_id, version_ident),
    CONSTRAINT ck_legal_act_versions_format CHECK ({CK_VERSION_FORMAT}),
    CONSTRAINT ck_legal_act_versions_dates CHECK ({CK_VERSION_DATES}),
    CONSTRAINT ck_legal_act_versions_changes CHECK ({CK_VERSION_CHANGES})
)""",
    f"""CREATE TABLE IF NOT EXISTS legal_provisions (
    id SERIAL PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES legal_act_versions(id) ON DELETE CASCADE,
    act_id INTEGER NOT NULL REFERENCES legal_acts(id) ON DELETE CASCADE,
    ref VARCHAR({REF_MAX}) NOT NULL,
    ref_key VARCHAR({REF_MAX}) NOT NULL,
    article VARCHAR(24) NOT NULL,
    kind VARCHAR(4) NOT NULL,
    depth SMALLINT NOT NULL DEFAULT 0,
    parent_key VARCHAR({REF_MAX}) NULL,
    position INTEGER NOT NULL,
    heading VARCHAR({HEADING_MAX}) NULL,
    text TEXT NOT NULL,
    repealed BOOLEAN NOT NULL DEFAULT FALSE,
    search_vector TSVECTOR GENERATED ALWAYS AS ({SEARCH_VECTOR_EXPR}) STORED,
    CONSTRAINT uq_legal_provisions_version_key UNIQUE (version_id, ref_key),
    CONSTRAINT ck_legal_provisions_kind CHECK ({CK_PROVISION_KIND})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_legal_act_versions_act_valid "
    "ON legal_act_versions (act_id, valid_from)",
    "CREATE INDEX IF NOT EXISTS ix_legal_act_versions_created "
    "ON legal_act_versions (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_legal_provisions_act_key "
    "ON legal_provisions (act_id, ref_key)",
    "CREATE INDEX IF NOT EXISTS ix_legal_provisions_version_position "
    "ON legal_provisions (version_id, position)",
    "CREATE INDEX IF NOT EXISTS ix_legal_provisions_search "
    "ON legal_provisions USING GIN (search_vector)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()

DATA_DDL: tuple[str, ...] = ()

#: Kolejność zakładania; ``downgrade`` kasuje odwrotnie.
TABLES: tuple[str, ...] = (
    "legal_acts",
    "legal_act_versions",
    "legal_provisions",
)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
