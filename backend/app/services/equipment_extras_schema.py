"""„Ludzie w NEXUSIE” — Sprzęt, etapy 4–5: SQL migracji ``0461_equipment_extras`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0461_equipment_extras.py`` i ``entrypoint.sh``
(przez ``app/services/hr_schema_bundle.py``). Kontrakt modułu jak w ``equipment_schema``.

Zakres (propozycja recepcji z 15.10, etapy 4 i 5, D9):

* ``equipment_intune_devices`` — migawka urządzeń z Intune (tylko odczyt Graph,
  ``DeviceManagementManagedDevices.Read.All`` za zgodą administratora). Rozjazdy
  z ewidencją liczone przy odczycie; ``resolution`` = recepcja wyjaśniła albo
  pominęła urządzenie. Bez kluczy odzyskiwania i bez danych spoza urządzenia,
  UPN to firmowy login użytkownika urządzenia,
* ``equipment_intune_sync_state`` — jeden wiersz: ostatni przebieg pętli (sonda health),
* ``academy_session_checklist`` — lista edycji Akademii (sekcje i punkty check listy
  recepcji) per edycja (``academy_sessions``),
* ``academy_participant_logistics`` — hotel i bilet uczestnika edycji
  (zestaw i protokół wynikają z wydań sprzętu),
* czwarty posiadacz sprzętu: uczestnik Akademii (``academy_application_id``) w wydaniach,
  protokołach i zadaniach recepcji.
"""

from __future__ import annotations

from app.services.equipment_schema import quoted

INTUNE_RESOLUTIONS: tuple[str, ...] = ("wyjasnione", "pominiete")
LOGISTICS_STATUSES: tuple[str, ...] = (
    "nie_dotyczy",
    "do_zrobienia",
    "zrobione",
    "do_anulowania",
    "anulowane",
)

CK_INTUNE_RESOLUTION = (
    f"resolution IS NULL OR resolution IN ({quoted(INTUNE_RESOLUTIONS)})"
)
CK_INTUNE_RESOLVED = "(resolution IS NULL) = (resolved_at IS NULL)"
CK_INTUNE_STATE_SINGLETON = "id = 1"
CK_CHECKLIST_LABEL = "btrim(label) <> ''"
CK_LOGISTICS_HOTEL = f"hotel IN ({quoted(LOGISTICS_STATUSES)})"
CK_LOGISTICS_TICKET = f"ticket IN ({quoted(LOGISTICS_STATUSES)})"

#: Wydanie, protokół i zadanie recepcji mają dokładnie jednego posiadacza
#: z czterech: konto, kontrakt, osoba zewnętrzna, uczestnik Akademii.
CK_ASSIGNMENT_ONE_HOLDER = (
    "num_nonnulls(user_id, contract_id, external_person_id, academy_application_id) = 1"
)

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS equipment_intune_devices (
    id SERIAL PRIMARY KEY,
    intune_device_id VARCHAR(64) NOT NULL,
    device_name VARCHAR(255) NULL,
    serial_number VARCHAR(128) NULL,
    manufacturer VARCHAR(120) NULL,
    model VARCHAR(160) NULL,
    operating_system VARCHAR(60) NULL,
    user_principal_name VARCHAR(255) NULL,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    item_id INTEGER NULL REFERENCES equipment_items(id) ON DELETE SET NULL,
    compliance_state VARCHAR(32) NULL,
    intune_last_sync_at TIMESTAMPTZ NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    missing_since TIMESTAMPTZ NULL,
    resolution VARCHAR(16) NULL,
    resolution_note TEXT NULL,
    resolved_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    resolved_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_equipment_intune_devices_device UNIQUE (intune_device_id),
    CONSTRAINT ck_equipment_intune_devices_resolution CHECK ({CK_INTUNE_RESOLUTION}),
    CONSTRAINT ck_equipment_intune_devices_resolved CHECK ({CK_INTUNE_RESOLVED})
)""",
    f"""CREATE TABLE IF NOT EXISTS equipment_intune_sync_state (
    id SMALLINT PRIMARY KEY DEFAULT 1,
    last_run_at TIMESTAMPTZ NULL,
    last_success_at TIMESTAMPTZ NULL,
    last_error TEXT NULL,
    device_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_equipment_intune_sync_state_singleton CHECK ({CK_INTUNE_STATE_SINGLETON})
)""",
    f"""CREATE TABLE IF NOT EXISTS academy_session_checklist (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES academy_sessions(id) ON DELETE CASCADE,
    section_key VARCHAR(40) NOT NULL,
    item_key VARCHAR(60) NOT NULL,
    position SMALLINT NOT NULL,
    label VARCHAR(300) NOT NULL,
    done_at TIMESTAMPTZ NULL,
    done_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    note TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_academy_session_checklist_item UNIQUE (session_id, item_key),
    CONSTRAINT ck_academy_session_checklist_label CHECK ({CK_CHECKLIST_LABEL})
)""",
    f"""CREATE TABLE IF NOT EXISTS academy_participant_logistics (
    application_id BIGINT PRIMARY KEY
        REFERENCES academy_applications(id) ON DELETE CASCADE,
    hotel VARCHAR(16) NOT NULL DEFAULT 'do_zrobienia',
    ticket VARCHAR(16) NOT NULL DEFAULT 'do_zrobienia',
    note TEXT NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_academy_participant_logistics_hotel CHECK ({CK_LOGISTICS_HOTEL}),
    CONSTRAINT ck_academy_participant_logistics_ticket CHECK ({CK_LOGISTICS_TICKET})
)""",
)

COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE equipment_assignments ADD COLUMN IF NOT EXISTS "
    "academy_application_id BIGINT NULL "
    "REFERENCES academy_applications(id) ON DELETE RESTRICT",
    "ALTER TABLE equipment_protocols ADD COLUMN IF NOT EXISTS "
    "academy_application_id BIGINT NULL "
    "REFERENCES academy_applications(id) ON DELETE SET NULL",
    "ALTER TABLE equipment_tasks ADD COLUMN IF NOT EXISTS "
    "academy_application_id BIGINT NULL "
    "REFERENCES academy_applications(id) ON DELETE CASCADE",
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_equipment_intune_devices_serial "
    "ON equipment_intune_devices (serial_number)",
    "CREATE INDEX IF NOT EXISTS ix_equipment_intune_devices_item "
    "ON equipment_intune_devices (item_id)",
    "CREATE INDEX IF NOT EXISTS ix_equipment_intune_devices_user "
    "ON equipment_intune_devices (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_academy_session_checklist_session "
    "ON academy_session_checklist (session_id, position)",
    "CREATE INDEX IF NOT EXISTS ix_equipment_assignments_academy "
    "ON equipment_assignments (academy_application_id)",
    "CREATE INDEX IF NOT EXISTS ix_equipment_tasks_academy "
    "ON equipment_tasks (academy_application_id)",
)

#: Czterech posiadaczy zamiast trzech. Blok podmienia CHECK tylko wtedy, gdy stoi
#: jeszcze stara wersja (entrypoint wykonuje go przy każdym starcie).
CONSTRAINT_DDL: tuple[str, ...] = (
    f"""DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'ck_equipment_assignments_one_holder'
              AND pg_get_constraintdef(oid) LIKE '%academy_application_id%'
        ) THEN
            ALTER TABLE equipment_assignments
                DROP CONSTRAINT IF EXISTS ck_equipment_assignments_one_holder;
            ALTER TABLE equipment_assignments
                ADD CONSTRAINT ck_equipment_assignments_one_holder
                CHECK ({CK_ASSIGNMENT_ONE_HOLDER});
        END IF;
    END $$""",
)

DATA_DDL: tuple[str, ...] = (
    "INSERT INTO equipment_intune_sync_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING",
)

TABLES: tuple[str, ...] = (
    "equipment_intune_devices",
    "equipment_intune_sync_state",
    "academy_session_checklist",
    "academy_participant_logistics",
)

DOWNGRADE_DDL: tuple[str, ...] = (
    "ALTER TABLE equipment_assignments DROP CONSTRAINT IF EXISTS "
    "ck_equipment_assignments_one_holder",
    "ALTER TABLE equipment_assignments ADD CONSTRAINT ck_equipment_assignments_one_holder "
    "CHECK (num_nonnulls(user_id, contract_id, external_person_id) = 1) NOT VALID",
    "ALTER TABLE equipment_tasks DROP COLUMN IF EXISTS academy_application_id",
    "ALTER TABLE equipment_protocols DROP COLUMN IF EXISTS academy_application_id",
    "ALTER TABLE equipment_assignments DROP COLUMN IF EXISTS academy_application_id",
)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
