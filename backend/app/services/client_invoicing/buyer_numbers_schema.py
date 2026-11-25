"""DDL dodatkowych numerów nabywcy klienta (0779, 25.11.2026).

Jedno źródło dla migracji ``0779_client_buyer_numbers`` i lustra w
``entrypoint.sh`` (pilnuje ``tests/test_client_buyer_numbers.py``).
"""

from __future__ import annotations

SOURCES = ("manual", "auto")

DDL: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS client_buyer_numbers (
        id SERIAL PRIMARY KEY,
        client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
        number VARCHAR(32) NOT NULL,
        source VARCHAR(16) NOT NULL DEFAULT 'manual',
        added_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_client_buyer_numbers_number UNIQUE (number),
        CONSTRAINT ck_client_buyer_numbers_source CHECK (source IN ('manual', 'auto'))
    )""",
    "CREATE INDEX IF NOT EXISTS ix_client_buyer_numbers_client_id "
    "ON client_buyer_numbers (client_id)",
)
