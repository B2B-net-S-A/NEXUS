"""DDL połączeń wtyczki LinkedIn — JEDNO źródło dla migracji 0607 i siatki
w ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

``linkedin_extension_connections``: jeden wiersz na wtyczkę połączoną z kontem
(decyzja Artura 28.10.2026, makiety https://claude.ai/artifact/1PEmR5Gm5UQTdtRwVCRRg4).
Klucz ``nxe_v1_<id>_<sekret>`` widać raz, przy połączeniu; w bazie leży SHA-256
sekretu, jak przy kluczach kont serwisowych. ``authorization_version`` to wersja
uprawnień konta z chwili połączenia — zmiana roli albo hasła odłącza wtyczkę.
Liczniki dnia (``usage_day``, ``reads_today``, ``adds_today``) to limit odczytów
stron LinkedIna na osobę i kolumny ekranu „Ustawienia → Wtyczka LinkedIn”.
"""

from __future__ import annotations

TABLE_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS linkedin_extension_connections (
           key_id VARCHAR(64) PRIMARY KEY,
           user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
           secret_sha256 VARCHAR(64) NOT NULL,
           authorization_version INTEGER NOT NULL,
           extension_version VARCHAR(32) NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           expires_at TIMESTAMPTZ NOT NULL,
           revoked_at TIMESTAMPTZ NULL,
           revoked_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
           last_used_at TIMESTAMPTZ NULL,
           usage_day DATE NULL,
           reads_today INTEGER NOT NULL DEFAULT 0,
           adds_today INTEGER NOT NULL DEFAULT 0
       )""",
    """CREATE INDEX IF NOT EXISTS ix_linkedin_extension_connections_user
           ON linkedin_extension_connections (user_id)""",
]
