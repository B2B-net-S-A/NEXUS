"""Wnioski o dopłatę za technologię premium (F3, 15.11.2026) — SQL migracji ``0713_premium_skill_claims``.

Jedno źródło DDL dla migracji i lustra ``entrypoint.sh``; same dodatki.

* ``contract_premium_skill_claims`` — wniosek DL o dopłatę dla kontraktu:
  propozycja NEXUSA (dowody ze źródłami w chwili złożenia), decyzja DL
  „zna / korzysta”, prośba do klienta, wynik (przyznana z potwierdzeniem
  klienta albo odmowa z powodem i datą kolejnej próby). Zamknięte wnioski
  zostają jako historia osoby — przy następnej prolongacji DL widzi, czym
  klient odmówił. Jeden otwarty wniosek na technologię kontraktu.
* ``dl_alerts.alert_type`` dostaje ``framework_over_limit`` (osoba ponad
  limitem z umowy ramowej, prolongata blisko, umowa daje dźwignię).
"""

from __future__ import annotations

CLAIM_STATUSES = ("approved", "sent", "granted", "refused", "dropped")
OPEN_STATUSES = ("approved", "sent")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


TABLE_DDL: tuple[str, ...] = (
    f"""
    CREATE TABLE IF NOT EXISTS contract_premium_skill_claims (
        id SERIAL PRIMARY KEY,
        contract_id INTEGER NOT NULL REFERENCES contracts (id) ON DELETE CASCADE,
        technology VARCHAR(100) NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'approved',
        knows BOOLEAN NULL,
        uses BOOLEAN NULL,
        evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
        dl_user_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
        dl_note TEXT NULL,
        client_confirmed_by VARCHAR(255) NULL,
        client_confirmed_on DATE NULL,
        client_evidence TEXT NULL,
        outcome_reason TEXT NULL,
        next_try_on DATE NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_premium_skill_claims_status CHECK (status IN ({_quoted(CLAIM_STATUSES)}))
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_premium_skill_claims_contract_id "
    "ON contract_premium_skill_claims (contract_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_premium_skill_claims_open "
    "ON contract_premium_skill_claims (contract_id, lower(technology)) "
    f"WHERE status IN ({_quoted(OPEN_STATUSES)})",
)

ALL_DDL = TABLE_DDL

DOWNGRADE_DDL: tuple[str, ...] = ("DROP TABLE IF EXISTS contract_premium_skill_claims",)
