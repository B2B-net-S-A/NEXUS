"""Rozliczenia Nordei N1 (``docs/rozliczenia-nordea-plan.md``): SQL migracji
``0689_client_time_reports`` i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0689_client_time_reports.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``).

Tabele:

* ``client_external_ids`` — kartoteka: kontrakt ↔ identyfikator u klienta.
  ``kind``: ``client_person_no`` (numer osoby, w T4T ``UserId``, na fakturze
  do Nordei ``ID:…``) albo ``project_no`` (NIDS, w T4T ``Investment ID``).
  ``source``: ``ksef_item`` (opis pozycji faktury do klienta z KSeF przypiętej
  do linii zamówienia osoby), ``report_name`` (imię i nazwisko z raportu),
  ``manual``. ``state``: ``confirmed`` wiąże raport z kontraktem,
  ``suggested`` czeka na Finanse, ``rejected`` nie wraca jako podpowiedź.
* ``client_time_reports`` — wersja raportu godzin od klienta (T4T) za miesiąc.
  Ten sam plik drugi raz (``sha256``; przy pliku z kilkoma arkuszami raportu
  liczony z plikiem i nazwą arkusza) nie tworzy nowej wersji.
* ``client_time_report_rows`` — wiersze surowe wersji (osoba, NIDS, okres,
  dzień, godziny, status), żeby karta osoby pokazała historię i różnice.

Statusy osoby w miesiącu liczymy przy odczycie (czysta funkcja
``client_settlements/time_report_engine.py``) z wierszy wersji i faktur
kontraktorów, więc nowa faktura z KSeF zmienia status bez przeliczania tabel.
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted

ID_KINDS: tuple[str, ...] = ("client_person_no", "project_no")
ID_SOURCES: tuple[str, ...] = ("ksef_item", "report_name", "manual")
ID_STATES: tuple[str, ...] = ("confirmed", "suggested", "rejected")
ID_VALUE_MAX = 32
FILE_NAME_MAX = 255
SHEET_NAME_MAX = 64
PERSON_NAME_MAX = 255
PROJECT_NAME_MAX = 255

PERIOD_CHECK = "period_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'"
CK_ID_KIND = f"kind IN ({quoted(ID_KINDS)})"
CK_ID_SOURCE = f"source IN ({quoted(ID_SOURCES)})"
CK_ID_STATE = f"state IN ({quoted(ID_STATES)})"
CK_SHA = "sha256 ~ '^[0-9a-f]{64}$'"
CK_VERSION = "version_no >= 1"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS client_external_ids (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    kind VARCHAR(20) NOT NULL,
    value VARCHAR({ID_VALUE_MAX}) NOT NULL,
    valid_from DATE NULL,
    valid_to DATE NULL,
    source VARCHAR(12) NOT NULL,
    state VARCHAR(10) NOT NULL,
    confirmed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    confirmed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_client_external_ids_value UNIQUE (client_id, contract_id, kind, value),
    CONSTRAINT ck_client_external_ids_kind CHECK ({CK_ID_KIND}),
    CONSTRAINT ck_client_external_ids_source CHECK ({CK_ID_SOURCE}),
    CONSTRAINT ck_client_external_ids_state CHECK ({CK_ID_STATE})
)""",
    f"""CREATE TABLE IF NOT EXISTS client_time_reports (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    period_month VARCHAR(7) NOT NULL,
    version_no INTEGER NOT NULL,
    received_on DATE NOT NULL,
    file_name VARCHAR({FILE_NAME_MAX}) NULL,
    sheet_name VARCHAR({SHEET_NAME_MAX}) NULL,
    sha256 VARCHAR(64) NOT NULL,
    rows_count INTEGER NOT NULL DEFAULT 0,
    people_count INTEGER NOT NULL DEFAULT 0,
    hours_approved NUMERIC(12, 2) NOT NULL DEFAULT 0,
    hours_submitted NUMERIC(12, 2) NOT NULL DEFAULT 0,
    uploaded_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_client_time_reports_sha UNIQUE (client_id, sha256),
    CONSTRAINT uq_client_time_reports_version UNIQUE (client_id, period_month, version_no),
    CONSTRAINT ck_client_time_reports_period CHECK ({PERIOD_CHECK}),
    CONSTRAINT ck_client_time_reports_sha CHECK ({CK_SHA}),
    CONSTRAINT ck_client_time_reports_version CHECK ({CK_VERSION})
)""",
    f"""CREATE TABLE IF NOT EXISTS client_time_report_rows (
    id SERIAL PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES client_time_reports(id) ON DELETE CASCADE,
    person_no VARCHAR({ID_VALUE_MAX}) NOT NULL,
    person_name VARCHAR({PERSON_NAME_MAX}) NULL,
    project_no VARCHAR({ID_VALUE_MAX}) NULL,
    project_name VARCHAR({PROJECT_NAME_MAX}) NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    work_date DATE NULL,
    hours NUMERIC(8, 2) NOT NULL,
    status SMALLINT NOT NULL,
    charge_code VARCHAR(64) NULL,
    company VARCHAR(128) NULL
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_client_external_ids_lookup "
    "ON client_external_ids (client_id, kind, value)",
    "CREATE INDEX IF NOT EXISTS ix_client_external_ids_contract "
    "ON client_external_ids (contract_id)",
    "CREATE INDEX IF NOT EXISTS ix_client_time_reports_month "
    "ON client_time_reports (client_id, period_month)",
    "CREATE INDEX IF NOT EXISTS ix_client_time_report_rows_report_person "
    "ON client_time_report_rows (report_id, person_no)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()

DATA_DDL: tuple[str, ...] = ()

TABLES: tuple[str, ...] = (
    "client_external_ids",
    "client_time_reports",
    "client_time_report_rows",
)

ALL_DDL: tuple[str, ...] = (*TABLE_DDL, *COLUMN_DDL, *INDEX_DDL, *CONSTRAINT_DDL)
