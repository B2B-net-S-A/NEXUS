"""Stan pętli zaciągania dni roboczych z COMPASSA (sonda zdrowia D5).

Revision ID: 0276_compass_workdays_sync_state
Revises: 0275_ai_quota_keys_and_tokens

``compass_workdays_sync`` był do 09.2026 jedynym integratorem bez wpisu
w ``/api/health.checks`` — i, co gorsza, jedynym, którego awarii nie dało się
wykryć ŻADNYM kanałem. Pętla ``return``uje czysto przy wyłączonej fladze
i przy braku sekretu (``classify_background_tasks`` → ``exited_cleanly``, stan
cichy), a jej ciało łyka każdy wyjątek, więc nigdy nie osiąga ``crashed``.
Wynik ``sync_workdays``, w tym ``fetch_failed:`` i ``basis_mismatch:``, szedł
wyłącznie do logu INFO.

Cicha awaria oznacza regres defektu, który D5 usuwał: ``workdays_source`` wraca
na ``"unavailable"``, mianownikiem znów jest stała 5, a osoba na urlopie ląduje
na imiennej liście „poniżej progu".

Tabela jest kalką ``order_mail_sync_state`` (jeden wiersz, ``id = 1``) — ta
pętla ma jedną fazę, więc wariant ``traffit_sync_state`` (wiersz per faza)
byłby nadmiarowy. Wiersz zakładamy tutaj, żeby sonda odróżniała „nigdy nie
było biegu" (wiersz jest, kolumny NULL) od „migracja nie doszła" (brak wiersza).

Zdublowane w safety-net ``entrypoint.sh`` — prod alembic bywa orphaned.
"""

from alembic import op

revision = "0276_compass_workdays_sync_state"
down_revision = "0275_ai_quota_keys_and_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Surowy SQL, bit w bit ten sam co lustro w ``entrypoint.sh`` — kalka 0264.
    # ``op.create_table`` dałoby ``id`` typu SERIAL (``nextval``), a entrypoint
    # tworzy zwykły ``INTEGER PRIMARY KEY``: tabela miałaby DWA różne kształty
    # zależnie od tego, która ścieżka zdążyła pierwsza. ``IF NOT EXISTS``
    # dokłada idempotencję — na prodzie z osieroconym alembikiem safety-net
    # zakłada tabelę wcześniej, a wtedy zwykły ``CREATE TABLE`` by tu padł.
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
    # Pusty wiersz-kotwica. Bez niego sonda nie odróżnia „pętla nigdy nie
    # wystartowała" (wiersz jest, kolumny NULL) od „migracja nie doszła"
    # (brak wiersza) — a to dwie różne naprawy.
    op.execute(
        "INSERT INTO compass_workdays_sync_state (id) VALUES (1) "
        "ON CONFLICT (id) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS compass_workdays_sync_state")
