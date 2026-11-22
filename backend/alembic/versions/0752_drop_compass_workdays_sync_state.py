"""Usunięcie śladu Compassa: tabela `compass_workdays_sync_state` i dwa klucze `app_settings`.

Revision ID: 0752_drop_compass_workdays_sync_state
Revises: 0751_settlement_extra_sources

Compass wygaszono 22.11.2026 (serwer usunięty). #3696 zdjął pętlę
`compass_workdays_sync`, która jako jedyna pisała do tabeli (0276), i sondę
`checks.compass_workdays`, która ją czytała; zostały model, lustro
w `entrypoint.sh` i sonda schematu w `/api/health/deep`, zdjęte razem z tą
migracją. Na tabelę nie wskazuje żaden klucz obcy (żadna migracja go nie
zakłada, tabela ma jeden wiersz `id = 1` bez odnośników), więc instrukcja idzie
bez CASCADE: nieznana zależność przerwie migrację głośno.

Klucze `app_settings`: `compass_lifecycle_state` (watermark pętli
`compass_lifecycle_sync`) i `service_account_retired_key_ids` (nagrobek kluczy
bootstrapu konta serwisowego Compassa). Oba czytał tylko kod usunięty w #3696.

Lustro DROP jest w `entrypoint.sh` (alembic na produkcji bywa osierocony);
pilnuje go `tests/test_drop_compass_workdays_sync_state_mirror.py`. DELETE
kluczy nie ma lustra: bez niego zostają dwa obojętne wiersze, a siatka nie
musiałaby ich kasować przy każdym starcie.
"""

from alembic import op

revision = "0752_drop_compass_workdays_sync_state"
down_revision = "0751_settlement_extra_sources"
branch_labels = None
depends_on = None

TABLE_GROUPS = (("compass_workdays_sync_state",),)
RETIRED_SETTING_KEYS = ("compass_lifecycle_state", "service_account_retired_key_ids")


def drop_statements() -> list[str]:
    return [f"DROP TABLE IF EXISTS {', '.join(group)}" for group in TABLE_GROUPS]


def delete_settings_statement() -> str:
    keys = ", ".join(f"'{key}'" for key in RETIRED_SETTING_KEYS)
    return f"DELETE FROM app_settings WHERE key IN ({keys})"


def upgrade() -> None:
    # zgodne-wstecz: tabeli i kluczy nie czyta ani nie pisze kod od #3696 (wdrożony 22.11.2026)
    # Wyjątek: sonda schematu w `/api/health/deep` starego kontenera pokaże tabelę
    # jako padniętą w czasie nakładania; `deploy.yml` czeka wtedy na nowy SHA
    # („stale version”), więc status starej wersji nie wpływa na wynik wdrożenia.
    for statement in drop_statements():
        op.execute(statement)
    op.execute(delete_settings_statement())


def downgrade() -> None:
    # Pusta tabela jak w 0276 (bit w bit z dawnym lustrem w `entrypoint.sh`)
    # z wierszem-kotwicą. Kluczy `app_settings` nie odtwarzamy: czytał je
    # tylko usunięty kod.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compass_workdays_sync_state (
            id INTEGER PRIMARY KEY,
            last_run_started_at TIMESTAMPTZ NULL,
            last_run_finished_at TIMESTAMPTZ NULL,
            last_status VARCHAR(20) NULL,
            last_error TEXT NULL,
            stats JSONB NULL,
            updated_at TIMESTAMPTZ NULL
        )
        """
    )
    op.execute(
        "INSERT INTO compass_workdays_sync_state (id) VALUES (1) "
        "ON CONFLICT (id) DO NOTHING"
    )
