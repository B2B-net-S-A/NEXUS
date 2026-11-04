"""„Ludzie w NEXUSIE” — Wejście i odejście: SQL migracji ``0461_hr_lifecycle`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0461_hr_lifecycle.py`` i ``entrypoint.sh``
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

* ``lifecycle_templates`` / ``lifecycle_template_items`` — ścieżki wejścia
  i odejścia, z terminem liczonym w DNIACH ROBOCZYCH od startu albo od
  ostatniego dnia pracy. Od etapu 3 (17.10.2026) ścieżka ma odbiorców
  (``audience``: zespół wewnętrzny albo konsultant u klienta) i wersję
  (każdy zapis = wersja + 1), a pozycja opis, „wymagane”, „wymaga pliku”,
  warunki (forma współpracy, sprzęt od nas / od klienta, student) i stały
  klucz (``key``, np. ``welcome_mail``),
* ``lifecycle_cases`` — sprawa wejścia albo odejścia osoby. Odejście niesie
  ostatni dzień pracy i ``deactivate_on`` (dzień po nim, kalendarz firmy),
  przekazanie pracy wykonuje się o 18:00 ostatniego dnia, konto wyłącza się
  w ``deactivate_on``. Powód odejścia to słownik bez danych o zdrowiu.
  Wejście konsultanta (etap 3) nie ma konta osoby — wiąże się z kontraktem
  (``contract_id``, bez FK: kontrakt scala i kasuje swoje haki), pamięta
  wersję ścieżki, z której powstało,
* ``lifecycle_tasks`` — zadania sprawy (z ścieżki, z pakietu klienta, z formy
  współpracy albo ręczne — ``source``),
* ``work_handovers`` — przekazanie pracy odchodzącej osoby per rodzaj pracy
  (przejmujący, liczba pozycji, wynik w liczbach); od etapu 2 także podwładni
  przełożonego, który odchodzi (``reports``), od etapu 3 opieka nad
  konsultantami (``care``).
"""

from __future__ import annotations

import json
from typing import Any

CASE_KINDS: tuple[str, ...] = ("onboarding", "offboarding")
CASE_STATUSES: tuple[str, ...] = ("draft", "active", "done", "cancelled")
#: Sprawy „żywe” — jedna na osobę i rodzaj.
LIVE_CASE_STATUSES: tuple[str, ...] = ("draft", "active")
#: Dla kogo ścieżka: zespół wewnętrzny (osoba z kontem i kartoteką) albo
#: konsultant u klienta (bez konta, sprawa przy kontrakcie). O1, 17.10.2026.
AUDIENCES: tuple[str, ...] = ("team", "consultant")
TASK_CATEGORIES: tuple[str, ...] = (
    "accounts",
    "equipment",
    "documents",
    "training",
    "meeting",
    "other",
)
#: Kto wykonuje: przełożony, Kadry, recepcja (uprawnienie „Sprzęt”),
#: sama osoba, IT (admini NEXUSA), a od etapu 3 (17.10.2026) także opiekun
#: kontraktu (``care_owner``), Delivery Lead klienta (``delivery_lead``)
#: i administracja@ (``administration`` — uprawnienie „Sprawy”). Wykonawca to
#: rola, nie osoba; tę samą krotkę czyta pakiet klienta (``client_pack``).
TASK_ASSIGNEES: tuple[str, ...] = (
    "manager",
    "people_admin",
    "reception",
    "person",
    "it",
    "care_owner",
    "delivery_lead",
    "administration",
)
#: Stara nazwa (etap 1) — ta sama krotka.
ASSIGNEE_KINDS: tuple[str, ...] = TASK_ASSIGNEES
TASK_STATUSES: tuple[str, ...] = ("open", "done", "skipped")
#: Skąd zadanie: pozycja ścieżki, pakiet klienta, pozycja z warunkiem formy
#: współpracy, dopisane ręcznie w sprawie.
TASK_SOURCES: tuple[str, ...] = ("path", "client", "form", "manual")
#: Warunki pozycji ścieżki (``conditions``): forma współpracy, sprzęt
#: (od nas / od klienta — ``clients.equipment_provider``), student.
CONDITION_KEYS: tuple[str, ...] = ("employment_types", "equipment", "student")
EQUIPMENT_CONDITIONS: tuple[str, ...] = ("ours", "client")
#: Stałe klucze pozycji, które czytają inne moduły: mail powitalny (G2
#: odhacza go przy wysyłce), zestaw sprzętu (lustro zadania recepcji
#: ``contract:{id}:start``) i wydanie sprzętu z protokołem.
KEY_WELCOME_MAIL = "welcome_mail"
KEY_EQUIPMENT_KIT = "equipment_kit"
KEY_EQUIPMENT_ISSUE = "equipment_issue"
KEY_MAX = 40
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
#: informacją — ``app/services/hr/handover.py``). ``reports`` (etap 2, D5,
#: 17.10.2026) — podwładni z kartoteki: przejmujący zostaje ich przełożonym.
#: ``care`` (etap 3, O11, 17.10.2026) — opieka nad konsultantami: kontrakty
#: i domyślne opieki klientów odchodzącego opiekuna.
TRANSFER_KINDS: tuple[str, ...] = (
    "recruitments",
    "delivery_lead_jobs",
    "dl_clients",
    "my_people",
    "reports",
    "care",
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
DESCRIPTION_MAX = 500


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_TEMPLATE_KIND = f"kind IN ({quoted(CASE_KINDS)})"
CK_TEMPLATE_EMPLOYMENT_TYPE = (
    "employment_type IS NULL OR employment_type IN ('uop', 'b2b', 'zlecenie')"
)
CK_TEMPLATE_AUDIENCE = f"audience IN ({quoted(AUDIENCES)})"
CK_TEMPLATE_VERSION = "version >= 1"
CK_ITEM_CATEGORY = f"category IN ({quoted(TASK_CATEGORIES)})"
CK_ITEM_ASSIGNEE = f"assignee_kind IN ({quoted(TASK_ASSIGNEES)})"
CK_ITEM_OFFSET = f"due_offset_days BETWEEN -{MAX_OFFSET_BEFORE} AND {MAX_OFFSET_AFTER}"
CK_ITEM_CONDITIONS = "jsonb_typeof(conditions) = 'object'"
CK_ITEM_ADDED_IN_VERSION = "added_in_version >= 1"
CK_CASE_KIND = f"kind IN ({quoted(CASE_KINDS)})"
CK_CASE_STATUS = f"status IN ({quoted(CASE_STATUSES)})"
CK_CASE_AUDIENCE = f"audience IN ({quoted(AUDIENCES)})"
#: Wejście konsultanta zawsze wisi na kontrakcie (konsultant nie ma konta).
CK_CASE_CONSULTANT_CONTRACT = "audience = 'team' OR contract_id IS NOT NULL"
CK_CASE_TEMPLATE_VERSION = "template_version IS NULL OR template_version >= 1"
#: Wejście ma datę startu, odejście — ostatni dzień pracy.
CK_CASE_DATES = (
    "(kind = 'onboarding' AND start_date IS NOT NULL) "
    "OR (kind = 'offboarding' AND last_working_day IS NOT NULL)"
)
#: Konto wyłącza się najwcześniej dzień po ostatnim dniu pracy.
CK_CASE_DEACTIVATE_ON = "deactivate_on IS NULL OR (kind = 'offboarding' AND deactivate_on > last_working_day)"
#: Bez konta: wejście konsultanta przy kontrakcie albo szkic wejścia z adresem
#: nowej osoby.
CK_CASE_PERSON = (
    "user_id IS NOT NULL OR (audience = 'consultant' AND contract_id IS NOT NULL) "
    "OR (kind = 'onboarding' AND status IN ('draft', 'cancelled') "
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
CK_TASK_SOURCE = f"source IN ({quoted(TASK_SOURCES)})"
#: Odhaczone zadanie wie, kiedy je zamknięto; otwarte nie ma tej daty.
CK_TASK_DONE_AT = "(status = 'open') = (done_at IS NULL)"
CK_HANDOVER_KIND = f"work_kind IN ({quoted(TRANSFER_KINDS)})"
CK_HANDOVER_STATUS = f"status IN ({quoted(HANDOVER_STATUSES)})"
CK_HANDOVER_COUNT = "item_count >= 0"
CK_HANDOVER_EXECUTED = "(status = 'done') = (executed_at IS NOT NULL)"

#: Jedna żywa sprawa na osobę i rodzaj (szkic albo w toku).
LIVE_CASE_WHERE = f"status IN ({quoted(LIVE_CASE_STATUSES)})"
#: Jedno żywe wejście (i jeden koniec projektu) na kontrakt.
LIVE_CONTRACT_CASE_WHERE = (
    f"contract_id IS NOT NULL AND status IN ({quoted(LIVE_CASE_STATUSES)})"
)
CONTRACT_CASE_WHERE = "contract_id IS NOT NULL"
#: Jeden szkic wejścia na adres nowej osoby (konto jeszcze nie istnieje);
#: adres zapisuje się małymi literami (``normalize_email``).
PENDING_EMAIL_WHERE = "user_id IS NULL AND status = 'draft'"
OPEN_TASK_WHERE = "status = 'open'"
#: Klucz pozycji jest jednoznaczny w obrębie ścieżki.
ITEM_KEY_WHERE = "key IS NOT NULL"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS lifecycle_templates (
    id SERIAL PRIMARY KEY,
    kind VARCHAR(16) NOT NULL,
    name VARCHAR(160) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    employment_type VARCHAR(16) NULL,
    department VARCHAR(200) NULL,
    audience VARCHAR(16) NOT NULL DEFAULT 'team',
    version INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_lifecycle_templates_kind CHECK ({CK_TEMPLATE_KIND}),
    CONSTRAINT ck_lifecycle_templates_employment_type
        CHECK ({CK_TEMPLATE_EMPLOYMENT_TYPE}),
    CONSTRAINT ck_lifecycle_templates_audience CHECK ({CK_TEMPLATE_AUDIENCE}),
    CONSTRAINT ck_lifecycle_templates_version CHECK ({CK_TEMPLATE_VERSION})
)""",
    f"""CREATE TABLE IF NOT EXISTS lifecycle_template_items (
    id SERIAL PRIMARY KEY,
    template_id INTEGER NOT NULL REFERENCES lifecycle_templates(id) ON DELETE CASCADE,
    position SMALLINT NOT NULL DEFAULT 0,
    title VARCHAR(200) NOT NULL,
    category VARCHAR(16) NOT NULL DEFAULT 'other',
    assignee_kind VARCHAR(16) NOT NULL DEFAULT 'people_admin',
    due_offset_days SMALLINT NOT NULL DEFAULT 0,
    description VARCHAR({DESCRIPTION_MAX}) NULL,
    required BOOLEAN NOT NULL DEFAULT TRUE,
    requires_file BOOLEAN NOT NULL DEFAULT FALSE,
    conditions JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    key VARCHAR({KEY_MAX}) NULL,
    added_in_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_lifecycle_template_items_category CHECK ({CK_ITEM_CATEGORY}),
    CONSTRAINT ck_lifecycle_template_items_assignee CHECK ({CK_ITEM_ASSIGNEE}),
    CONSTRAINT ck_lifecycle_template_items_offset CHECK ({CK_ITEM_OFFSET}),
    CONSTRAINT ck_lifecycle_template_items_conditions CHECK ({CK_ITEM_CONDITIONS}),
    CONSTRAINT ck_lifecycle_template_items_added_in
        CHECK ({CK_ITEM_ADDED_IN_VERSION})
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
    audience VARCHAR(16) NOT NULL DEFAULT 'team',
    contract_id INTEGER NULL,
    template_version INTEGER NULL,
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
    CONSTRAINT ck_lifecycle_cases_account_result CHECK ({CK_CASE_ACCOUNT_RESULT}),
    CONSTRAINT ck_lifecycle_cases_audience CHECK ({CK_CASE_AUDIENCE}),
    CONSTRAINT ck_lifecycle_cases_consultant_contract
        CHECK ({CK_CASE_CONSULTANT_CONTRACT}),
    CONSTRAINT ck_lifecycle_cases_template_version
        CHECK ({CK_CASE_TEMPLATE_VERSION})
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
    description VARCHAR({DESCRIPTION_MAX}) NULL,
    required BOOLEAN NOT NULL DEFAULT TRUE,
    requires_file BOOLEAN NOT NULL DEFAULT FALSE,
    key VARCHAR({KEY_MAX}) NULL,
    source VARCHAR(16) NOT NULL DEFAULT 'manual',
    source_label VARCHAR(160) NULL,
    due_offset_days SMALLINT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_lifecycle_tasks_category CHECK ({CK_TASK_CATEGORY}),
    CONSTRAINT ck_lifecycle_tasks_assignee CHECK ({CK_TASK_ASSIGNEE}),
    CONSTRAINT ck_lifecycle_tasks_status CHECK ({CK_TASK_STATUS}),
    CONSTRAINT ck_lifecycle_tasks_done_at CHECK ({CK_TASK_DONE_AT}),
    CONSTRAINT ck_lifecycle_tasks_source CHECK ({CK_TASK_SOURCE})
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
#: Kolumny etapu 3 w tabelach założonych wcześniejszą wersją 0461 (świeża
#: baza dostaje je w ``TABLE_DDL``).
COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE lifecycle_templates ADD COLUMN IF NOT EXISTS audience "
    "VARCHAR(16) NOT NULL DEFAULT 'team'",
    "ALTER TABLE lifecycle_templates ADD COLUMN IF NOT EXISTS version "
    "INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE lifecycle_template_items ADD COLUMN IF NOT EXISTS description "
    f"VARCHAR({DESCRIPTION_MAX}) NULL",
    "ALTER TABLE lifecycle_template_items ADD COLUMN IF NOT EXISTS required "
    "BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE lifecycle_template_items ADD COLUMN IF NOT EXISTS requires_file "
    "BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE lifecycle_template_items ADD COLUMN IF NOT EXISTS conditions "
    "JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE lifecycle_template_items ADD COLUMN IF NOT EXISTS key "
    f"VARCHAR({KEY_MAX}) NULL",
    "ALTER TABLE lifecycle_template_items ADD COLUMN IF NOT EXISTS added_in_version "
    "INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE lifecycle_cases ADD COLUMN IF NOT EXISTS audience "
    "VARCHAR(16) NOT NULL DEFAULT 'team'",
    "ALTER TABLE lifecycle_cases ADD COLUMN IF NOT EXISTS contract_id INTEGER NULL",
    "ALTER TABLE lifecycle_cases ADD COLUMN IF NOT EXISTS template_version "
    "INTEGER NULL",
    "ALTER TABLE lifecycle_tasks ADD COLUMN IF NOT EXISTS description "
    f"VARCHAR({DESCRIPTION_MAX}) NULL",
    "ALTER TABLE lifecycle_tasks ADD COLUMN IF NOT EXISTS required "
    "BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE lifecycle_tasks ADD COLUMN IF NOT EXISTS requires_file "
    "BOOLEAN NOT NULL DEFAULT FALSE",
    f"ALTER TABLE lifecycle_tasks ADD COLUMN IF NOT EXISTS key VARCHAR({KEY_MAX}) NULL",
    "ALTER TABLE lifecycle_tasks ADD COLUMN IF NOT EXISTS source "
    "VARCHAR(16) NOT NULL DEFAULT 'manual'",
    "ALTER TABLE lifecycle_tasks ADD COLUMN IF NOT EXISTS source_label "
    "VARCHAR(160) NULL",
    "ALTER TABLE lifecycle_tasks ADD COLUMN IF NOT EXISTS due_offset_days "
    "SMALLINT NULL",
)
INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_lifecycle_template_items_template "
    "ON lifecycle_template_items (template_id, position)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_lifecycle_template_items_key "
    f"ON lifecycle_template_items (template_id, key) WHERE {ITEM_KEY_WHERE}",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_lifecycle_cases_live "
    f"ON lifecycle_cases (user_id, kind) WHERE {LIVE_CASE_WHERE}",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_lifecycle_cases_contract_live "
    f"ON lifecycle_cases (contract_id, kind) WHERE {LIVE_CONTRACT_CASE_WHERE}",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_lifecycle_cases_pending_email "
    f"ON lifecycle_cases (pending_email) WHERE {PENDING_EMAIL_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_lifecycle_cases_status_deactivate "
    "ON lifecycle_cases (status, deactivate_on)",
    "CREATE INDEX IF NOT EXISTS ix_lifecycle_cases_user ON lifecycle_cases (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_lifecycle_cases_contract "
    f"ON lifecycle_cases (contract_id) WHERE {CONTRACT_CASE_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_lifecycle_tasks_case "
    "ON lifecycle_tasks (case_id, position)",
    "CREATE INDEX IF NOT EXISTS ix_lifecycle_tasks_assignee_open "
    f"ON lifecycle_tasks (assignee_user_id, due_date) WHERE {OPEN_TASK_WHERE}",
)


def _ensure_check(table: str, name: str, expression: str, marker: str) -> str:
    """CHECK dołożony albo podmieniony, gdy jego definicja nie ma ``marker``.

    Starsza wersja 0461 założyła część CHECK-ów bez wartości etapu 3 (albo
    wcale) — blok podmienia je tylko przy starej definicji, więc entrypoint
    może go wykonywać przy każdym starcie.
    """

    return f"""DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = '{name}'
              AND conrelid = '{table}'::regclass
              AND pg_get_constraintdef(oid) LIKE '%{marker}%'
        ) THEN
            ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name};
            ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expression});
        END IF;
    END $$"""


#: Rodzaje pracy (``reports``, ``care``), nowe role wykonawców i nowe pola
#: etapu 3 w CHECK-ach tabel założonych wcześniejszą wersją 0461.
CONSTRAINT_DDL: tuple[str, ...] = (
    _ensure_check("work_handovers", "ck_work_handovers_kind", CK_HANDOVER_KIND, "care"),
    _ensure_check(
        "lifecycle_template_items",
        "ck_lifecycle_template_items_assignee",
        CK_ITEM_ASSIGNEE,
        "administration",
    ),
    _ensure_check(
        "lifecycle_tasks",
        "ck_lifecycle_tasks_assignee",
        CK_TASK_ASSIGNEE,
        "administration",
    ),
    _ensure_check(
        "lifecycle_cases", "ck_lifecycle_cases_person", CK_CASE_PERSON, "consultant"
    ),
    _ensure_check(
        "lifecycle_templates",
        "ck_lifecycle_templates_audience",
        CK_TEMPLATE_AUDIENCE,
        "consultant",
    ),
    _ensure_check(
        "lifecycle_templates",
        "ck_lifecycle_templates_version",
        CK_TEMPLATE_VERSION,
        "version",
    ),
    _ensure_check(
        "lifecycle_template_items",
        "ck_lifecycle_template_items_conditions",
        CK_ITEM_CONDITIONS,
        "jsonb_typeof",
    ),
    _ensure_check(
        "lifecycle_template_items",
        "ck_lifecycle_template_items_added_in",
        CK_ITEM_ADDED_IN_VERSION,
        "added_in_version",
    ),
    _ensure_check(
        "lifecycle_cases", "ck_lifecycle_cases_audience", CK_CASE_AUDIENCE, "consultant"
    ),
    _ensure_check(
        "lifecycle_cases",
        "ck_lifecycle_cases_consultant_contract",
        CK_CASE_CONSULTANT_CONTRACT,
        "contract_id",
    ),
    _ensure_check(
        "lifecycle_cases",
        "ck_lifecycle_cases_template_version",
        CK_CASE_TEMPLATE_VERSION,
        "template_version",
    ),
    _ensure_check(
        "lifecycle_tasks", "ck_lifecycle_tasks_source", CK_TASK_SOURCE, "manual"
    ),
)


def item(
    title: str,
    category: str,
    assignee: str,
    offset: int,
    *,
    description: str | None = None,
    required: bool = True,
    requires_file: bool = False,
    conditions: dict[str, Any] | None = None,
    key: str | None = None,
) -> dict[str, Any]:
    """Pozycja ścieżki startowej (zasiew i testy)."""

    return {
        "title": title,
        "category": category,
        "assignee_kind": assignee,
        "due_offset_days": offset,
        "description": description,
        "required": required,
        "requires_file": requires_file,
        "conditions": conditions or {},
        "key": key,
    }


#: Ścieżki startowe: (rodzaj, odbiorcy) → (nazwa, pozycje). Przesunięcia
#: w dniach roboczych. Kadry i head back office zmieniają je w Ustawieniach;
#: ścieżek się nie kasuje (wyłącza), więc zasiew nie wraca po restarcie.
#: „Konsultant u klienta” i „Koniec projektu konsultanta” — makieta M4
#: (17.10.2026); pakiet klienta dokłada do wejścia dokumenty, dostępy
#: i odbiór rzeczy od klienta (``client_pack.pack_tasks``), a zestaw i wydanie
#: sprzętu są tutaj, z warunkiem „sprzęt od nas”.
DEFAULT_TEMPLATES: dict[tuple[str, str], tuple[str, tuple[dict[str, Any], ...]]] = {
    ("onboarding", "team"): (
        "Wejście — standard",
        (
            item("Konto Microsoft 365", "accounts", "it", -2),
            item("Konto i rola w NEXUSIE", "accounts", "it", -2),
            item("Wydanie zestawu biurowego", "equipment", "reception", -2),
            item("Protokół wydania sprzętu do podpisu", "equipment", "reception", 0),
            item("Dokumenty kadrowe", "documents", "people_admin", 0),
            item("Rozmowa w pierwszym dniu", "meeting", "manager", 0),
            item("Rozmowa po pierwszym tygodniu", "meeting", "manager", 5),
            item("Rozmowa po pierwszym miesiącu", "meeting", "manager", 21),
        ),
    ),
    ("offboarding", "team"): (
        "Odejście — standard",
        (
            item("Rozmowa wyjściowa", "meeting", "manager", -2),
            item("Ostatni timesheet", "documents", "person", 0),
            item("Rozliczenie urlopu", "documents", "people_admin", 0),
            item("Zwrot sprzętu z ewidencji", "equipment", "reception", 0),
            item("Dezaktywacja karty dostępu w budynku", "equipment", "reception", 0),
            item("Wyłączenie skrzynki i licencji Microsoft 365", "accounts", "it", 1),
        ),
    ),
    ("onboarding", "consultant"): (
        "Konsultant u klienta",
        (
            item(
                "Umowa podpisana, dane do faktur",
                "documents",
                "administration",
                -7,
                description="Plik umowy w kontrakcie.",
                requires_file=True,
                conditions={"employment_types": ["b2b"]},
            ),
            item(
                "Oświadczenie studenta i zgłoszenie do ZUS",
                "documents",
                "people_admin",
                -7,
                conditions={"employment_types": ["zlecenie"], "student": True},
            ),
            item(
                "Przygotuj zestaw sprzętu",
                "equipment",
                "reception",
                -7,
                description="Rzeczy od nas z pakietu klienta.",
                conditions={"equipment": "ours"},
                key=KEY_EQUIPMENT_KIT,
            ),
            item(
                "Mail powitalny do konsultanta",
                "other",
                "care_owner",
                -3,
                description="Podgląd przed wysłaniem — wysyła opiekun.",
                key=KEY_WELCOME_MAIL,
            ),
            item(
                "Wydanie sprzętu i protokół",
                "equipment",
                "reception",
                0,
                description="Wzór protokołu z pakietu klienta.",
                conditions={"equipment": "ours"},
                key=KEY_EQUIPMENT_ISSUE,
            ),
            item(
                "Dostępy klienta działają",
                "accounts",
                "care_owner",
                0,
                description="VPN, konto i narzędzia z pakietu klienta.",
                required=False,
            ),
            item("Rozmowa po pierwszym dniu", "meeting", "care_owner", 1),
            item(
                "Rozmowa po dwóch tygodniach",
                "meeting",
                "care_owner",
                10,
                description="Sprzęt, dostępy, zespół.",
            ),
            item(
                "Pierwsza opinia menedżera u klienta",
                "meeting",
                "delivery_lead",
                21,
                required=False,
            ),
        ),
    ),
    ("offboarding", "consultant"): (
        "Koniec projektu konsultanta",
        (
            item(
                "Rozmowa przed końcem projektu",
                "meeting",
                "care_owner",
                -10,
                description="Co dalej: przedłużenie, nowy projekt, przerwa.",
            ),
            item(
                "Zwrot sprzętu według pakietu klienta",
                "equipment",
                "reception",
                0,
                conditions={"equipment": "ours"},
            ),
            item(
                "Dostępy klienta wyłączone",
                "accounts",
                "delivery_lead",
                0,
                required=False,
            ),
            item(
                "Rozliczenie ostatniego miesiąca",
                "documents",
                "administration",
                5,
            ),
        ),
    ),
}


def _sql_text(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def _seed_statement(kind: str, audience: str) -> str:
    name, items = DEFAULT_TEMPLATES[(kind, audience)]
    values = ", ".join(
        "("
        + ", ".join(
            (
                str(position),
                _sql_text(spec["title"]),
                f"'{spec['category']}'",
                f"'{spec['assignee_kind']}'",
                str(spec["due_offset_days"]),
                _sql_text(spec["description"]),
                "TRUE" if spec["required"] else "FALSE",
                "TRUE" if spec["requires_file"] else "FALSE",
                _sql_text(json.dumps(spec["conditions"], sort_keys=True)) + "::jsonb",
                _sql_text(spec["key"]),
            )
        )
        + ")"
        for position, spec in enumerate(items)
    )
    return (
        "WITH seeded AS ("
        " INSERT INTO lifecycle_templates (kind, name, audience)"
        f" SELECT '{kind}', {_sql_text(name)}, '{audience}'"
        " WHERE NOT EXISTS (SELECT 1 FROM lifecycle_templates"
        f" WHERE kind = '{kind}' AND audience = '{audience}') RETURNING id)"
        " INSERT INTO lifecycle_template_items"
        " (template_id, position, title, category, assignee_kind, due_offset_days,"
        " description, required, requires_file, conditions, key)"
        " SELECT seeded.id, v.position, v.title, v.category, v.assignee_kind,"
        " v.offset_days, v.description, v.required, v.requires_file, v.conditions,"
        " v.key"
        f" FROM seeded, (VALUES {values})"
        " AS v(position, title, category, assignee_kind, offset_days, description,"
        " required, requires_file, conditions, key)"
    )


DATA_DDL: tuple[str, ...] = tuple(
    _seed_statement(kind, audience) for kind, audience in DEFAULT_TEMPLATES
)
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
