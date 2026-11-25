"""Układ CV: klasyczny Word albo „Nowe CV” w PDF (migracja 0753, 22.11.2026).

Jedno źródło SQL dla migracji i `entrypoint.sh` (alembic na produkcji bywa
osierocony, entrypoint jest wtedy wdrożeniem):

- `candidate_stage_cvs.cv_layout` — układ tego CV, jedno ustawienie widoczne
  w generatorze, karcie „CV do klienta” i edytorze; `page1_extras` — dodatki
  strony 1 nowego CV, których nie ma w HTML-u edytora (np. wybrane zdanie
  „najmocniejszy wynik”),
- `cv_document_versions.cv_layout` / `page1_extras` — zamrożone przy
  zatwierdzeniu (NULL w starych wierszach = klasyczny),
- `cv_generated_documents.cv_layout` — układ wybrany przy „Generuj”; trafia do
  CV etapu, gdy wynik generacji staje się szkicem,
- `client_cv_rules.cv_layout` — domyślny układ klienta (NULL = klasyczny).

Migracja 0776 (25.11.2026): `client_cv_rules.cv_file_format` — w jakim pliku
klient chce CV (`docx` | `pdf` | `both`; NULL = bez wymagań, plik idzie za
układem: klasyczne → Word, Nowe CV → PDF). Osobna krotka, bo 0753 wykonuje
`ALL_DDL` — dopisanie tam zmieniłoby starą migrację.
"""

LAYOUTS = ("classic", "new")

ADDED_COLUMNS = (
    ("candidate_stage_cvs", "cv_layout", "VARCHAR(16) NOT NULL DEFAULT 'classic'"),
    ("candidate_stage_cvs", "page1_extras", "JSONB NULL"),
    ("cv_document_versions", "cv_layout", "VARCHAR(16) NULL"),
    ("cv_document_versions", "page1_extras", "JSONB NULL"),
    ("cv_generated_documents", "cv_layout", "VARCHAR(16) NULL"),
    ("client_cv_rules", "cv_layout", "VARCHAR(16) NULL"),
)

ALL_DDL = tuple(
    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}"
    for table, column, ddl in ADDED_COLUMNS
)

FILE_FORMATS = ("docx", "pdf", "both")

FILE_FORMAT_COLUMNS = (("client_cv_rules", "cv_file_format", "VARCHAR(8) NULL"),)

FILE_FORMAT_DDL = tuple(
    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}"
    for table, column, ddl in FILE_FORMAT_COLUMNS
)
