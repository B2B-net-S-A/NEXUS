"""Sprzedaż (Atlas → NEXUS) — rdzeń: SQL migracji 0601 i lustra w ``entrypoint.sh``.

JEDNO źródło instrukcji dla ``alembic/versions/0601_sales_core.py``
i ``entrypoint.sh`` (alembic na produkcji bywa osierocony, więc entrypoint
jest wdrożeniem schematu). Decyzje Artura 26.10.2026: sprzedaż budowana
w NEXUSIE od nowa, dane przychodzą importem z Atlasa (D1 = B).

Tabele:

* ``sales_pipelines`` / ``sales_pipeline_stages`` — lejki i etapy. Etap ma
  wynik (``open`` / ``won`` / ``lost``) i prawdopodobieństwo; ``qualifies``
  oznacza etap, od którego szansa jest zakwalifikowana (pierwszy taki etap
  ustawia ``qualified_at`` raz, cofnięcie go nie czyści — reguła Atlasa).
* ``sales_companies`` — kartoteka firm sprzedaży, OSOBNA od ``clients`` (D2):
  9 tys. firm z Atlasa (31% śmieci) nie zalewa listy klientów. ``client_id``
  łączy firmę z klientem po wygranej, ``parent_company_id`` to grupa
  kapitałowa (mBank ↔ mLeasing). ``normalized_name`` liczy
  ``normalize_company_name`` NEXUSA — tylko indeks, nie UNIQUE: w Atlasie
  UNIQUE na nazwie kanonicznej blokowało dwie różne spółki o tej samej nazwie.
* ``sales_contacts`` — osoby po stronie firmy (nie kandydaci z bazy).
* ``sales_opportunities`` — szanse. Firma wymagana (szansa bez firmy to
  w Atlasie 115 „sierot” z samą nazwą tekstem); ``roles`` to role, których
  klient szuka — z nich powstaje rekrutacja po wygranej.
* ``sales_opportunity_contacts`` — kto po stronie klienta i w jakiej roli.
* ``sales_activities`` — JEDNA tabela na telefony, maile, spotkania, zadania
  i notatki (Atlas miał dwie nakładające się: przy szansie i przy firmie).
* ``sales_files`` — pliki przy firmie albo szansie.

``external_ref`` (``atlas:<uuid>``) czyni import z Atlasa idempotentnym.
"""

from __future__ import annotations

from enum import StrEnum


class StageOutcome(StrEnum):
    open = "open"
    won = "won"
    lost = "lost"


class CompanyLifecycle(StrEnum):
    lead = "lead"
    prospect = "prospect"
    opportunity = "opportunity"
    customer = "customer"
    churned = "churned"
    disqualified = "disqualified"


class CompanyStatus(StrEnum):
    active = "active"
    inactive = "inactive"
    do_not_contact = "do_not_contact"


class OpportunityStatus(StrEnum):
    open = "open"
    won = "won"
    lost = "lost"


class ActivityKind(StrEnum):
    call = "call"
    email = "email"
    meeting = "meeting"
    task = "task"
    note = "note"


def _values(enum: type[StrEnum]) -> tuple[str, ...]:
    return tuple(member.value for member in enum)


STAGE_OUTCOMES = _values(StageOutcome)
COMPANY_LIFECYCLES = _values(CompanyLifecycle)
COMPANY_STATUSES = _values(CompanyStatus)
COMPANY_TIERS: tuple[str, ...] = ("strategic", "enterprise", "mid_market", "smb")
OPPORTUNITY_STATUSES = _values(OpportunityStatus)
#: Linie usług z Atlasa (wymagane przy zakładaniu szansy w Atlasie).
SERVICE_LINES: tuple[str, ...] = ("bodyleasing", "subscription", "core_solutions")
CONTACT_ROLES: tuple[str, ...] = (
    "decision_maker",
    "economic_buyer",
    "champion",
    "influencer",
    "blocker",
    "end_user",
)
ACTIVITY_KINDS = _values(ActivityKind)
PRIORITIES: tuple[str, ...] = ("low", "medium", "high")


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_STAGE_OUTCOME = f"outcome IN ({quoted(STAGE_OUTCOMES)})"
CK_STAGE_PROBABILITY = "probability BETWEEN 0 AND 100"
CK_COMPANY_LIFECYCLE = f"lifecycle_stage IN ({quoted(COMPANY_LIFECYCLES)})"
CK_COMPANY_STATUS = f"status IN ({quoted(COMPANY_STATUSES)})"
CK_COMPANY_TIER = f"tier IS NULL OR tier IN ({quoted(COMPANY_TIERS)})"
CK_COMPANY_NAME = "char_length(btrim(name)) > 0"
CK_COMPANY_NO_SELF_PARENT = "parent_company_id IS NULL OR parent_company_id <> id"
CK_CONTACT_NAME = "char_length(btrim(full_name)) > 0"
CK_OPPORTUNITY_STATUS = f"status IN ({quoted(OPPORTUNITY_STATUSES)})"
CK_OPPORTUNITY_SERVICE_LINE = (
    f"service_line IS NULL OR service_line IN ({quoted(SERVICE_LINES)})"
)
CK_OPPORTUNITY_PROBABILITY = "probability BETWEEN 0 AND 100"
CK_OPPORTUNITY_TITLE = "char_length(btrim(title)) > 0"
CK_OPPORTUNITY_CONTACT_ROLE = f"role IS NULL OR role IN ({quoted(CONTACT_ROLES)})"
CK_ACTIVITY_KIND = f"kind IN ({quoted(ACTIVITY_KINDS)})"
CK_ACTIVITY_PRIORITY = f"priority IS NULL OR priority IN ({quoted(PRIORITIES)})"
CK_FILE_OWNER = "company_id IS NOT NULL OR opportunity_id IS NOT NULL"

TABLES: tuple[str, ...] = (
    "sales_pipelines",
    "sales_pipeline_stages",
    "sales_companies",
    "sales_contacts",
    "sales_opportunities",
    "sales_opportunity_contacts",
    "sales_activities",
    "sales_files",
)

TABLE_DDL: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS sales_pipelines (
    id SERIAL PRIMARY KEY,
    key VARCHAR(40) NOT NULL,
    name VARCHAR(120) NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    is_default BOOLEAN NOT NULL DEFAULT false,
    archived_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_sales_pipelines_key UNIQUE (key)
)""",
    f"""CREATE TABLE IF NOT EXISTS sales_pipeline_stages (
    id SERIAL PRIMARY KEY,
    pipeline_id INTEGER NOT NULL REFERENCES sales_pipelines(id) ON DELETE CASCADE,
    key VARCHAR(60) NOT NULL,
    name VARCHAR(120) NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    probability INTEGER NOT NULL DEFAULT 0,
    outcome VARCHAR(8) NOT NULL DEFAULT 'open',
    qualifies BOOLEAN NOT NULL DEFAULT false,
    color VARCHAR(16) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_sales_pipeline_stages_key UNIQUE (pipeline_id, key),
    CONSTRAINT ck_sales_pipeline_stages_outcome CHECK ({CK_STAGE_OUTCOME}),
    CONSTRAINT ck_sales_pipeline_stages_probability CHECK ({CK_STAGE_PROBABILITY})
)""",
    f"""CREATE TABLE IF NOT EXISTS sales_companies (
    id SERIAL PRIMARY KEY,
    name VARCHAR(500) NOT NULL,
    legal_name VARCHAR(500) NULL,
    normalized_name VARCHAR(500) NOT NULL,
    nip VARCHAR(15) NULL,
    krs VARCHAR(20) NULL,
    regon VARCHAR(14) NULL,
    domain VARCHAR(255) NULL,
    website_url VARCHAR(500) NULL,
    linkedin_url VARCHAR(500) NULL,
    industry VARCHAR(255) NULL,
    size_range VARCHAR(40) NULL,
    hq_city VARCHAR(120) NULL,
    hq_country VARCHAR(2) NULL,
    description TEXT NULL,
    lifecycle_stage VARCHAR(20) NOT NULL DEFAULT 'lead',
    tier VARCHAR(20) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    source VARCHAR(60) NULL,
    parent_company_id INTEGER NULL REFERENCES sales_companies(id) ON DELETE SET NULL,
    client_id INTEGER NULL REFERENCES clients(id) ON DELETE SET NULL,
    owner_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    custom_fields JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    dates_backfill JSONB NULL,
    external_ref VARCHAR(80) NULL,
    archived_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_sales_companies_name CHECK ({CK_COMPANY_NAME}),
    CONSTRAINT ck_sales_companies_lifecycle CHECK ({CK_COMPANY_LIFECYCLE}),
    CONSTRAINT ck_sales_companies_status CHECK ({CK_COMPANY_STATUS}),
    CONSTRAINT ck_sales_companies_tier CHECK ({CK_COMPANY_TIER}),
    CONSTRAINT ck_sales_companies_no_self_parent CHECK ({CK_COMPANY_NO_SELF_PARENT})
)""",
    f"""CREATE TABLE IF NOT EXISTS sales_contacts (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NULL REFERENCES sales_companies(id) ON DELETE SET NULL,
    full_name VARCHAR(255) NOT NULL,
    first_name VARCHAR(120) NULL,
    last_name VARCHAR(120) NULL,
    title VARCHAR(255) NULL,
    email VARCHAR(255) NULL,
    phone VARCHAR(60) NULL,
    mobile_phone VARCHAR(60) NULL,
    linkedin_url VARCHAR(500) NULL,
    seniority VARCHAR(40) NULL,
    department VARCHAR(120) NULL,
    is_executive BOOLEAN NOT NULL DEFAULT false,
    notes TEXT NULL,
    source VARCHAR(40) NULL,
    created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    external_ref VARCHAR(80) NULL,
    archived_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_sales_contacts_name CHECK ({CK_CONTACT_NAME})
)""",
    f"""CREATE TABLE IF NOT EXISTS sales_opportunities (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES sales_companies(id) ON DELETE RESTRICT,
    pipeline_id INTEGER NOT NULL REFERENCES sales_pipelines(id) ON DELETE RESTRICT,
    stage_id INTEGER NOT NULL REFERENCES sales_pipeline_stages(id) ON DELETE RESTRICT,
    title VARCHAR(255) NOT NULL,
    description TEXT NULL,
    status VARCHAR(8) NOT NULL DEFAULT 'open',
    service_line VARCHAR(32) NULL,
    value NUMERIC(14, 2) NULL,
    mrr_value NUMERIC(14, 2) NULL,
    one_off_value NUMERIC(14, 2) NULL,
    margin_pct NUMERIC(5, 2) NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
    contract_months INTEGER NULL,
    probability INTEGER NOT NULL DEFAULT 0,
    expected_close_date DATE NULL,
    qualified_at TIMESTAMPTZ NULL,
    won_at TIMESTAMPTZ NULL,
    lost_at TIMESTAMPTZ NULL,
    lost_reason VARCHAR(500) NULL,
    primary_contact_id INTEGER NULL REFERENCES sales_contacts(id) ON DELETE SET NULL,
    roles JSONB NOT NULL DEFAULT '[]'::jsonb,
    source VARCHAR(60) NULL,
    campaign VARCHAR(120) NULL,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    custom_fields JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    owner_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    last_activity_at TIMESTAMPTZ NULL,
    keep_open_until DATE NULL,
    archived_at TIMESTAMPTZ NULL,
    archived_reason VARCHAR(255) NULL,
    external_ref VARCHAR(80) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_sales_opportunities_title CHECK ({CK_OPPORTUNITY_TITLE}),
    CONSTRAINT ck_sales_opportunities_status CHECK ({CK_OPPORTUNITY_STATUS}),
    CONSTRAINT ck_sales_opportunities_service_line CHECK ({CK_OPPORTUNITY_SERVICE_LINE}),
    CONSTRAINT ck_sales_opportunities_probability CHECK ({CK_OPPORTUNITY_PROBABILITY})
)""",
    f"""CREATE TABLE IF NOT EXISTS sales_opportunity_contacts (
    opportunity_id INTEGER NOT NULL REFERENCES sales_opportunities(id) ON DELETE CASCADE,
    contact_id INTEGER NOT NULL REFERENCES sales_contacts(id) ON DELETE CASCADE,
    role VARCHAR(30) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_sales_opportunity_contacts PRIMARY KEY (opportunity_id, contact_id),
    CONSTRAINT ck_sales_opportunity_contacts_role CHECK ({CK_OPPORTUNITY_CONTACT_ROLE})
)""",
    f"""CREATE TABLE IF NOT EXISTS sales_activities (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NULL REFERENCES sales_companies(id) ON DELETE CASCADE,
    opportunity_id INTEGER NULL REFERENCES sales_opportunities(id) ON DELETE SET NULL,
    contact_id INTEGER NULL REFERENCES sales_contacts(id) ON DELETE SET NULL,
    kind VARCHAR(12) NOT NULL,
    subject VARCHAR(500) NULL,
    body TEXT NULL,
    priority VARCHAR(8) NULL,
    due_at TIMESTAMPTZ NULL,
    occurred_at TIMESTAMPTZ NULL,
    done_at TIMESTAMPTZ NULL,
    is_pinned BOOLEAN NOT NULL DEFAULT false,
    assignee_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    external_source VARCHAR(40) NULL,
    external_ref VARCHAR(80) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_sales_activities_kind CHECK ({CK_ACTIVITY_KIND}),
    CONSTRAINT ck_sales_activities_priority CHECK ({CK_ACTIVITY_PRIORITY})
)""",
    f"""CREATE TABLE IF NOT EXISTS sales_files (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NULL REFERENCES sales_companies(id) ON DELETE CASCADE,
    opportunity_id INTEGER NULL REFERENCES sales_opportunities(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    content_type VARCHAR(120) NULL,
    size_bytes BIGINT NULL,
    storage_key VARCHAR(500) NOT NULL,
    folder VARCHAR(120) NULL,
    uploaded_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    external_ref VARCHAR(80) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_sales_files_owner CHECK ({CK_FILE_OWNER})
)""",
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_sales_pipeline_stages_pipeline "
    "ON sales_pipeline_stages (pipeline_id, position)",
    "CREATE INDEX IF NOT EXISTS ix_sales_companies_normalized_name "
    "ON sales_companies (normalized_name)",
    "CREATE INDEX IF NOT EXISTS ix_sales_companies_nip ON sales_companies (nip)",
    "CREATE INDEX IF NOT EXISTS ix_sales_companies_parent "
    "ON sales_companies (parent_company_id)",
    "CREATE INDEX IF NOT EXISTS ix_sales_companies_owner "
    "ON sales_companies (owner_user_id)",
    # Jedna firma sprzedaży na klienta — po wygranej łączymy, nie dublujemy.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_sales_companies_client "
    "ON sales_companies (client_id) WHERE client_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_sales_companies_external_ref "
    "ON sales_companies (external_ref) WHERE external_ref IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_sales_contacts_company ON sales_contacts (company_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_sales_contacts_external_ref "
    "ON sales_contacts (external_ref) WHERE external_ref IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_sales_opportunities_company "
    "ON sales_opportunities (company_id)",
    "CREATE INDEX IF NOT EXISTS ix_sales_opportunities_stage "
    "ON sales_opportunities (pipeline_id, stage_id)",
    "CREATE INDEX IF NOT EXISTS ix_sales_opportunities_owner "
    "ON sales_opportunities (owner_user_id)",
    "CREATE INDEX IF NOT EXISTS ix_sales_opportunities_status "
    "ON sales_opportunities (status)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_sales_opportunities_external_ref "
    "ON sales_opportunities (external_ref) WHERE external_ref IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_sales_opportunity_contacts_contact "
    "ON sales_opportunity_contacts (contact_id)",
    "CREATE INDEX IF NOT EXISTS ix_sales_activities_company "
    "ON sales_activities (company_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_sales_activities_opportunity "
    "ON sales_activities (opportunity_id, created_at)",
    # Lista zadań: otwarte zadania osoby po terminie.
    "CREATE INDEX IF NOT EXISTS ix_sales_activities_open_tasks "
    "ON sales_activities (assignee_user_id, due_at) "
    "WHERE kind = 'task' AND done_at IS NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_sales_activities_external_ref "
    "ON sales_activities (external_ref) WHERE external_ref IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_sales_files_company ON sales_files (company_id)",
    "CREATE INDEX IF NOT EXISTS ix_sales_files_opportunity "
    "ON sales_files (opportunity_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_sales_files_external_ref "
    "ON sales_files (external_ref) WHERE external_ref IS NOT NULL",
)

#: Domyślny lejek „Sprzedaż” — etapy jak w Atlasie (migracja kpi01), z tym że
#: „Niezakwalifikowany” to w Atlasie etap przegranej (is_lost) na pozycji 4.
DEFAULT_PIPELINE_KEY = "sales"
DEFAULT_STAGES: tuple[tuple[str, str, int, str, bool], ...] = (
    # (key, nazwa, prawdopodobieństwo, wynik, kwalifikuje)
    ("lead", "Lead", 5, "open", False),
    ("qualifying-meeting", "Spotkanie kwalifikujące", 20, "open", False),
    ("qualified", "Lead kwalifikowany", 40, "open", True),
    ("offer-sent", "Oferta wysłana", 60, "open", False),
    ("not-qualified", "Niezakwalifikowany", 0, "lost", False),
    ("won", "Wygrana", 100, "won", False),
    ("lost", "Przegrana", 0, "lost", False),
)

_STAGE_ROWS = ", ".join(
    f"('{key}', '{name}', {position}, {probability}, '{outcome}', "
    f"{'true' if qualifies else 'false'})"
    for position, (key, name, probability, outcome, qualifies) in enumerate(
        DEFAULT_STAGES
    )
)

DATA_DDL: tuple[str, ...] = (
    "INSERT INTO sales_pipelines (key, name, position, is_default) VALUES "
    f"('{DEFAULT_PIPELINE_KEY}', 'Sprzedaż', 0, true) ON CONFLICT (key) DO NOTHING",
    # Etapy tylko dla lejka bez etapów — restart nie odtwarza etapu, który
    # admin świadomie usunął albo przemianował.
    "INSERT INTO sales_pipeline_stages "
    "(pipeline_id, key, name, position, probability, outcome, qualifies) "
    "SELECT p.id, s.key, s.name, s.position, s.probability, s.outcome, s.qualifies "
    f"FROM sales_pipelines p CROSS JOIN (VALUES {_STAGE_ROWS}) "
    "AS s(key, name, position, probability, outcome, qualifies) "
    f"WHERE p.key = '{DEFAULT_PIPELINE_KEY}' AND NOT EXISTS ("
    "SELECT 1 FROM sales_pipeline_stages x WHERE x.pipeline_id = p.id)",
)

ALL_DDL: tuple[str, ...] = TABLE_DDL + INDEX_DDL + DATA_DDL


# ── 0602: skrzynka leadów (etap 4) ─────────────────────────────────────────
# Sygnał, że firma może kupić: skan ogłoszeń (NoFluffJobs), import z Atlasa
# (LinkedIn, prasa), wpis ręczny. ``fingerprint`` zszywa ten sam sygnał
# z kolejnych skanów. Lead z firmy, która jest już klientem NEXUSA, nie
# powstaje — popyt u klientów idzie do DL (decyzja Artura 22.10.2026).

LEAD_SOURCES: tuple[str, ...] = ("job_board", "linkedin", "press", "manual", "atlas")
LEAD_STATUSES: tuple[str, ...] = ("new", "contacted", "converted", "dismissed")
CK_LEAD_SOURCE = f"source IN ({quoted(LEAD_SOURCES)})"
CK_LEAD_STATUS = f"status IN ({quoted(LEAD_STATUSES)})"
CK_LEAD_SCORE = "score BETWEEN 0 AND 100"
CK_LEAD_TITLE = "char_length(btrim(title)) > 0"

LEAD_TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS sales_leads (
    id SERIAL PRIMARY KEY,
    source VARCHAR(16) NOT NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'new',
    title VARCHAR(500) NOT NULL,
    summary TEXT NULL,
    company_name VARCHAR(500) NULL,
    company_id INTEGER NULL REFERENCES sales_companies(id) ON DELETE SET NULL,
    url VARCHAR(1000) NULL,
    score INTEGER NOT NULL DEFAULT 0,
    signal_at TIMESTAMPTZ NULL,
    fingerprint VARCHAR(200) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    assignee_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    opportunity_id INTEGER NULL REFERENCES sales_opportunities(id) ON DELETE SET NULL,
    dismissed_reason VARCHAR(255) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_sales_leads_fingerprint UNIQUE (fingerprint),
    CONSTRAINT ck_sales_leads_source CHECK ({CK_LEAD_SOURCE}),
    CONSTRAINT ck_sales_leads_status CHECK ({CK_LEAD_STATUS}),
    CONSTRAINT ck_sales_leads_score CHECK ({CK_LEAD_SCORE}),
    CONSTRAINT ck_sales_leads_title CHECK ({CK_LEAD_TITLE})
)""",
)

LEAD_INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_sales_leads_inbox "
    "ON sales_leads (status, score, signal_at)",
    "CREATE INDEX IF NOT EXISTS ix_sales_leads_company ON sales_leads (company_id)",
)

LEADS_DDL: tuple[str, ...] = LEAD_TABLE_DDL + LEAD_INDEX_DDL
LEADS_DOWNGRADE_DDL: tuple[str, ...] = ("DROP TABLE IF EXISTS sales_leads",)

DOWNGRADE_DDL: tuple[str, ...] = tuple(
    f"DROP TABLE IF EXISTS {table}" for table in reversed(TABLES)
)


# ── 0614: luki importu Atlasa (audyt 28.10.2026) ───────────────────────────
# * ``owner_label`` — opiekun z Atlasa, który nie ma konta w NEXUSIE (Atlas
#   trzymał go jako sam tekst). Admin przypisuje etykietę do konta na ekranie
#   „Opiekunowie z Atlasa”; nazwisk nie ma w kodzie ani w logach (repo jest
#   publiczne).
# * pola Outlooka przy aktywności: id wiadomości (klucz przyszłej
#   synchronizacji), link „otwórz w Outlooku”, kierunek, czas trwania.
# * ``sales_company_contacts`` — osoba bywa w kilku firmach (w Atlasie 224
#   powiązania z firmą inną niż główna), z rolą i stanowiskiem przy tej firmie.
#   ``sales_contacts.company_id`` zostaje firmą główną.
# * lista zadań obejmuje też telefony z terminem (w Atlasie Task Center
#   pokazywał każdy otwarty rodzaj).

ACTIVITY_DIRECTIONS: tuple[str, ...] = ("in", "out")
CK_ACTIVITY_DIRECTION = (
    f"direction IS NULL OR direction IN ({quoted(ACTIVITY_DIRECTIONS)})"
)
TASK_KINDS: tuple[str, ...] = ("task", "call")
SYNCED_TABLES: tuple[str, ...] = (
    "sales_companies",
    "sales_contacts",
    "sales_opportunities",
    "sales_activities",
)

GAPS_DDL: tuple[str, ...] = (
    "ALTER TABLE sales_companies ADD COLUMN IF NOT EXISTS owner_label VARCHAR(120) NULL",
    "CREATE INDEX IF NOT EXISTS ix_sales_companies_owner_label "
    "ON sales_companies (owner_label) WHERE owner_label IS NOT NULL",
    "ALTER TABLE sales_activities ADD COLUMN IF NOT EXISTS external_id VARCHAR(255) NULL",
    "ALTER TABLE sales_activities ADD COLUMN IF NOT EXISTS web_link VARCHAR(2000) NULL",
    "ALTER TABLE sales_activities ADD COLUMN IF NOT EXISTS direction VARCHAR(3) NULL",
    "ALTER TABLE sales_activities ADD COLUMN IF NOT EXISTS duration_minutes INTEGER NULL",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'ck_sales_activities_direction') THEN "
    "ALTER TABLE sales_activities ADD CONSTRAINT ck_sales_activities_direction "
    f"CHECK ({CK_ACTIVITY_DIRECTION}); END IF; END $$",
    "CREATE INDEX IF NOT EXISTS ix_sales_activities_open_items "
    "ON sales_activities (assignee_user_id, due_at) "
    f"WHERE kind IN ({quoted(TASK_KINDS)}) AND done_at IS NULL",
    """CREATE TABLE IF NOT EXISTS sales_company_contacts (
    company_id INTEGER NOT NULL REFERENCES sales_companies(id) ON DELETE CASCADE,
    contact_id INTEGER NOT NULL REFERENCES sales_contacts(id) ON DELETE CASCADE,
    role VARCHAR(60) NULL,
    title VARCHAR(255) NULL,
    is_primary BOOLEAN NOT NULL DEFAULT false,
    is_current BOOLEAN NOT NULL DEFAULT true,
    started_at DATE NULL,
    ended_at DATE NULL,
    external_ref VARCHAR(80) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_sales_company_contacts PRIMARY KEY (company_id, contact_id)
)""",
    "CREATE INDEX IF NOT EXISTS ix_sales_company_contacts_contact "
    "ON sales_company_contacts (contact_id)",
    # Kiedy wiersz ostatnio zapisał import. ``updated_at > synced_at`` znaczy
    # „zmienione w NEXUSIE po imporcie” — kolejny bieg nie nadpisuje wtedy pól,
    # które ludzie edytują (etap, status, tytuł, tagi, wykonanie zadania).
    *(
        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS synced_at TIMESTAMPTZ NULL"
        for table in SYNCED_TABLES
    ),
    # Firma główna kontaktu jest też powiązaniem (jedno źródło dla listy osób firmy).
    "INSERT INTO sales_company_contacts (company_id, contact_id, title, is_primary) "
    "SELECT company_id, id, title, true FROM sales_contacts "
    "WHERE company_id IS NOT NULL ON CONFLICT DO NOTHING",
)

GAPS_DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE IF EXISTS sales_company_contacts",
    "DROP INDEX IF EXISTS ix_sales_activities_open_items",
    "ALTER TABLE sales_activities DROP CONSTRAINT IF EXISTS ck_sales_activities_direction",
    "ALTER TABLE sales_activities DROP COLUMN IF EXISTS duration_minutes",
    "ALTER TABLE sales_activities DROP COLUMN IF EXISTS direction",
    "ALTER TABLE sales_activities DROP COLUMN IF EXISTS web_link",
    "ALTER TABLE sales_activities DROP COLUMN IF EXISTS external_id",
    *(
        f"ALTER TABLE {table} DROP COLUMN IF EXISTS synced_at"
        for table in SYNCED_TABLES
    ),
    "DROP INDEX IF EXISTS ix_sales_companies_owner_label",
    "ALTER TABLE sales_companies DROP COLUMN IF EXISTS owner_label",
)


# ── 0619: bieżąca poczta i kalendarz Outlooka handlowców (28.10.2026) ──────
# * ``emails.web_link`` — „Otwórz w Outlooku” (Graph ``webLink``).
# * ``calendar_events.m365_ical_uid`` — klucz spotkania wspólny dla wszystkich
#   skrzynek i dla historii z Atlasa; ``@removed`` z Graphu niesie samo id
#   wydarzenia, więc bez tej kolumny nie da się zdjąć odwołanego spotkania.
# * indeksy dopasowania (adres kontaktu, domena firmy, id z Outlooka) i UNIQUE
#   na wierszach synchronizacji NEXUSA — tylko bez ``external_ref`` (historia
#   z Atlasa ma go zawsze), więc indeks nie może się wywrócić na danych z importu.

OUTLOOK_SYNC_DDL: tuple[str, ...] = (
    "ALTER TABLE emails ADD COLUMN IF NOT EXISTS web_link VARCHAR(2000) NULL",
    "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS m365_ical_uid VARCHAR(255) NULL",
    "CREATE INDEX IF NOT EXISTS ix_calendar_events_m365_ical_uid "
    "ON calendar_events (m365_ical_uid) WHERE m365_ical_uid IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_sales_activities_external_id "
    "ON sales_activities (external_source, external_id) "
    "WHERE external_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_sales_activities_outlook "
    "ON sales_activities (external_source, external_id, company_id) "
    "WHERE external_id IS NOT NULL AND external_ref IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_sales_contacts_email_lower "
    "ON sales_contacts (lower(btrim(email))) WHERE email IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_sales_companies_mail_domain "
    "ON sales_companies ((regexp_replace(lower(btrim(domain)), "
    "'^([a-z]+://)?(www\\.)?([^/:?#]+).*$', '\\3')))",
)

OUTLOOK_SYNC_DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP INDEX IF EXISTS ix_sales_companies_mail_domain",
    "DROP INDEX IF EXISTS ix_sales_contacts_email_lower",
    "DROP INDEX IF EXISTS ux_sales_activities_outlook",
    "DROP INDEX IF EXISTS ix_sales_activities_external_id",
    "DROP INDEX IF EXISTS ix_calendar_events_m365_ical_uid",
    "ALTER TABLE calendar_events DROP COLUMN IF EXISTS m365_ical_uid",
    "ALTER TABLE emails DROP COLUMN IF EXISTS web_link",
)
