"""„Ludzie w NEXUSIE” — propozycje struktury u klienta: SQL migracji ``0475_client_structure_proposals`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0475_client_structure_proposals.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Kontrakt
modułu jak w pozostałych ``*_schema.py``; każda instrukcja idempotentna.

Decyzja Artura 18.10.2026: „Propozycja automatu + akcept DL”. Automat
(``services/care/structure_proposals.py``) liczy przy odczycie, kto jest
menedżerem konsultanta u klienta i pod kogo podlega osoba klienta — nic nie
zapisuje się samo. Delivery Lead zatwierdza (zapis ``contracts.client_pm_contact_id``
albo ``contacts.reports_to_contact_id``), zmienia albo pomija. Tabela niżej
pamięta tylko „Pomiń”:

* ``client_structure_skips`` — pominięta propozycja: menedżer konsultanta
  (``kind = 'manager'``, ``contract_id``) albo przełożony osoby klienta
  (``kind = 'reports_to'``, ``contact_id``), z kontaktem, który był
  propozycją (``proposed_contact_id``; NULL = „pomiń” bez propozycji). Jeden
  wiersz na pozycję — nowe „Pomiń” go zastępuje. Gdy automat zaproponuje
  INNĄ osobę, pozycja wraca na listę; „Przywróć” kasuje wiersz.

Dzwonek ``care_client_structure`` (sekcja Delivery) do Delivery Leadów
klienta: „uzupełnij strukturę klienta X”, z dziennego przebiegu opieki,
najwyżej raz na 7 dni na klienta. Do klientów nic nie wychodzi.
"""

from __future__ import annotations

SKIP_KINDS: tuple[str, ...] = ("manager", "reports_to")

#: Dzwonek do Delivery Leadów klienta. Do ``DELIVERY_TYPES`` modułu
#: powiadomień dopina go ``hr_notification_schema``.
NOTIFICATION_TYPES: tuple[str, ...] = ("care_client_structure",)
ENUM_DDL: tuple[str, ...] = tuple(
    f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'"
    for value in NOTIFICATION_TYPES
)

CK_SKIP_KIND = "kind IN ('manager', 'reports_to')"
#: Pozycja ma dokładnie jeden przedmiot zgodny z rodzajem.
CK_SKIP_SUBJECT = (
    "(kind = 'manager' AND contract_id IS NOT NULL AND contact_id IS NULL) "
    "OR (kind = 'reports_to' AND contact_id IS NOT NULL AND contract_id IS NULL)"
)

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS client_structure_skips (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    kind VARCHAR(16) NOT NULL,
    contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE CASCADE,
    contact_id INTEGER NULL REFERENCES contacts(id) ON DELETE CASCADE,
    proposed_contact_id INTEGER NULL REFERENCES contacts(id) ON DELETE CASCADE,
    skipped_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    skipped_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_client_structure_skips_kind CHECK ({CK_SKIP_KIND}),
    CONSTRAINT ck_client_structure_skips_subject CHECK ({CK_SKIP_SUBJECT})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_client_structure_skips_client "
    "ON client_structure_skips (client_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_client_structure_skips_contract "
    "ON client_structure_skips (contract_id) WHERE kind = 'manager'",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_client_structure_skips_contact "
    "ON client_structure_skips (contact_id) WHERE kind = 'reports_to'",
)

CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()
TABLES: tuple[str, ...] = ("client_structure_skips",)
DOWNGRADE_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
