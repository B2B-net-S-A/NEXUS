"""DDL odczytów CV z okna „Dodaj kandydata” (0771) — jedno źródło dla migracji
i entrypointu.

Wiersz na plik (``sha256`` treści), najwyżej ``cv_preview_cache.MAX_ENTRIES``
wierszy, każdy żyje 30 min i znika po zapisie kandydata. ``payload`` to odczyt
i tekst CV zaszyfrowane kluczem z bajtów pliku (``cv_preview_cache``): bez samego
pliku wiersz nic nie mówi, także w kopii bazy i na stagingu. Bez indeksów poza
kluczem, bo tabela ma najwyżej kilkadziesiąt wierszy.

Lustro 1:1 w ``entrypoint.sh`` — pilnuje ``test_cv_preview_cache.py``.
"""

TABLE_DDL = (
    """CREATE TABLE IF NOT EXISTS cv_preview_reads (
        sha256 VARCHAR(64) PRIMARY KEY,
        payload BYTEA NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        used_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
)
