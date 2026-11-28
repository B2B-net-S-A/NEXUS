"""DDL ekranu Ustawienia → Bezpieczeństwo (0800) — JEDNO źródło dla migracji
i siatki w ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

Decyzja Artura z 27.11.2026 (research „Tarcza NEXUSA”): jeden ekran admina
zbiera znaleziska ze skanerów (CI, DefectDojo, Wazuh), zdarzenia z serwera
(CrowdSec, Falco, Wazuh, logowania) i terminy rutyn bezpieczeństwa.

* ``security_findings`` — rzecz do załatwienia. ``fingerprint`` to stały klucz
  źródła (ponowny import aktualizuje treść, status ustawiony w NEXUSIE zostaje).
  Wyjątek ma zawsze powód i termin (``exception_until``); po terminie znalezisko
  wraca na listę (odczyt liczy to sam, pętla przestawia status i zostawia ślad).
* ``security_events`` — strumień zdarzeń bez danych osobowych (opis jest
  czyszczony z adresów IP i e-maili przy zapisie). ``ref`` daje idempotentne
  ponowienia webhooków (unikalny per źródło).
* ``security_routines`` — rytm testów i przeglądów z terminem; po terminie
  dzwonek i mail do adminów.
* ``security_source_states`` — kiedy źródło ostatnio się odezwało (każda
  paczka webhooka) i wynik odczytu GitHub Actions.

Same dodania — stary kod działa na nowym schemacie.
"""

from __future__ import annotations

SOURCES: tuple[str, ...] = (
    "ci",
    "defectdojo",
    "wazuh",
    "crowdsec",
    "falco",
    "pentest",
    "nexus",
    "manual",
    # 0802 (28.11.2026): alerty Grafany Cloud przez webhook kontaktu.
    "grafana",
    # 0808 (28.11.2026): incydenty Microsoft Defendera — NEXUS czyta je sam z Graph.
    "defender",
)
# Lista z 0802 — downgrade 0808 wraca do niej.
SOURCES_0802: tuple[str, ...] = tuple(s for s in SOURCES if s != "defender")
# Lista z 0800 — downgrade 0802 wraca do niej.
SOURCES_0800: tuple[str, ...] = tuple(s for s in SOURCES_0802 if s != "grafana")
SEVERITIES: tuple[str, ...] = ("info", "low", "medium", "high", "critical")
FINDING_STATUSES: tuple[str, ...] = ("open", "excepted", "fixed")
CADENCES: tuple[str, ...] = ("week", "month", "quarter")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


ENUM_STATEMENTS: tuple[str, ...] = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'security_routine_overdue'",
)

TABLE_DDL: list[str] = [
    f"""CREATE TABLE IF NOT EXISTS security_findings (
           id SERIAL PRIMARY KEY,
           source VARCHAR(20) NOT NULL
               CONSTRAINT ck_security_findings_source CHECK (source IN ({_in(SOURCES)})),
           scanner VARCHAR(40) NULL,
           fingerprint VARCHAR(200) NOT NULL,
           severity VARCHAR(10) NOT NULL
               CONSTRAINT ck_security_findings_severity CHECK (severity IN ({_in(SEVERITIES)})),
           title VARCHAR(200) NOT NULL,
           location VARCHAR(300) NULL,
           evidence TEXT NULL,
           impact TEXT NULL,
           steps JSONB NOT NULL DEFAULT '[]'::jsonb,
           status VARCHAR(10) NOT NULL DEFAULT 'open'
               CONSTRAINT ck_security_findings_status CHECK (status IN ({_in(FINDING_STATUSES)})),
           owner_user_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           exception_reason TEXT NULL,
           exception_until DATE NULL,
           exception_by_user_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           closed_note TEXT NULL,
           closed_at TIMESTAMPTZ NULL,
           closed_by_user_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           last_run_id VARCHAR(80) NULL,
           updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           CONSTRAINT ck_security_findings_exception
               CHECK (status <> 'excepted' OR (exception_reason IS NOT NULL AND exception_until IS NOT NULL))
       )""",
    # Kolumna dołożona przed wdrożeniem 0800 (pełny skan w paczkach) — bazy,
    # które już wykonały wcześniejszą wersję DDL (staging), dostają ją tutaj.
    "ALTER TABLE security_findings ADD COLUMN IF NOT EXISTS last_run_id VARCHAR(80) NULL",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_security_findings_fingerprint
           ON security_findings (source, fingerprint)""",
    """CREATE INDEX IF NOT EXISTS ix_security_findings_status
           ON security_findings (status, severity)""",
    f"""CREATE TABLE IF NOT EXISTS security_events (
           id BIGSERIAL PRIMARY KEY,
           source VARCHAR(20) NOT NULL
               CONSTRAINT ck_security_events_source CHECK (source IN ({_in(SOURCES)})),
           kind VARCHAR(40) NOT NULL,
           severity VARCHAR(10) NOT NULL DEFAULT 'info'
               CONSTRAINT ck_security_events_severity CHECK (severity IN ({_in(SEVERITIES)})),
           summary VARCHAR(300) NOT NULL,
           count INTEGER NOT NULL DEFAULT 1,
           ref VARCHAR(120) NULL,
           link VARCHAR(500) NULL,
           occurred_at TIMESTAMPTZ NOT NULL,
           received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           service_account_id INTEGER NULL
       )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_security_events_ref
           ON security_events (source, ref) WHERE ref IS NOT NULL""",
    """CREATE INDEX IF NOT EXISTS ix_security_events_occurred
           ON security_events (occurred_at DESC)""",
    """CREATE INDEX IF NOT EXISTS ix_security_events_source_kind
           ON security_events (source, kind, occurred_at DESC)""",
    f"""CREATE TABLE IF NOT EXISTS security_routines (
           id SERIAL PRIMARY KEY,
           key VARCHAR(40) NOT NULL,
           title VARCHAR(200) NOT NULL,
           cadence VARCHAR(10) NOT NULL
               CONSTRAINT ck_security_routines_cadence CHECK (cadence IN ({_in(CADENCES)})),
           owner_label VARCHAR(80) NOT NULL,
           auto_source VARCHAR(20) NULL,
           position INTEGER NOT NULL DEFAULT 0,
           last_done_on DATE NULL,
           next_due_on DATE NOT NULL,
           last_note TEXT NULL,
           updated_by_user_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
       )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_security_routines_key
           ON security_routines (key)""",
    """CREATE TABLE IF NOT EXISTS security_source_states (
           source VARCHAR(20) PRIMARY KEY,
           last_run_at TIMESTAMPTZ NULL,
           last_ok_at TIMESTAMPTZ NULL,
           last_error VARCHAR(300) NULL,
           owner_service_account_id INTEGER NULL,
           detail JSONB NOT NULL DEFAULT '{}'::jsonb
       )""",
    "ALTER TABLE security_source_states ADD COLUMN IF NOT EXISTS owner_service_account_id INTEGER NULL",
]


def source_check_ddl(sources: tuple[str, ...]) -> list[str]:
    """CHECK źródła w obu tabelach na nowo — ``CREATE TABLE IF NOT EXISTS`` nie
    poszerzy go w bazie, w której tabela już stoi. Tabele są małe, więc
    przebudowa przy każdym starcie (lustro w entrypoint) kosztuje ułamek sekundy."""
    return [
        f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_source, "
        f"ADD CONSTRAINT ck_{table}_source CHECK (source IN ({_in(sources)}))"
        for table in ("security_findings", "security_events")
    ]


TABLE_DDL += source_check_ddl(SOURCES)

# Rytm z raportu „Tarcza NEXUSA” (27.11.2026). Zasiew raz: ON CONFLICT
# zostawia wiersz, który admin już odhaczył. Terminy pierwszego przebiegu
# z makiety; potem następny termin = wykonanie + rytm.
ROUTINE_SEED: tuple[
    tuple[str, str, str, str, str | None, int, str | None, str], ...
] = (
    (
        "ci_weekly",
        "Semgrep + audyt zależności (security-weekly)",
        "week",
        "CI",
        "ci",
        10,
        "2026-11-23",
        "2026-11-30",
    ),
    (
        "pentest_staging",
        "Pentest stagingu (6 scenariuszy OWASP)",
        "month",
        "sesja Claude",
        None,
        20,
        "2026-11-13",
        "2026-12-13",
    ),
    (
        "dast_staging",
        "ZAP + Schemathesis + Nuclei na stagingu",
        "month",
        "sesja Claude",
        None,
        30,
        None,
        "2026-12-09",
    ),
    (
        "external_scan",
        "Skan z zewnątrz (porty, TLS)",
        "quarter",
        "sesja Claude, za zgodą",
        None,
        40,
        "2026-11-24",
        "2026-12-17",
    ),
    (
        "accounts_review",
        "Przegląd kont, ról i tokenów API",
        "quarter",
        "admin",
        None,
        50,
        "2026-11-24",
        "2026-12-15",
    ),
)


def _lit(value: str | None) -> str:
    return "NULL" if value is None else "'" + value.replace("'", "''") + "'"


SEED_DDL: list[str] = [
    "INSERT INTO security_routines "
    "(key, title, cadence, owner_label, auto_source, position, last_done_on, next_due_on) VALUES "
    + ", ".join(
        f"({_lit(k)}, {_lit(t)}, {_lit(c)}, {_lit(o)}, {_lit(a)}, {p}, "
        f"{_lit(last)}::date, {_lit(nxt)}::date)"
        for k, t, c, o, a, p, last, nxt in ROUTINE_SEED
    )
    + " ON CONFLICT (key) DO NOTHING"
]

DOWNGRADE_DDL: list[str] = [
    "DROP TABLE IF EXISTS security_source_states",
    "DROP TABLE IF EXISTS security_routines",
    "DROP TABLE IF EXISTS security_events",
    "DROP TABLE IF EXISTS security_findings",
]
