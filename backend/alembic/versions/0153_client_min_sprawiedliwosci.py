"""Wyróżniony klient „Ministerstwo Sprawiedliwości" w generatorze umów B2B.

Revision ID: 0153_client_min_sprawiedliwosci
Revises: 0152_cv_generated_async_status
Create Date: 2026-07-03

Dropdown „Pełna nazwa Klienta" w generatorze umów B2B pobiera listę z
``/api/clients-lookup?featured=true`` — a `featured` zawęża do klientów z
ustawionym ``display_name`` (kuratorska lista ~17 nazw). „Ministerstwo
Sprawiedliwości" brakowało na liście → dodajemy je.

Kuratorskie ``display_name`` były dotąd ustawiane ręcznie w produkcyjnej bazie
(brak seeda w kodzie, brak endpointu zapisu — patrz migracja 0127, która dodała
tylko kolumny). Ta migracja utrwala JEDNĄ pozycję w sposób wersjonowany i w
pełni idempotentny:

  1. Jeśli istnieje klient o nazwie „Ministerstwo Sprawiedliwości" (np. z
     Traffita), jeszcze nie wyróżniony — promujemy DOKŁADNIE JEDEN (najniższe
     ``id``) ustawiając ``display_name``. NIE ruszamy ``name`` → nadpisanie jest
     odporne na sync Traffita (importer robi ``ON CONFLICT ... DO UPDATE SET
     name = EXCLUDED.name``, ale ``display_name`` zostawia w spokoju — 0127).
  2. Jeśli nadal nie ma wyróżnionej pozycji — wstawiamy ręcznego klienta
     (``external_source='manual'``, ``external_id=NULL`` → poza partial-unique
     z 0071 i poza upsertem Traffita, więc sync go nie dotknie ani nie zduplikuje).

Oba kroki są dodatkowo strażowane warunkiem „nie ma jeszcze wyróżnionej pozycji",
więc re-run (albo wyścig z ręcznym dodaniem) nie stworzy duplikatu w dropdownie.
"""

from alembic import op

revision = "0153_client_min_sprawiedliwosci"
down_revision = "0152_cv_generated_async_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Promuj istniejącego klienta o tej nazwie (case/space-insensitive),
    #    tylko jeden wiersz i tylko gdy nic jeszcze nie jest wyróżnione.
    op.execute(
        """
        UPDATE clients
        SET display_name = 'Ministerstwo Sprawiedliwości'
        WHERE id = (
            SELECT id FROM clients
            WHERE display_name IS NULL
              AND hidden = false
              AND lower(btrim(name)) = lower('Ministerstwo Sprawiedliwości')
            ORDER BY id
            LIMIT 1
        )
        AND NOT EXISTS (
            SELECT 1 FROM clients
            WHERE display_name = 'Ministerstwo Sprawiedliwości'
              AND hidden = false
        )
        """
    )
    # 2) Jeśli nadal brak wyróżnionej pozycji → wstaw ręcznego klienta.
    #    `nda_signed` jawnie: na prodzie kolumna jest NOT NULL BEZ defaultu
    #    (drift względem 0001, które daje DEFAULT FALSE nullable) — INSERT bez
    #    niej wywalał NotNullViolationError i blokował alembic_version na 0152.
    op.execute(
        """
        INSERT INTO clients
            (name, display_name, status, hidden, nda_signed,
             external_source, created_at, updated_at)
        SELECT
            'Ministerstwo Sprawiedliwości', 'Ministerstwo Sprawiedliwości',
            'prospect', false, false, 'manual', now(), now()
        WHERE NOT EXISTS (
            SELECT 1 FROM clients
            WHERE display_name = 'Ministerstwo Sprawiedliwości'
              AND hidden = false
        )
        """
    )


def downgrade() -> None:
    # Usuń ręcznego sentinela, którego mogliśmy wstawić (tylko gdy nie ma
    # powiązanych ofert/kontraktów — nie kasujemy danych z historii).
    op.execute(
        """
        DELETE FROM clients
        WHERE display_name = 'Ministerstwo Sprawiedliwości'
          AND name = 'Ministerstwo Sprawiedliwości'
          AND external_source = 'manual'
          AND external_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.client_id = clients.id)
          AND NOT EXISTS (SELECT 1 FROM contracts k WHERE k.client_id = clients.id)
        """
    )
    # Od-wyróżnij ewentualnie promowane wiersze (np. klient z Traffita).
    op.execute(
        """
        UPDATE clients
        SET display_name = NULL
        WHERE display_name = 'Ministerstwo Sprawiedliwości'
        """
    )
