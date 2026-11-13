"""Dodatki do rozliczenia kontraktora: SQL migracji ``0690_settlement_extra_sources``
i lustra entrypointu (przez ``app/services/hr_schema_bundle.py``).

Potrzeba Finansów z 13.11.2026: kontraktor dolicza do faktury kwoty spoza
godzin (premia za polecenie, weryfikacja techniczna, szkolenie, delegacja).
Dodatek to wiersz na (kontrakt, miesiąc) z rodzajem, kwotą netto, źródłem
i stanem. Ta sama tabela trzyma koszty integracji BNP (rodzaj ``integration``,
reguła ``cl.integration_costs``, zgoda DL-a) — jeden model kosztów dodatkowych.

* ``client_settlement_extras`` (0689 + kolumny 0690) — ``status``: ``pending`` (zgłoszony),
  ``approved`` (zatwierdzony: liczy się do kwoty faktury kontraktora),
  ``rejected`` (odrzucony z powodem). ``source``: ``back_office`` (karta sprawy),
  ``finance`` (Finanse na karcie osoby), ``portal`` (konsultant w panelu).
  ``bill_to_client``: dodatek idzie też do faktury dla klienta (reguła
  ``cl.extra_costs_on_invoice``); przy Aliorze koszty bywają tylko naszą zgodą.
* ``client_settlement_extra_documents`` — pliki dodatku (faktura, paragon,
  bilety) w magazynie ``documents_store`` (``hr_documents/settlement_extras/``).

Tabelę ``client_settlement_extras`` z rodzajem, kwotą, opisem i stanem zakłada
0689 (``client_settlements_schema``, koszty integracji). Tu kolumny pozostałych
rodzajów (``ADD COLUMN IF NOT EXISTS``) i tabela dokumentów.
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted

SOURCES: tuple[str, ...] = ("back_office", "finance", "portal")
DOC_CHANNELS: tuple[str, ...] = ("portal", "staff")

DECISION_NOTE_MAX = 500
FILE_NAME_MAX = 255

CK_SOURCE = f"source IN ({quoted(SOURCES)})"
CK_DOC_CHANNEL = f"channel IN ({quoted(DOC_CHANNELS)})"


def _constraint(table: str, name: str, check: str) -> str:
    return f"""DO $$ BEGIN
    ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({check});
EXCEPTION WHEN duplicate_object THEN NULL;
END $$"""


#: Kolumny dokładane do ``client_settlement_extras`` z 0689 (downgrade je zdejmuje).
ADDED_COLUMNS: tuple[str, ...] = (
    "source",
    "bo_card_id",
    "bill_to_client",
    "decision_note",
)

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS client_settlement_extra_documents (
    id SERIAL PRIMARY KEY,
    extra_id INTEGER NOT NULL REFERENCES client_settlement_extras(id) ON DELETE CASCADE,
    file_path VARCHAR(300) NOT NULL,
    file_name VARCHAR({FILE_NAME_MAX}) NULL,
    mime VARCHAR(120) NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    size_bytes INTEGER NOT NULL,
    channel VARCHAR(8) NOT NULL,
    uploaded_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_client_settlement_extra_documents_file UNIQUE (extra_id, sha256),
    CONSTRAINT ck_client_settlement_extra_documents_channel CHECK ({CK_DOC_CHANNEL})
)""",
)

#: Tabela ``client_settlement_extras`` powstaje wcześniej, w ``client_settlements_schema``
#: (moduł przed tym w ``hr_schema_bundle.MODULES``), więc FK dokumentów i ALTER-y mają cel.
COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE client_settlement_extras ADD COLUMN IF NOT EXISTS "
    "source VARCHAR(12) NOT NULL DEFAULT 'finance'",
    "ALTER TABLE client_settlement_extras ADD COLUMN IF NOT EXISTS "
    "bo_card_id INTEGER NULL REFERENCES bo_cards(id) ON DELETE SET NULL",
    "ALTER TABLE client_settlement_extras ADD COLUMN IF NOT EXISTS "
    "bill_to_client BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE client_settlement_extras ADD COLUMN IF NOT EXISTS "
    f"decision_note VARCHAR({DECISION_NOTE_MAX}) NULL",
    _constraint(
        "client_settlement_extras", "ck_client_settlement_extras_source", CK_SOURCE
    ),
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_client_settlement_extras_card "
    "ON client_settlement_extras (bo_card_id) WHERE bo_card_id IS NOT NULL",
)

CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()

TABLES: tuple[str, ...] = ("client_settlement_extra_documents",)

ALL_DDL: tuple[str, ...] = (*TABLE_DDL, *COLUMN_DDL, *INDEX_DDL)
