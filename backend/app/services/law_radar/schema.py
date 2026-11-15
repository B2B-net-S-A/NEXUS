"""Radar przepisów (decyzje Artura 15.11.2026): SQL migracji ``0715_law_radar``
i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0715_law_radar.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``).

Tabele:

* ``law_radar_runs`` — bieg Zbieracza (``collect``) albo Analityka
  (``analyze``): SHA-256 jednorazowego tokenu (2 godziny, raz), zlecenie
  wysłane botowi i podsumowanie liczbowe przyjęcia.
* ``law_radar_items`` — surowa pozycja od Zbieracza z odciskiem (bez powtórek),
  klasą źródła (``official`` / ``lex`` / ``practice``) i wynikiem bramki
  (``pending`` do sprawdzenia w API Sejmu, potem ``verified`` / ``unverified``
  / ``rejected``), dane z API Sejmu w ``official``.
* ``law_changes`` — zmiana w prawie od Analityka. Treść i etap aktualizuje
  kolejny bieg Analityka, status i decyzję wyłącznie człowiek.
* ``law_change_tasks`` — zadania przy zmianie (od bota albo dopisane ręcznie).
* ``law_change_events`` — dziennik: założenie, zmiana etapu, decyzja z powodem,
  zadania.
* ``law_change_probes`` — wynik sondy „u nas” (liczba, tekst, link, czas).
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted

RUN_KINDS: tuple[str, ...] = ("collect", "analyze")
RUN_STATUSES: tuple[str, ...] = ("started", "received", "failed", "expired")
#: Źródła Zbieracza; ``lex`` to konto księgowej (decyzja Artura 15.11.2026).
SOURCES: tuple[str, ...] = (
    "sejm",
    "rcl",
    "zus",
    "mf",
    "eureka",
    "pip",
    "uodo",
    "nsa",
    "eurlex",
    "advisor",
    "x",
    "lex",
    "other",
)
CLASSES: tuple[str, ...] = ("official", "lex", "practice")
GATES: tuple[str, ...] = ("pending", "verified", "unverified", "rejected")
ROLES: tuple[str, ...] = ("board", "accounting", "payroll", "contracts", "recruitment")
URGENCIES: tuple[str, ...] = ("now", "soon", "watch")
STAGES: tuple[str, ...] = (
    "project",
    "sejm",
    "senate",
    "president",
    "journal",
    "in_force",
)
STATUSES: tuple[str, ...] = ("new", "in_progress", "done", "not_applicable")
OPEN_STATUSES: tuple[str, ...] = ("new", "in_progress")
TASK_SOURCES: tuple[str, ...] = ("bot", "user")
EVENT_KINDS: tuple[str, ...] = (
    "created",
    "updated",
    "stage",
    "status",
    "task_added",
    "task_done",
    "task_reopened",
    "task_updated",
)

ITEM_TITLE_MAX = 300
URL_MAX = 1000
STAGE_TEXT_MAX = 200
QUOTE_MAX = 500
ACT_REF_MAX = 16
PRINT_NO_MAX = 8
FINGERPRINT_MAX = 64
GATE_REASON_MAX = 32
CHANGE_TITLE_MAX = 200
LEGAL_REF_MAX = 200
TASK_TEXT_MAX = 200
PROBE_KEY_MAX = 48
PROBE_TEXT_MAX = 300
LINK_MAX = 300
EVENT_VALUE_MAX = 32

#: Numer aktu w Dzienniku Ustaw albo Monitorze Polskim: ``DU/2026/473``.
ACT_REF_PATTERN = r"^(DU|MP)/[0-9]{4}/[0-9]{1,5}$"
#: Numer druku Sejmu (proces legislacyjny X kadencji).
PRINT_NO_PATTERN = r"^[0-9]{1,5}$"

CK_RUN_KIND = f"kind IN ({quoted(RUN_KINDS)})"
CK_RUN_STATUS = f"status IN ({quoted(RUN_STATUSES)})"
CK_ITEM_SOURCE = f"source IN ({quoted(SOURCES)})"
CK_ITEM_CLASS = f"klass IN ({quoted(CLASSES)})"
CK_ITEM_GATE = f"gate IN ({quoted(GATES)})"
#: Pozycja z LEX-u nigdy nie jest faktem urzędowym ani „praktyką”.
CK_ITEM_LEX = "(source = 'lex') = (klass = 'lex')"
CK_ITEM_ACT_REF = f"act_ref IS NULL OR act_ref ~ '{ACT_REF_PATTERN}'"
CK_ITEM_PRINT_NO = f"print_no IS NULL OR print_no ~ '{PRINT_NO_PATTERN}'"
CK_CHANGE_URGENCY = f"urgency IN ({quoted(URGENCIES)})"
CK_CHANGE_STAGE = f"stage IN ({quoted(STAGES)})"
CK_CHANGE_STATUS = f"status IN ({quoted(STATUSES)})"
#: „Nie dotyczy” zawsze z powodem (dziennik decyzji).
CK_CHANGE_NOT_APPLICABLE = "status <> 'not_applicable' OR decision_note IS NOT NULL"
CK_CHANGE_ARRAYS = (
    "jsonb_typeof(summary) = 'array' AND jsonb_typeof(roles) = 'array' "
    "AND jsonb_typeof(probe_keys) = 'array'"
)
CK_TASK_ROLE = f"role IS NULL OR role IN ({quoted(ROLES)})"
CK_TASK_SOURCE = f"source IN ({quoted(TASK_SOURCES)})"
CK_EVENT_KIND = f"kind IN ({quoted(EVENT_KINDS)})"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS law_radar_runs (
    id SERIAL PRIMARY KEY,
    kind VARCHAR(8) NOT NULL,
    status VARCHAR(10) NOT NULL DEFAULT 'started',
    token_hash VARCHAR(64) NULL,
    token_expires_at TIMESTAMPTZ NULL,
    request JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    report JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    error VARCHAR(255) NULL,
    parent_run_id INTEGER NULL REFERENCES law_radar_runs(id) ON DELETE SET NULL,
    requested_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    received_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_law_radar_runs_kind CHECK ({CK_RUN_KIND}),
    CONSTRAINT ck_law_radar_runs_status CHECK ({CK_RUN_STATUS})
)""",
    f"""CREATE TABLE IF NOT EXISTS law_changes (
    id SERIAL PRIMARY KEY,
    title VARCHAR({CHANGE_TITLE_MAX}) NOT NULL,
    summary JSONB NOT NULL DEFAULT '[]'::jsonb,
    roles JSONB NOT NULL DEFAULT '[]'::jsonb,
    urgency VARCHAR(8) NOT NULL,
    stage VARCHAR(12) NOT NULL,
    effective_on DATE NULL,
    deadline DATE NULL,
    legal_ref VARCHAR({LEGAL_REF_MAX}) NULL,
    probe_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(16) NOT NULL DEFAULT 'new',
    decision_note TEXT NULL,
    decided_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    decided_at TIMESTAMPTZ NULL,
    first_run_id INTEGER NULL REFERENCES law_radar_runs(id) ON DELETE SET NULL,
    last_run_id INTEGER NULL REFERENCES law_radar_runs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_law_changes_urgency CHECK ({CK_CHANGE_URGENCY}),
    CONSTRAINT ck_law_changes_stage CHECK ({CK_CHANGE_STAGE}),
    CONSTRAINT ck_law_changes_status CHECK ({CK_CHANGE_STATUS}),
    CONSTRAINT ck_law_changes_not_applicable CHECK ({CK_CHANGE_NOT_APPLICABLE}),
    CONSTRAINT ck_law_changes_arrays CHECK ({CK_CHANGE_ARRAYS})
)""",
    f"""CREATE TABLE IF NOT EXISTS law_change_tasks (
    id SERIAL PRIMARY KEY,
    change_id INTEGER NOT NULL REFERENCES law_changes(id) ON DELETE CASCADE,
    text VARCHAR({TASK_TEXT_MAX}) NOT NULL,
    role VARCHAR(12) NULL,
    source VARCHAR(4) NOT NULL DEFAULT 'bot',
    assignee_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    due_on DATE NULL,
    done_at TIMESTAMPTZ NULL,
    done_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_law_change_tasks_role CHECK ({CK_TASK_ROLE}),
    CONSTRAINT ck_law_change_tasks_source CHECK ({CK_TASK_SOURCE})
)""",
    f"""CREATE TABLE IF NOT EXISTS law_change_events (
    id SERIAL PRIMARY KEY,
    change_id INTEGER NOT NULL REFERENCES law_changes(id) ON DELETE CASCADE,
    kind VARCHAR(16) NOT NULL,
    from_value VARCHAR({EVENT_VALUE_MAX}) NULL,
    to_value VARCHAR({EVENT_VALUE_MAX}) NULL,
    note TEXT NULL,
    task_id INTEGER NULL REFERENCES law_change_tasks(id) ON DELETE SET NULL,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    run_id INTEGER NULL REFERENCES law_radar_runs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_law_change_events_kind CHECK ({CK_EVENT_KIND})
)""",
    f"""CREATE TABLE IF NOT EXISTS law_change_probes (
    id SERIAL PRIMARY KEY,
    change_id INTEGER NOT NULL REFERENCES law_changes(id) ON DELETE CASCADE,
    probe_key VARCHAR({PROBE_KEY_MAX}) NOT NULL,
    value INTEGER NULL,
    text VARCHAR({PROBE_TEXT_MAX}) NOT NULL DEFAULT '',
    link VARCHAR({LINK_MAX}) NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_law_change_probes_change_key UNIQUE (change_id, probe_key)
)""",
    f"""CREATE TABLE IF NOT EXISTS law_radar_items (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NULL REFERENCES law_radar_runs(id) ON DELETE SET NULL,
    analyze_run_id INTEGER NULL REFERENCES law_radar_runs(id) ON DELETE SET NULL,
    change_id INTEGER NULL REFERENCES law_changes(id) ON DELETE SET NULL,
    fingerprint VARCHAR({FINGERPRINT_MAX}) NOT NULL,
    source VARCHAR(12) NOT NULL,
    klass VARCHAR(8) NOT NULL,
    gate VARCHAR(10) NOT NULL DEFAULT 'pending',
    gate_reason VARCHAR({GATE_REASON_MAX}) NULL,
    title VARCHAR({ITEM_TITLE_MAX}) NOT NULL,
    url VARCHAR({URL_MAX}) NOT NULL,
    published DATE NOT NULL,
    act_ref VARCHAR({ACT_REF_MAX}) NULL,
    print_no VARCHAR({PRINT_NO_MAX}) NULL,
    stage VARCHAR({STAGE_TEXT_MAX}) NULL,
    quote VARCHAR({QUOTE_MAX}) NULL,
    official JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    analyzed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_law_radar_items_fingerprint UNIQUE (fingerprint),
    CONSTRAINT ck_law_radar_items_source CHECK ({CK_ITEM_SOURCE}),
    CONSTRAINT ck_law_radar_items_klass CHECK ({CK_ITEM_CLASS}),
    CONSTRAINT ck_law_radar_items_gate CHECK ({CK_ITEM_GATE}),
    CONSTRAINT ck_law_radar_items_lex CHECK ({CK_ITEM_LEX}),
    CONSTRAINT ck_law_radar_items_act_ref CHECK ({CK_ITEM_ACT_REF}),
    CONSTRAINT ck_law_radar_items_print_no CHECK ({CK_ITEM_PRINT_NO})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_law_radar_runs_kind_started "
    "ON law_radar_runs (kind, started_at)",
    "CREATE INDEX IF NOT EXISTS ix_law_changes_status_deadline "
    "ON law_changes (status, deadline)",
    "CREATE INDEX IF NOT EXISTS ix_law_change_tasks_change "
    "ON law_change_tasks (change_id)",
    "CREATE INDEX IF NOT EXISTS ix_law_change_events_change "
    "ON law_change_events (change_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_law_radar_items_run ON law_radar_items (run_id)",
    "CREATE INDEX IF NOT EXISTS ix_law_radar_items_change "
    "ON law_radar_items (change_id)",
    "CREATE INDEX IF NOT EXISTS ix_law_radar_items_gate "
    "ON law_radar_items (gate, analyzed_at)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()

DATA_DDL: tuple[str, ...] = ()

#: Kolejność zakładania; ``downgrade`` kasuje odwrotnie.
TABLES: tuple[str, ...] = (
    "law_radar_runs",
    "law_changes",
    "law_change_tasks",
    "law_change_events",
    "law_change_probes",
    "law_radar_items",
)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
