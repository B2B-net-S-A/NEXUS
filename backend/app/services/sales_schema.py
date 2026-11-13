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

LEAD_SOURCES: tuple[str, ...] = (
    "job_board",
    "linkedin",
    "press",
    "manual",
    "atlas",
    # 0676: sygnał z raportu bota researchu (Grok Bot), ``SIGNALS_DDL`` niżej.
    "research",
)
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


# ── 0618: historia zmian szansy (jak „Historia zmian” w Atlasie) ─────────────
# Jeden wiersz na zmienione pole: kto (``user_id``), kiedy, co było i co jest.
# Wartości jako tekst (id etapu, opiekuna, firmy, kwota, data ISO) — nazwy
# etapów i osób dokłada odczyt, więc w tabeli nie ma nazwisk. Wejście na etap
# to ``field = 'stage_id'`` (także przy założeniu szansy) — z tego samego
# źródła liczy się KPI „ofert” per etap. Import z Atlasa zdarzeń nie zapisuje
# (historia zaczyna się od pracy w NEXUSIE).


class OpportunityEventKind(StrEnum):
    created = "created"
    updated = "updated"
    archived = "archived"
    restored = "restored"
    company_merged = "company_merged"


OPPORTUNITY_EVENT_KINDS = _values(OpportunityEventKind)
CK_OPPORTUNITY_EVENT_KIND = f"kind IN ({quoted(OPPORTUNITY_EVENT_KINDS)})"

HISTORY_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS sales_opportunity_events (
    id BIGSERIAL PRIMARY KEY,
    opportunity_id INTEGER NOT NULL REFERENCES sales_opportunities(id) ON DELETE CASCADE,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    kind VARCHAR(20) NOT NULL,
    field VARCHAR(40) NULL,
    old_value TEXT NULL,
    new_value TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_sales_opportunity_events_kind CHECK ({CK_OPPORTUNITY_EVENT_KIND})
)""",
    "CREATE INDEX IF NOT EXISTS ix_sales_opportunity_events_opportunity "
    "ON sales_opportunity_events (opportunity_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_sales_opportunity_events_field "
    "ON sales_opportunity_events (field, created_at)",
)

HISTORY_DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE IF EXISTS sales_opportunity_events",
)


# ── 0623: cele i KPI tygodniowe handlowców (decyzja Artura 28.10.2026) ─────
# * ``sales_targets`` — cele tygodniowe osoby (spotkania, leady kwalifikowane,
#   wejścia na etap „Oferta wysłana”), opcjonalny cel marży (netto MRR)
#   z terminem i drużyna. Wiersz bez ``user_id`` to cel firmy (netto MRR),
#   który w Atlasie był stałą w kodzie. Kwot nie ma w kodzie — wpisuje admin.
# * KPI „Oferty” liczy wejścia na etap ``offer-sent`` z historii zmian szansy
#   (``sales_opportunity_events``, 0618) — NEXUS nie ma ofert.

TARGETS_DDL: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS sales_targets (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE CASCADE,
    meetings INTEGER NOT NULL DEFAULT 0,
    qualified INTEGER NOT NULL DEFAULT 0,
    offers_stage INTEGER NOT NULL DEFAULT 0,
    margin_goal_amount NUMERIC(14, 2) NULL,
    margin_goal_deadline DATE NULL,
    team VARCHAR(60) NULL,
    updated_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_sales_targets_weekly CHECK (meetings >= 0 AND qualified >= 0 AND offers_stage >= 0),
    CONSTRAINT ck_sales_targets_margin CHECK (margin_goal_amount IS NULL OR margin_goal_amount >= 0)
)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_sales_targets_user "
    "ON sales_targets (user_id) WHERE user_id IS NOT NULL",
    # Jeden wiersz firmowy: wszystkie mają tę samą wartość wyrażenia.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_sales_targets_company "
    "ON sales_targets ((user_id IS NULL)) WHERE user_id IS NULL",
)

TARGETS_DOWNGRADE_DDL: tuple[str, ...] = ("DROP TABLE IF EXISTS sales_targets",)


# ── 0624: bieżąca poczta i kalendarz Outlooka handlowców (28.10.2026) ──────
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

# ── 0628: transkrypty Teams przy spotkaniach handlowców (decyzja Artura 02.11.2026) ──
# Klucz to ``iCalUId``, a nie aktywność: jedno spotkanie bywa przy kilku firmach,
# a transkrypt pobieramy raz. Bez FK do ``sales_activities`` z tego samego powodu.

TRANSCRIPT_STATUSES: tuple[str, ...] = (
    "waiting",
    "fetched",
    "missing",
    "not_online",
    "forbidden",
    "error",
)
CK_TRANSCRIPT_STATUS = f"status IN ({quoted(TRANSCRIPT_STATUSES)})"

TRANSCRIPTS_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS sales_meeting_transcripts (
    id BIGSERIAL PRIMARY KEY,
    ical_uid VARCHAR(255) NOT NULL,
    organizer_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    organizer_upn VARCHAR(320) NOT NULL,
    graph_event_id VARCHAR(512) NOT NULL,
    organizer_aad_id VARCHAR(64),
    join_url VARCHAR(2000),
    online_meeting_id VARCHAR(512),
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'waiting',
    fetch_attempts INTEGER NOT NULL DEFAULT 0,
    next_fetch_at TIMESTAMPTZ,
    last_error VARCHAR(120),
    graph_transcript_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    plain_text TEXT,
    fetched_at TIMESTAMPTZ,
    summary TEXT,
    summary_attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_sales_meeting_transcripts_ical UNIQUE (ical_uid),
    CONSTRAINT ck_sales_meeting_transcripts_status CHECK ({CK_TRANSCRIPT_STATUS})
)""",
    "CREATE INDEX IF NOT EXISTS ix_sales_meeting_transcripts_queue "
    "ON sales_meeting_transcripts (next_fetch_at) WHERE next_fetch_at IS NOT NULL",
)

TRANSCRIPTS_DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE IF EXISTS sales_meeting_transcripts",
)


# ── 0671: inne nazwy firmy z CV (etap P8, 09.11.2026) ─────────────────────
# Decyzja handlowca przy wariancie nazwy z CV: „Dołącz” (``joined``) doliczamy
# do „Kogo znamy”, „Nie ta firma” (``rejected``) tylko przestajemy podpowiadać.
# Cofnięcie kasuje wiersz, bo to decyzja, a nie dane o firmie. Klucz po
# ``normalize_company_name``, więc jedna decyzja obejmuje każdą pisownię.

COMPANY_ALIAS_STATUSES: tuple[str, ...] = ("joined", "rejected")
CK_COMPANY_ALIAS_STATUS = f"status IN ({quoted(COMPANY_ALIAS_STATUSES)})"

COMPANY_ALIASES_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS sales_company_aliases (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES sales_companies(id) ON DELETE CASCADE,
    alias VARCHAR(500) NOT NULL,
    normalized_alias VARCHAR(500) NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_sales_company_aliases_name UNIQUE (company_id, normalized_alias),
    CONSTRAINT ck_sales_company_aliases_status CHECK ({CK_COMPANY_ALIAS_STATUS})
)""",
)

COMPANY_ALIASES_DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE IF EXISTS sales_company_aliases",
)

# ── 0672: wynik rozmowy i sprzeciw wobec kontaktu ────────────────────────
#
# Wynik zapisany w polu, nie tylko w temacie wpisu, żeby dało się go policzyć.
# ``sales_contacts`` nie miało dotąd żadnego pola zgody ani sprzeciwu.

CALL_OUTCOMES: tuple[str, ...] = (
    "connected",
    "no_answer",
    "call_back",
    "wants_offer",
    "not_now",
    "do_not_contact",
    # 0681: wyniki z kolejki dzwonienia (jeden słownik dla karty szansy i kolejki).
    "offer_sent",
    "meeting_booked",
    # 0683: z Excela dzwoniących (decyzje Artura 11.11.2026).
    "not_interested",
    "bad_contact",
)
CK_ACTIVITY_OUTCOME = f"outcome IS NULL OR outcome IN ({quoted(CALL_OUTCOMES)})"

CALL_OUTCOME_DDL: tuple[str, ...] = (
    "ALTER TABLE sales_activities ADD COLUMN IF NOT EXISTS outcome VARCHAR(20) NULL",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'ck_sales_activities_outcome') THEN "
    "ALTER TABLE sales_activities ADD CONSTRAINT ck_sales_activities_outcome "
    f"CHECK ({CK_ACTIVITY_OUTCOME}); END IF; END $$",
    "ALTER TABLE sales_contacts ADD COLUMN IF NOT EXISTS "
    "do_not_contact_at TIMESTAMPTZ NULL",
    "ALTER TABLE sales_contacts ADD COLUMN IF NOT EXISTS do_not_contact_by_user_id "
    "INTEGER NULL REFERENCES users(id) ON DELETE SET NULL",
)

CALL_OUTCOME_DOWNGRADE_DDL: tuple[str, ...] = (
    "ALTER TABLE sales_contacts DROP COLUMN IF EXISTS do_not_contact_by_user_id",
    "ALTER TABLE sales_contacts DROP COLUMN IF EXISTS do_not_contact_at",
    "ALTER TABLE sales_activities DROP CONSTRAINT IF EXISTS ck_sales_activities_outcome",
    "ALTER TABLE sales_activities DROP COLUMN IF EXISTS outcome",
)

# ── 0676: kanał sygnałów z bota researchu (Grok Bot) ─────────────────────
#
# NEXUS zakłada bieg, wysyła botowi nazwy i domeny firm z jednorazowym tokenem,
# a bot odsyła jeden raport. ``token_hash`` to SHA-256 tokenu: samego tokenu baza
# nie trzyma. ``kind``: ``signals`` (tygodniowy przegląd firm z tagiem pilota)
# albo ``briefing`` (punkty do rozmowy dla firm z leadami i szansami).
# Punkty firmy to jeden wiersz na firmę, nadpisywany kolejnym biegiem.

SIGNAL_RUN_KINDS: tuple[str, ...] = ("signals", "briefing")
SIGNAL_RUN_STATUSES: tuple[str, ...] = ("started", "received", "expired", "failed")
BRIEFING_MODES: tuple[str, ...] = ("first_call", "ongoing")
CK_SIGNAL_RUN_KIND = f"kind IN ({quoted(SIGNAL_RUN_KINDS)})"
CK_SIGNAL_RUN_STATUS = f"status IN ({quoted(SIGNAL_RUN_STATUSES)})"
CK_BRIEFING_MODE = f"mode IN ({quoted(BRIEFING_MODES)})"

SIGNALS_DDL: tuple[str, ...] = (
    # Nowe źródło leada. Stary CHECK z 0602 nie zna ``research``; podmiana tylko
    # wtedy, gdy definicja go jeszcze nie ma, bo entrypoint biegnie przy każdym starcie.
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'ck_sales_leads_source' "
    "AND pg_get_constraintdef(oid) LIKE '%research%') THEN "
    "ALTER TABLE sales_leads DROP CONSTRAINT IF EXISTS ck_sales_leads_source; "
    "ALTER TABLE sales_leads ADD CONSTRAINT ck_sales_leads_source "
    f"CHECK ({CK_LEAD_SOURCE}); END IF; END $$",
    f"""CREATE TABLE IF NOT EXISTS sales_signal_runs (
    id SERIAL PRIMARY KEY,
    kind VARCHAR(16) NOT NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'started',
    company_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    modes JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    token_hash VARCHAR(64) NULL,
    token_expires_at TIMESTAMPTZ NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    received_at TIMESTAMPTZ NULL,
    report JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    error VARCHAR(255) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_sales_signal_runs_kind CHECK ({CK_SIGNAL_RUN_KIND}),
    CONSTRAINT ck_sales_signal_runs_status CHECK ({CK_SIGNAL_RUN_STATUS})
)""",
    "CREATE INDEX IF NOT EXISTS ix_sales_signal_runs_kind_started "
    "ON sales_signal_runs (kind, started_at DESC)",
    f"""CREATE TABLE IF NOT EXISTS sales_company_briefings (
    company_id INTEGER PRIMARY KEY REFERENCES sales_companies(id) ON DELETE CASCADE,
    mode VARCHAR(12) NOT NULL,
    points JSONB NOT NULL DEFAULT '[]'::jsonb,
    run_id INTEGER NULL REFERENCES sales_signal_runs(id) ON DELETE SET NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_sales_company_briefings_mode CHECK ({CK_BRIEFING_MODE})
)""",
)

_LEAD_SOURCES_BEFORE_SIGNALS = tuple(s for s in LEAD_SOURCES if s != "research")

SIGNALS_DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE IF EXISTS sales_company_briefings",
    "DROP TABLE IF EXISTS sales_signal_runs",
    "DELETE FROM sales_leads WHERE source = 'research'",
    "ALTER TABLE sales_leads DROP CONSTRAINT IF EXISTS ck_sales_leads_source",
    "ALTER TABLE sales_leads ADD CONSTRAINT ck_sales_leads_source "
    f"CHECK (source IN ({quoted(_LEAD_SOURCES_BEFORE_SIGNALS)}))",
)

# ── 0677: podsumowanie spotkania dla klienta (09.11.2026) ─────────────────
# Szkic modelu F46 zapisany przy transkrypcie, żeby ponowne otwarcie okna nie
# wołało modelu drugi raz, klucz żądania wysyłki (drugi klik „Wyślij” z tym
# samym kluczem nie wysyła drugiego maila do klienta) i chwila ostatniej wysyłki,
# którą okno pokazuje przed ponowną.

CLIENT_SUMMARY_DDL: tuple[str, ...] = (
    "ALTER TABLE sales_meeting_transcripts ADD COLUMN IF NOT EXISTS "
    "client_summary TEXT NULL",
    "ALTER TABLE sales_meeting_transcripts ADD COLUMN IF NOT EXISTS "
    "client_mail_request_id VARCHAR(64) NULL",
    "ALTER TABLE sales_meeting_transcripts ADD COLUMN IF NOT EXISTS "
    "client_mail_sent_at TIMESTAMPTZ NULL",
)

CLIENT_SUMMARY_DOWNGRADE_DDL: tuple[str, ...] = (
    "ALTER TABLE sales_meeting_transcripts DROP COLUMN IF EXISTS client_mail_sent_at",
    "ALTER TABLE sales_meeting_transcripts DROP COLUMN IF EXISTS client_mail_request_id",
    "ALTER TABLE sales_meeting_transcripts DROP COLUMN IF EXISTS client_summary",
)

# ── 0681: kampanie dzwonienia i kolejka (decyzje Artura 10.11.2026) ───────
#
# Wynik telefonu przestaje być szansą. Kampania to usługa, lista i skrypt rozmowy,
# a rekord to firma, osoba, telefon, „skąd kontakt”, stan w kolejce, data
# oddzwonienia i kto dzwoni. Szansa powstaje dopiero z umówionego spotkania
# (``opportunity_id``). Rekord bez kampanii to wpis kolejki dla istniejącej szansy
# dzwoniącego z etapu „Lead”: jeden na szansę (``ux_sales_call_records_opportunity``).
# Stan rekordu to ``new`` albo ostatni wynik z kolejki, nazwany jak ``CALL_OUTCOMES``.

CALL_QUEUE_OUTCOMES: tuple[str, ...] = (
    "no_answer",
    "call_back",
    "not_now",
    "offer_sent",
    "meeting_booked",
    "do_not_contact",
    # 0683: „Nie zainteresowany” wraca po wybranym czasie albo nigdy, „Zły numer /
    # brak danych” zamyka rekord. To nie jest sprzeciw: firma i osoba zostają do
    # kontaktu z innej drogi.
    "not_interested",
    "bad_contact",
)
CALL_RECORD_NEW = "new"
CALL_RECORD_STATES: tuple[str, ...] = (CALL_RECORD_NEW, *CALL_QUEUE_OUTCOMES)
CK_CALL_CAMPAIGN_NAME = "char_length(btrim(name)) > 0"
CK_CALL_RECORD_STATE = f"state IN ({quoted(CALL_RECORD_STATES)})"
CK_CALL_RECORD_ATTEMPTS = "attempts >= 0"

CALLING_DDL: tuple[str, ...] = (
    # Stary CHECK z 0672 nie zna wyników kolejki; podmiana tylko wtedy, gdy definicja
    # ich jeszcze nie ma, bo entrypoint biegnie przy każdym starcie.
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'ck_sales_activities_outcome' "
    "AND pg_get_constraintdef(oid) LIKE '%meeting_booked%') THEN "
    "ALTER TABLE sales_activities DROP CONSTRAINT IF EXISTS ck_sales_activities_outcome; "
    "ALTER TABLE sales_activities ADD CONSTRAINT ck_sales_activities_outcome "
    f"CHECK ({CK_ACTIVITY_OUTCOME}); END IF; END $$",
    f"""CREATE TABLE IF NOT EXISTS sales_call_campaigns (
    id SERIAL PRIMARY KEY,
    name VARCHAR(160) NOT NULL,
    service VARCHAR(120) NULL,
    script TEXT NULL,
    created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    archived_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_sales_call_campaigns_name CHECK ({CK_CALL_CAMPAIGN_NAME})
)""",
    f"""CREATE TABLE IF NOT EXISTS sales_call_records (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER NULL REFERENCES sales_call_campaigns(id) ON DELETE CASCADE,
    company_id INTEGER NOT NULL REFERENCES sales_companies(id) ON DELETE CASCADE,
    contact_id INTEGER NULL REFERENCES sales_contacts(id) ON DELETE SET NULL,
    opportunity_id INTEGER NULL REFERENCES sales_opportunities(id) ON DELETE SET NULL,
    person_name VARCHAR(255) NULL,
    person_title VARCHAR(255) NULL,
    phone VARCHAR(60) NULL,
    email VARCHAR(255) NULL,
    contact_source VARCHAR(255) NULL,
    note TEXT NULL,
    state VARCHAR(20) NOT NULL DEFAULT 'new',
    callback_on DATE NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_outcome_at TIMESTAMPTZ NULL,
    assigned_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_sales_call_records_state CHECK ({CK_CALL_RECORD_STATE}),
    CONSTRAINT ck_sales_call_records_attempts CHECK ({CK_CALL_RECORD_ATTEMPTS})
)""",
    "CREATE INDEX IF NOT EXISTS ix_sales_call_records_queue "
    "ON sales_call_records (assigned_user_id, state, callback_on)",
    "CREATE INDEX IF NOT EXISTS ix_sales_call_records_company "
    "ON sales_call_records (company_id)",
    "CREATE INDEX IF NOT EXISTS ix_sales_call_records_campaign "
    "ON sales_call_records (campaign_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_sales_call_records_opportunity "
    "ON sales_call_records (opportunity_id) "
    "WHERE campaign_id IS NULL AND opportunity_id IS NOT NULL",
)

_CALL_OUTCOMES_BEFORE_QUEUE = tuple(
    o
    for o in CALL_OUTCOMES
    if o not in ("offer_sent", "meeting_booked", "not_interested", "bad_contact")
)

CALLING_DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE IF EXISTS sales_call_records",
    "DROP TABLE IF EXISTS sales_call_campaigns",
    "UPDATE sales_activities SET outcome = NULL "
    "WHERE outcome IN ('offer_sent', 'meeting_booked')",
    "ALTER TABLE sales_activities DROP CONSTRAINT IF EXISTS ck_sales_activities_outcome",
    "ALTER TABLE sales_activities ADD CONSTRAINT ck_sales_activities_outcome "
    f"CHECK (outcome IS NULL OR outcome IN ({quoted(_CALL_OUTCOMES_BEFORE_QUEUE)}))",
)


# ── 0683: „Nie zainteresowany” i „Zły numer / brak danych” ───────────────
#
# Podmiana obu CHECK-ów tylko wtedy, gdy definicja nie zna jeszcze nowych wyników,
# bo entrypoint biegnie przy każdym starcie (tak samo jak w 0681).

CK_CALL_DAY_TOTALS = "calls >= 0 AND talks >= 0 AND offers >= 0 AND meetings >= 0"
CALL_DAY_TOTALS_EXCEL = "excel"

CALL_OUTCOMES_V2_DDL: tuple[str, ...] = (
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'ck_sales_activities_outcome' "
    "AND pg_get_constraintdef(oid) LIKE '%not_interested%') THEN "
    "ALTER TABLE sales_activities DROP CONSTRAINT IF EXISTS ck_sales_activities_outcome; "
    "ALTER TABLE sales_activities ADD CONSTRAINT ck_sales_activities_outcome "
    f"CHECK ({CK_ACTIVITY_OUTCOME}); END IF; END $$",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'ck_sales_call_records_state' "
    "AND pg_get_constraintdef(oid) LIKE '%not_interested%') THEN "
    "ALTER TABLE sales_call_records DROP CONSTRAINT IF EXISTS ck_sales_call_records_state; "
    "ALTER TABLE sales_call_records ADD CONSTRAINT ck_sales_call_records_state "
    f"CHECK ({CK_CALL_RECORD_STATE}); END IF; END $$",
    # Podsumowania dni sprzed kolejki (ręczny wiersz „Podsumowanie” w Excelu
    # dzwoniących): jedna liczba na osobę, dzień i źródło, bez rozbicia na telefony.
    f"""CREATE TABLE IF NOT EXISTS sales_call_day_totals (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day DATE NOT NULL,
    source VARCHAR(40) NOT NULL,
    calls INTEGER NOT NULL DEFAULT 0,
    talks INTEGER NOT NULL DEFAULT 0,
    offers INTEGER NOT NULL DEFAULT 0,
    meetings INTEGER NOT NULL DEFAULT 0,
    created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_sales_call_day_totals_counts CHECK ({CK_CALL_DAY_TOTALS})
)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_sales_call_day_totals_user_day "
    "ON sales_call_day_totals (user_id, day, source)",
)

_CALL_OUTCOMES_0681 = tuple(
    o for o in CALL_OUTCOMES if o not in ("not_interested", "bad_contact")
)
_CALL_RECORD_STATES_0681 = tuple(
    s for s in CALL_RECORD_STATES if s not in ("not_interested", "bad_contact")
)

CALL_OUTCOMES_V2_DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE IF EXISTS sales_call_day_totals",
    "UPDATE sales_call_records SET state = 'not_now' "
    "WHERE state IN ('not_interested', 'bad_contact')",
    "UPDATE sales_activities SET outcome = NULL "
    "WHERE outcome IN ('not_interested', 'bad_contact')",
    "ALTER TABLE sales_activities DROP CONSTRAINT IF EXISTS ck_sales_activities_outcome",
    "ALTER TABLE sales_activities ADD CONSTRAINT ck_sales_activities_outcome "
    f"CHECK (outcome IS NULL OR outcome IN ({quoted(_CALL_OUTCOMES_0681)}))",
    "ALTER TABLE sales_call_records DROP CONSTRAINT IF EXISTS ck_sales_call_records_state",
    "ALTER TABLE sales_call_records ADD CONSTRAINT ck_sales_call_records_state "
    f"CHECK (state IN ({quoted(_CALL_RECORD_STATES_0681)}))",
)


# ── 0684: zadania bota (decyzje Artura 12.11.2026) ───────────────────────
#
# Jeden kanał bota dla wielu zadań: rodzaj biegu mówi, co bot ma zrobić
# (``services/sales/bot_tasks``). ``request`` to pola zlecenia, które rodzaj sam
# wysyła botowi (każde z uzasadnieniem w module rodzaju), ``requested_by_user_id``
# to osoba, która zleciła bieg z ekranu. Wyniki, o których decyduje handlowiec
# (przyjmij, odrzuć), leżą w ``sales_bot_results``; odcisk chroni decyzję przed
# kolejnym biegiem z tym samym wynikiem. Podmiana CHECK-ów tylko wtedy, gdy
# definicja nie zna jeszcze nowych wartości, bo entrypoint biegnie przy każdym starcie.

_BOT_RUN_KINDS_0684: tuple[str, ...] = (
    *SIGNAL_RUN_KINDS,
    "enrich",
    "question",
    "winback",
    "discovery",
    "people",
)
#: 0690 dokłada ``lists`` (Bot Listy, firmy pod kampanię z rejestr.io i researchu).
BOT_RUN_KINDS: tuple[str, ...] = (*_BOT_RUN_KINDS_0684, "lists")
BOT_BRIEFING_MODES: tuple[str, ...] = (*BRIEFING_MODES, "call_hook", "meeting_prep")
BOT_RESULT_STATUSES: tuple[str, ...] = ("new", "accepted", "rejected", "partial")
CK_BOT_RUN_KIND = f"kind IN ({quoted(BOT_RUN_KINDS)})"
CK_BOT_BRIEFING_MODE = f"mode IN ({quoted(BOT_BRIEFING_MODES)})"
CK_BOT_RESULT_STATUS = f"status IN ({quoted(BOT_RESULT_STATUSES)})"

BOT_TASKS_DDL: tuple[str, ...] = (
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'ck_sales_signal_runs_kind' "
    "AND pg_get_constraintdef(oid) LIKE '%people%') THEN "
    "ALTER TABLE sales_signal_runs DROP CONSTRAINT IF EXISTS ck_sales_signal_runs_kind; "
    "ALTER TABLE sales_signal_runs ADD CONSTRAINT ck_sales_signal_runs_kind "
    f"CHECK ({CK_BOT_RUN_KIND}); END IF; END $$",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'ck_sales_company_briefings_mode' "
    "AND pg_get_constraintdef(oid) LIKE '%meeting_prep%') THEN "
    "ALTER TABLE sales_company_briefings "
    "DROP CONSTRAINT IF EXISTS ck_sales_company_briefings_mode; "
    "ALTER TABLE sales_company_briefings ADD CONSTRAINT ck_sales_company_briefings_mode "
    f"CHECK ({CK_BOT_BRIEFING_MODE}); END IF; END $$",
    "ALTER TABLE sales_signal_runs ADD COLUMN IF NOT EXISTS "
    "request JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE sales_signal_runs ADD COLUMN IF NOT EXISTS "
    "requested_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL",
    f"""CREATE TABLE IF NOT EXISTS sales_bot_results (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES sales_signal_runs(id) ON DELETE CASCADE,
    kind VARCHAR(16) NOT NULL,
    company_id INTEGER NULL REFERENCES sales_companies(id) ON DELETE CASCADE,
    status VARCHAR(12) NOT NULL DEFAULT 'new',
    payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    fingerprint VARCHAR(200) NULL,
    decided_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    decided_at TIMESTAMPTZ NULL,
    decision_reason VARCHAR(300) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_sales_bot_results_fingerprint UNIQUE (fingerprint),
    CONSTRAINT ck_sales_bot_results_status CHECK ({CK_BOT_RESULT_STATUS})
)""",
    "CREATE INDEX IF NOT EXISTS ix_sales_bot_results_kind_status "
    "ON sales_bot_results (kind, status, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_sales_bot_results_company "
    "ON sales_bot_results (company_id)",
)

BOT_TASKS_DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE IF EXISTS sales_bot_results",
    "ALTER TABLE sales_signal_runs DROP COLUMN IF EXISTS requested_by_user_id",
    "ALTER TABLE sales_signal_runs DROP COLUMN IF EXISTS request",
    "DELETE FROM sales_company_briefings WHERE mode IN ('call_hook', 'meeting_prep')",
    "ALTER TABLE sales_company_briefings "
    "DROP CONSTRAINT IF EXISTS ck_sales_company_briefings_mode",
    "ALTER TABLE sales_company_briefings ADD CONSTRAINT ck_sales_company_briefings_mode "
    f"CHECK ({CK_BRIEFING_MODE})",
    f"DELETE FROM sales_signal_runs WHERE kind NOT IN ({quoted(SIGNAL_RUN_KINDS)})",
    "ALTER TABLE sales_signal_runs DROP CONSTRAINT IF EXISTS ck_sales_signal_runs_kind",
    "ALTER TABLE sales_signal_runs ADD CONSTRAINT ck_sales_signal_runs_kind "
    f"CHECK ({CK_SIGNAL_RUN_KIND})",
)


# 0690: Bot Listy (decyzja Artura 13.11.2026) — brief kampanii, z którego bot buduje
# i dosypuje listę do dzwonienia (``services/sales/bot_lists.py``).
BOT_LISTS_DDL: tuple[str, ...] = (
    "ALTER TABLE sales_call_campaigns ADD COLUMN IF NOT EXISTS bot_brief JSONB NULL",
    "ALTER TABLE sales_call_campaigns "
    "ADD COLUMN IF NOT EXISTS bot_built_at TIMESTAMPTZ NULL",
    # Rodzaj biegu ``lists``; podmiana tylko, gdy CHECK go jeszcze nie zna.
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'ck_sales_signal_runs_kind' "
    "AND pg_get_constraintdef(oid) LIKE '%''lists''%') THEN "
    "ALTER TABLE sales_signal_runs DROP CONSTRAINT IF EXISTS ck_sales_signal_runs_kind; "
    "ALTER TABLE sales_signal_runs ADD CONSTRAINT ck_sales_signal_runs_kind "
    f"CHECK ({CK_BOT_RUN_KIND}); END IF; END $$",
)
BOT_LISTS_DOWNGRADE_DDL: tuple[str, ...] = (
    "DELETE FROM sales_signal_runs WHERE kind = 'lists'",
    "ALTER TABLE sales_signal_runs DROP CONSTRAINT IF EXISTS ck_sales_signal_runs_kind",
    "ALTER TABLE sales_signal_runs ADD CONSTRAINT ck_sales_signal_runs_kind "
    f"CHECK (kind IN ({quoted(_BOT_RUN_KINDS_0684)}))",
    "ALTER TABLE sales_call_campaigns DROP COLUMN IF EXISTS bot_built_at",
    "ALTER TABLE sales_call_campaigns DROP COLUMN IF EXISTS bot_brief",
)
