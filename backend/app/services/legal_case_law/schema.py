"""Orzecznictwo dla asystenta prawnego (część C, 25.11.2026): SQL migracji
``0787_legal_case_law`` i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0787_legal_case_law.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``).

Tabela ``legal_cases`` — orzeczenie pobrane ze źródła z API (dziś SAOS):
sygnatura, sąd, data, rodzaj, adres, teza, tekst, skrót treści i kiedy
pobrano. Orzeczenia nie podlegają prawu autorskiemu (art. 4 pkt 2 pr. aut.),
więc tekst może trafić do modelu. ``search_tsv`` to tekst złożony bez polskich
znaków (``help_search.fold``) — wyszukiwanie po słowach bez rozszerzeń
Postgresa; wektory leżą w Qdrancie (``nexus_legal_cases``, id punktu = id
wiersza, bez tekstu w payloadzie).
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted

#: ``saos`` ma API; ``cbosa`` i ``eureka`` to dziś sam link (reguła
#: ``docs/claude/asystent-prawny/orzecznictwo-i-interpretacje.md``), wartości
#: są w CHECK-u, żeby pobranie z nich nie wymagało migracji.
SOURCES: tuple[str, ...] = ("saos", "cbosa", "eureka")
COURT_TYPES: tuple[str, ...] = (
    "supreme",
    "common",
    "administrative",
    "constitutional",
    "appeal_chamber",
    "tax_authority",
)
KINDS: tuple[str, ...] = (
    "judgment",
    "decision",
    "resolution",
    "order",
    "reasons",
    "interpretation",
)

SOURCE_ID_MAX = 64
SIGNATURE_MAX = 200
COURT_MAX = 200
URL_MAX = 1000
TOPIC_MAX = 32

CK_SOURCE = f"source IN ({quoted(SOURCES)})"
CK_COURT_TYPE = f"court_type IN ({quoted(COURT_TYPES)})"
CK_KIND = f"kind IN ({quoted(KINDS)})"
CK_TOPICS = "jsonb_typeof(topics) = 'array'"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS legal_cases (
    id SERIAL PRIMARY KEY,
    source VARCHAR(8) NOT NULL,
    source_id VARCHAR({SOURCE_ID_MAX}) NOT NULL,
    signature VARCHAR({SIGNATURE_MAX}) NOT NULL,
    court VARCHAR({COURT_MAX}) NOT NULL,
    court_type VARCHAR(16) NOT NULL,
    judgment_date DATE NULL,
    kind VARCHAR(16) NOT NULL,
    url VARCHAR({URL_MAX}) NOT NULL,
    summary TEXT NULL,
    text TEXT NOT NULL,
    content_sha256 VARCHAR(64) NOT NULL,
    topics JSONB NOT NULL DEFAULT '[]'::jsonb,
    search_tsv TSVECTOR NULL,
    embedded_sha256 VARCHAR(64) NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_legal_cases_source_id UNIQUE (source, source_id),
    CONSTRAINT ck_legal_cases_source CHECK ({CK_SOURCE}),
    CONSTRAINT ck_legal_cases_court_type CHECK ({CK_COURT_TYPE}),
    CONSTRAINT ck_legal_cases_kind CHECK ({CK_KIND}),
    CONSTRAINT ck_legal_cases_topics CHECK ({CK_TOPICS})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_legal_cases_court_date "
    "ON legal_cases (court_type, judgment_date)",
    "CREATE INDEX IF NOT EXISTS ix_legal_cases_search "
    "ON legal_cases USING GIN (search_tsv)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()

DATA_DDL: tuple[str, ...] = ()

#: Kolejność zakładania; ``downgrade`` kasuje odwrotnie.
TABLES: tuple[str, ...] = ("legal_cases",)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
