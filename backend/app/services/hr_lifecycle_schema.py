"""„Ludzie w NEXUSIE” — Wejście i odejście: SQL migracji ``0457_hr_lifecycle`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0457_hr_lifecycle.py`` i ``entrypoint.sh``
(przez ``app/services/hr_schema_bundle.py``). Zakres: szablony i sprawy cyklu życia, zadania, przekazania pracy.

Kontrakt modułu (czyta go agregator i test łańcucha):

* ``TABLE_DDL`` — ``CREATE TABLE IF NOT EXISTS`` nowych tabel (VARCHAR + CHECK,
  bez nowych typów enum),
* ``COLUMN_DDL`` — ``ALTER TABLE … ADD COLUMN IF NOT EXISTS`` w istniejących tabelach,
* ``INDEX_DDL`` — ``CREATE [UNIQUE] INDEX IF NOT EXISTS``,
* ``CONSTRAINT_DDL`` — ograniczenia dokładane do ISTNIEJĄCYCH tabel (idempotentne bloki ``DO``),
* ``DATA_DDL`` — zasiewy i znaczniki jednorazowe (idempotentne),
* ``TABLES`` — nowe tabele w kolejności tworzenia (downgrade kasuje odwrotnie),
* ``DOWNGRADE_DDL`` — sprzątanie kolumn/ograniczeń w istniejących tabelach.

Każda instrukcja musi być idempotentna: entrypoint wykonuje je przy każdym starcie.

Tabele:

* ``lifecycle_templates`` / ``lifecycle_template_items`` — listy zadań wejścia
  i odejścia (Kadry), z terminem liczonym w DNIACH ROBOCZYCH od startu albo
  od ostatniego dnia pracy,
* ``lifecycle_cases`` — sprawa wejścia albo odejścia osoby. Odejście niesie
  ostatni dzień pracy i ``deactivate_on`` (dzień po nim, kalendarz firmy),
  przekazanie pracy wykonuje się o 18:00 ostatniego dnia, konto wyłącza się
  w ``deactivate_on``. Powód odejścia to słownik bez danych o zdrowiu,
* ``lifecycle_tasks`` — zadania sprawy (z szablonu albo ręczne),
* ``work_handovers`` — przekazanie pracy odchodzącej osoby per rodzaj pracy
  (przejmujący, liczba pozycji, wynik w liczbach).
"""

from __future__ import annotations

CASE_KINDS: tuple[str, ...] = ("onboarding", "offboarding")
CASE_STATUSES: tuple[str, ...] = ("draft", "active", "done", "cancelled")
#: Sprawy „żywe” — jedna na osobę i rodzaj.
LIVE_CASE_STATUSES: tuple[str, ...] = ("draft", "active")
TASK_CATEGORIES: tuple[str, ...] = (
    "accounts",
    "equipment",
    "documents",
    "training",
    "meeting",
    "other",
)
#: Kto wykonuje: przełożony, Kadry, recepcja (uprawnienie „Sprzęt”),
#: sama osoba, IT (admini NEXUSA).
ASSIGNEE_KINDS: tuple[str, ...] = (
    "manager",
    "people_admin",
    "reception",
    "person",
    "it",
)
TASK_STATUSES: tuple[str, ...] = ("open", "done", "skipped")
EXIT_INITIATORS: tuple[str, ...] = ("employee", "company", "mutual")
#: Powód odejścia — słownik bez kategorii zdrowotnych (dane o zdrowiu nie
#: należą do sprawy odejścia; Compass trzymał tu wolny tekst).
EXIT_REASONS: tuple[str, ...] = (
    "new_opportunity",
    "compensation",
    "role_fit",
    "management",
    "work_life_balance",
    "career_growth",
    "relocation",
    "contract_end",
    "other",
)
#: Rodzaje pracy, które przechodzą na przejmującego (pozostałe rodzaje
#: z podsumowania „co osoba ma w NEXUSIE” idą z rekrutacjami albo są
#: informacją — ``app/services/hr/handover.py``).
TRANSFER_KINDS: tuple[str, ...] = (
    "recruitments",
    "delivery_lead_jobs",
    "dl_clients",
    "my_people",
)
HANDOVER_STATUSES: tuple[str, ...] = ("planned", "done", "failed")
ACCOUNT_CLOSE_RESULTS: tuple[str, ...] = (
    "deactivated",
    "already_inactive",
    "skipped_admin",
)

#: Najdalsze przesunięcie terminu zadania (dni robocze) w obie strony.
MAX_OFFSET_BEFORE = 60
MAX_OFFSET_AFTER = 120


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_TEMPLATE_KIND = f"kind IN ({quoted(CASE_KINDS)})"
CK_TEMPLATE_EMPLOYMENT_TYPE = (
    "employment_type IS NULL OR employment_type IN ('uop', 'b2b', 'zlecenie')"
)
CK_ITEM_CATEGORY = f"category IN ({quoted(TASK_CATEGORIES)})"
CK_ITEM_ASSIGNEE = f"assignee_kind IN ({quoted(ASSIGNEE_KINDS)})"
CK_ITEM_OFFSET = f"due_offset_days BETWEEN -{MAX_OFFSET_BEFORE} AND {MAX_OFFSET_AFTER}"
CK_CASE_KIND = f"kind IN ({quoted(CASE_KINDS)})"
CK_CASE_STATUS = f"status IN ({quoted(CASE_STATUSES)})"
#: Wejście ma datę startu, odejście — ostatni dzień pracy.
CK_CASE_DATES = (
    "(kind = 'onboarding' AND start_date IS NOT NULL) "
    "OR (kind = 'offboarding' AND last_working_day IS NOT NULL)"
)
#: Konto wyłącza się najwcześniej dzień po ostatnim dniu pracy.
CK_CASE_DEACTIVATE_ON = "deactivate_on IS NULL OR (kind = 'offboarding' AND deactivate_on > last_working_day)"
#: Bez konta tylko szkic wejścia z adresem nowej osoby.
CK_CASE_PERSON = (
    "user_id IS NOT NULL OR (kind = 'onboarding' AND status IN ('draft', 'cancelled') "
    "AND pending_email IS NOT NULL)"
)
CK_CASE_EXIT_INITIATOR = (
    f"exit_initiator IS NULL OR exit_initiator IN ({quoted(EXIT_INITIATORS)})"
)
CK_CASE_EXIT_REASON = f"exit_reason IS NULL OR exit_reason IN ({quoted(EXIT_REASONS)})"
CK_CASE_EXIT_ONLY_OFFBOARDING = (
    "kind = 'offboarding' OR (exit_initiator IS NULL AND exit_reason IS NULL "
    "AND exit_note IS NULL)"
)
CK_CASE_ACCOUNT_RESULT = (
    "account_close_result IS NULL OR account_close_result IN "
    f"({quoted(ACCOUNT_CLOSE_RESULTS)})"
)
CK_TASK_CATEGORY = CK_ITEM_CATEGORY
CK_TASK_ASSIGNEE = CK_ITEM_ASSIGNEE
CK_TASK_STATUS = f"status IN ({quoted(TASK_STATUSES)})"
#: Odhaczone zadanie wie, kiedy je zamknięto; otwarte nie ma tej daty.
CK_TASK_DONE_AT = "(status = 'open') = (done_at IS NULL)"
CK_HANDOVER_KIND = f"work_kind IN ({quoted(TRANSFER_KINDS)})"
CK_HANDOVER_STATUS = f"status IN ({quoted(HANDOVER_STATUSES)})"
CK_HANDOVER_COUNT = "item_count >= 0"
CK_HANDOVER_EXECUTED = "(status = 'done') = (executed_at IS NOT NULL)"

#: Jedna żywa sprawa na osobę i rodzaj (szkic albo w toku).
LIVE_CASE_WHERE = f"status IN ({quoted(LIVE_CASE_STATUSES)})"
#: Jeden szkic wejścia na adres nowej osoby (konto jeszcze nie istnieje);
#: adres zapisuje się małymi literami (``normalize_email``).
PENDING_EMAIL_WHERE = "user_id IS NULL AND status = 'draft'"
OPEN_TASK_WHERE = "status = 'open'"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS lifecycle_templates (
    id SERIAL PRIMARY KEY,
    kind VARCHAR(16) NOT NULL,
    name VARCHAR(160) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    employment_type VARCHAR(16) NULL,
    department VARCHAR(200) NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_lifecycle_templates_kind CHECK ({CK_TEMPLATE_KIND}),
    CONSTRAINT ck_lifecycle_templates_employment_type
        CHECK ({CK_TEMPLATE_EMPLOYMENT_TYPE})
)""",
    f"""CREATE TABLE IF NOT EXISTS lifecycle_template_items (
    id SERIAL PRIMARY KEY,
    template_id INTEGER NOT NULL REFERENCES lifecycle_templates(id) ON DELETE CASCADE,
    position SMALLINT NOT NULL DEFAULT 0,
    title VARCHAR(200) NOT NULL,
    category VARCHAR(16) NOT NULL DEFAULT 'other',
    assignee_kind VARCHAR(16) NOT NULL DEFAULT 'people_admin',
    due_offset_days SMALLINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_lifecycle_template_items_category CHECK ({CK_ITEM_CATEGORY}),
    CONSTRAINT ck_lifecycle_template_items_assignee CHECK ({CK_ITEM_ASSIGNEE}),
    CONSTRAINT ck_lifecycle_template_items_offset CHECK ({CK_ITEM_OFFSET})
)""",
    f"""CREATE TABLE IF NOT EXISTS lifecycle_cases (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE RESTRICT,
    pending_email VARCHAR(255) NULL,
    pending_name VARCHAR(255) NULL,
    kind VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'draft',
    template_id INTEGER NULL REFERENCES lifecycle_templates(id) ON DELETE SET NULL,
    start_date DATE NULL,
    last_working_day DATE NULL,
    deactivate_on DATE NULL,
    owner_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    manager_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    profile_values JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    exit_initiator VARCHAR(16) NULL,
    exit_reason VARCHAR(32) NULL,
    exit_note VARCHAR(500) NULL,
    started_at TIMESTAMPTZ NULL,
    handover_executed_at TIMESTAMPTZ NULL,
    account_closed_at TIMESTAMPTZ NULL,
    account_close_result VARCHAR(24) NULL,
    completed_at TIMESTAMPTZ NULL,
    cancelled_at TIMESTAMPTZ NULL,
    cancelled_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    source_key VARCHAR(120) NULL,
    compass_id UUID NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_lifecycle_cases_source_key UNIQUE (source_key),
    CONSTRAINT uq_lifecycle_cases_compass_id UNIQUE (compass_id),
    CONSTRAINT ck_lifecycle_cases_kind CHECK ({CK_CASE_KIND}),
    CONSTRAINT ck_lifecycle_cases_status CHECK ({CK_CASE_STATUS}),
    CONSTRAINT ck_lifecycle_cases_dates CHECK ({CK_CASE_DATES}),
    CONSTRAINT ck_lifecycle_cases_deactivate_on CHECK ({CK_CASE_DEACTIVATE_ON}),
    CONSTRAINT ck_lifecycle_cases_person CHECK ({CK_CASE_PERSON}),
    CONSTRAINT ck_lifecycle_cases_exit_initiator CHECK ({CK_CASE_EXIT_INITIATOR}),
    CONSTRAINT ck_lifecycle_cases_exit_reason CHECK ({CK_CASE_EXIT_REASON}),
    CONSTRAINT ck_lifecycle_cases_exit_only_offboarding
        CHECK ({CK_CASE_EXIT_ONLY_OFFBOARDING}),
    CONSTRAINT ck_lifecycle_cases_account_result CHECK ({CK_CASE_ACCOUNT_RESULT})
)""",
    f"""CREATE TABLE IF NOT EXISTS lifecycle_tasks (
    id SERIAL PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES lifecycle_cases(id) ON DELETE CASCADE,
    template_item_id INTEGER NULL
        REFERENCES lifecycle_template_items(id) ON DELETE SET NULL,
    position SMALLINT NOT NULL DEFAULT 0,
    title VARCHAR(200) NOT NULL,
    category VARCHAR(16) NOT NULL DEFAULT 'other',
    assignee_kind VARCHAR(16) NOT NULL,
    assignee_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    due_date DATE NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'open',
    done_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    done_at TIMESTAMPTZ NULL,
    note VARCHAR(500) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_lifecycle_tasks_category CHECK ({CK_TASK_CATEGORY}),
    CONSTRAINT ck_lifecycle_tasks_assignee CHECK ({CK_TASK_ASSIGNEE}),
    CONSTRAINT ck_lifecycle_tasks_status CHECK ({CK_TASK_STATUS}),
    CONSTRAINT ck_lifecycle_tasks_done_at CHECK ({CK_TASK_DONE_AT})
)""",
    f"""CREATE TABLE IF NOT EXISTS work_handovers (
    id SERIAL PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES lifecycle_cases(id) ON DELETE CASCADE,
    work_kind VARCHAR(32) NOT NULL,
    receiver_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    item_count INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'planned',
    executed_at TIMESTAMPTZ NULL,
    result JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    error VARCHAR(200) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_work_handovers_case_kind UNIQUE (case_id, work_kind),
    CONSTRAINT ck_work_handovers_kind CHECK ({CK_HANDOVER_KIND}),
    CONSTRAINT ck_work_handovers_status CHECK ({CK_HANDOVER_STATUS}),
    CONSTRAINT ck_work_handovers_count CHECK ({CK_HANDOVER_COUNT}),
    CONSTRAINT ck_work_handovers_executed CHECK ({CK_HANDOVER_EXECUTED})
)""",
)
COLUMN_DDL: tuple[str, ...] = ()
INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_lifecycle_template_items_template "
    "ON lifecycle_template_items (template_id, position)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_lifecycle_cases_live "
    f"ON lifecycle_cases (user_id, kind) WHERE {LIVE_CASE_WHERE}",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_lifecycle_cases_pending_email "
    f"ON lifecycle_cases (pending_email) WHERE {PENDING_EMAIL_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_lifecycle_cases_status_deactivate "
    "ON lifecycle_cases (status, deactivate_on)",
    "CREATE INDEX IF NOT EXISTS ix_lifecycle_cases_user ON lifecycle_cases (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_lifecycle_tasks_case "
    "ON lifecycle_tasks (case_id, position)",
    "CREATE INDEX IF NOT EXISTS ix_lifecycle_tasks_assignee_open "
    f"ON lifecycle_tasks (assignee_user_id, due_date) WHERE {OPEN_TASK_WHERE}",
)
CONSTRAINT_DDL: tuple[str, ...] = ()

#: Szablony startowe (tytuł, kategoria, kto wykonuje, przesunięcie w dniach
#: roboczych). Kadry zmieniają je w Ustawieniach → Kadry; szablonów się nie
#: kasuje (wyłącza), więc zasiew nie wraca po restarcie.
DEFAULT_TEMPLATES: dict[str, tuple[str, tuple[tuple[str, str, str, int], ...]]] = {
    "onboarding": (
        "Wejście — standard",
        (
            ("Konto Microsoft 365", "accounts", "it", -2),
            ("Konto i rola w NEXUSIE", "accounts", "it", -2),
            ("Wydanie zestawu biurowego", "equipment", "reception", -2),
            ("Protokół wydania sprzętu do podpisu", "equipment", "reception", 0),
            ("Dokumenty kadrowe", "documents", "people_admin", 0),
            ("Rozmowa w pierwszym dniu", "meeting", "manager", 0),
            ("Rozmowa po pierwszym tygodniu", "meeting", "manager", 5),
            ("Rozmowa po pierwszym miesiącu", "meeting", "manager", 21),
        ),
    ),
    "offboarding": (
        "Odejście — standard",
        (
            ("Rozmowa wyjściowa", "meeting", "manager", -2),
            ("Ostatni timesheet", "documents", "person", 0),
            ("Rozliczenie urlopu", "documents", "people_admin", 0),
            ("Zwrot sprzętu z ewidencji", "equipment", "reception", 0),
            ("Dezaktywacja karty dostępu w budynku", "equipment", "reception", 0),
            ("Wyłączenie skrzynki i licencji Microsoft 365", "accounts", "it", 1),
        ),
    ),
}


def _sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _seed_statement(kind: str) -> str:
    name, items = DEFAULT_TEMPLATES[kind]
    values = ", ".join(
        f"({position}, {_sql_text(title)}, '{category}', '{assignee}', {offset})"
        for position, (title, category, assignee, offset) in enumerate(items)
    )
    return (
        "WITH seeded AS ("
        f" INSERT INTO lifecycle_templates (kind, name) SELECT '{kind}', {_sql_text(name)}"
        " WHERE NOT EXISTS (SELECT 1 FROM lifecycle_templates"
        f" WHERE kind = '{kind}') RETURNING id)"
        " INSERT INTO lifecycle_template_items"
        " (template_id, position, title, category, assignee_kind, due_offset_days)"
        " SELECT seeded.id, v.position, v.title, v.category, v.assignee_kind, v.offset_days"
        f" FROM seeded, (VALUES {values})"
        " AS v(position, title, category, assignee_kind, offset_days)"
    )


DATA_DDL: tuple[str, ...] = tuple(_seed_statement(kind) for kind in CASE_KINDS)
TABLES: tuple[str, ...] = (
    "lifecycle_templates",
    "lifecycle_template_items",
    "lifecycle_cases",
    "lifecycle_tasks",
    "work_handovers",
)
DOWNGRADE_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
