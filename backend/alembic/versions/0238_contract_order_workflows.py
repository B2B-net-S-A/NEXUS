"""Statusy kontraktów, przyszłe grupy zamówień i trwały PDF zamówienia.

Revision ID: 0238_contract_order_workflows
Revises: 0237_proposal_snapshot_hidden

Jedna rewizja odpowiada jednemu wdrożeniu siedmiu powiązanych ticketów:

* ``scheduled`` odróżnia przyszłe przedłużenie od równorzędnej aktywnej karty;
* master PDF grupy pozwala dosynchronizować konsultanta dodanego później;
* częściowo unikalne źródło dokumentu gwarantuje jeden automatyczny PDF danego
  zamówienia na kontrakt, bez ingerowania w dokumenty ręczne;
* korekta BIK aktywuje najnowszy nieanulowany kontrakt każdej wskazanej osoby.

Korekty danych nie cofamy w ``downgrade``: poprzedni status nie jest znany, a
zgadywanie przy rollbacku zmieniłoby prawidłowe dane biznesowe.
"""

import sqlalchemy as sa
from alembic import op

revision = "0238_contract_order_workflows"
down_revision = "0237_proposal_snapshot_hidden"
branch_labels = None
depends_on = None


_GROUP_STATUSES = "('active', 'scheduled', 'completed', 'exhausted')"
_PREVIOUS_GROUP_STATUSES = "('active', 'completed', 'exhausted')"


def upgrade() -> None:
    # ── Przyszłe zamówienia ────────────────────────────────────────────────
    op.drop_constraint(
        "ck_client_order_groups_status",
        "client_order_groups",
        type_="check",
    )
    op.create_check_constraint(
        "ck_client_order_groups_status",
        "client_order_groups",
        f"status IN {_GROUP_STATUSES}",
    )

    # ── Master PDF grupy ──────────────────────────────────────────────────
    op.add_column(
        "client_order_groups", sa.Column("filename", sa.String(255), nullable=True)
    )
    op.add_column(
        "client_order_groups", sa.Column("file_path", sa.String(512), nullable=True)
    )
    op.add_column(
        "client_order_groups",
        sa.Column("content_type", sa.String(128), nullable=True),
    )
    op.add_column(
        "client_order_groups", sa.Column("size_bytes", sa.Integer(), nullable=True)
    )
    op.add_column(
        "client_order_groups",
        sa.Column("file_uploaded_by", sa.Integer(), nullable=True),
    )
    op.add_column(
        "client_order_groups",
        sa.Column("file_uploaded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_client_order_groups_file_uploaded_by_users",
        "client_order_groups",
        "users",
        ["file_uploaded_by"],
        ["id"],
        ondelete="SET NULL",
    )

    # ── Automatyczne kopie na kontraktach ─────────────────────────────────
    op.add_column(
        "contract_documents",
        sa.Column("source_order_group_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_contract_documents_source_order_group",
        "contract_documents",
        "client_order_groups",
        ["source_order_group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_contract_documents_source_order_group_id",
        "contract_documents",
        ["source_order_group_id"],
    )
    op.create_index(
        "uq_contract_documents_contract_order_group",
        "contract_documents",
        ["contract_id", "source_order_group_id"],
        unique=True,
        postgresql_where=sa.text("source_order_group_id IS NOT NULL"),
    )

    # ── Jednorazowa korekta BIK ───────────────────────────────────────────
    # Najnowszy nieanulowany kontrakt per osoba+klient. Nie aktywujemy dawnych
    # umów historycznych, jeżeli kandydat ma więcej niż jeden rekord u BIK.
    op.execute(
        """
        WITH marker AS (
            INSERT INTO app_settings (key, value)
            VALUES (
                '0238_bik_contract_status_correction',
                jsonb_build_object(
                    'revision', '0238_contract_order_workflows',
                    'completed_at', clock_timestamp(),
                    'source', 'alembic'
                )
            )
            ON CONFLICT (key) DO NOTHING
            RETURNING key
        ), ranked AS (
            SELECT
                co.id,
                row_number() OVER (
                    PARTITION BY co.candidate_id, co.client_id
                    ORDER BY co.end_date DESC NULLS FIRST, co.id DESC
                ) AS position
            FROM contracts co
            JOIN candidates ca ON ca.id = co.candidate_id
            JOIN clients cl ON cl.id = co.client_id
            WHERE co.status <> 'void'::contractstatus
              AND lower(concat_ws(' ', cl.name, cl.display_name, cl.legal_name))
                    LIKE '%biuro informacji kredytowej%'
              -- Porównanie idzie po formie NFC, nie po surowym napisie.
              -- Część rekordów ma nazwisko zapisane w formie ROZŁOŻONEJ
              -- ("ń" = "n" + U+0301), więc równość CAŁEGO napisu
              -- cicho ich nie trafiała. Kosztowało to kontrakt #571,
              -- doaktywowany dopiero rewizją 0239 -- punktowo, jednym
              -- prefiksem LIKE, więc przyczyna zostawała. Tę samą podatność
              -- ma na tej liście "michał leśniak" ("ś" rozkłada się dokładnie
              -- tak samo), a migracja nie raportuje, ilu z dziewięciu ludzi
              -- faktycznie trafiła -- częściowe pudło było NIEWIDOCZNE.
              --
              -- UWAGA: ta poprawka NIE leczy produkcji. Marker
              -- '0238_bik_contract_status_correction' jest tam już wstawiony,
              -- więc UPDATE nigdy się nie powtórzy, a brakujące rekordy trzeba
              -- domknąć ręcznie. Działa dla baz odtwarzanych od zera i
              -- zdejmuje pułapkę ze wzorca, który ktoś skopiuje przy
              -- następnej liście nazwisk. Literały poniżej muszą zostać
              -- w NFC -- pilnuje tego test tests/test_migration_0238_name_matching.py
              AND lower(normalize(trim(ca.name) || ' ' || trim(ca.lastname), NFC))
                  IN (
                    'aleksander wojdyła',
                    'daniel madejski',
                    'maciej koc',
                    'robert łuszczyński',
                    'paweł łaski',
                    'konrad teper',
                    'michał leśniak',
                    'wojciech wojtak',
                    'grzegorz wadecki'
              )
              AND EXISTS (SELECT 1 FROM marker)
        )
        UPDATE contracts co
        SET status = 'active'::contractstatus,
            updated_at = now()
        FROM ranked
        WHERE co.id = ranked.id
          AND ranked.position = 1
        """
    )


def downgrade() -> None:
    op.drop_index(
        "uq_contract_documents_contract_order_group",
        table_name="contract_documents",
    )
    op.drop_index(
        "ix_contract_documents_source_order_group_id",
        table_name="contract_documents",
    )
    op.drop_constraint(
        "fk_contract_documents_source_order_group",
        "contract_documents",
        type_="foreignkey",
    )
    op.drop_column("contract_documents", "source_order_group_id")

    op.drop_constraint(
        "fk_client_order_groups_file_uploaded_by_users",
        "client_order_groups",
        type_="foreignkey",
    )
    op.drop_column("client_order_groups", "file_uploaded_at")
    op.drop_column("client_order_groups", "file_uploaded_by")
    op.drop_column("client_order_groups", "size_bytes")
    op.drop_column("client_order_groups", "content_type")
    op.drop_column("client_order_groups", "file_path")
    op.drop_column("client_order_groups", "filename")

    op.drop_constraint(
        "ck_client_order_groups_status",
        "client_order_groups",
        type_="check",
    )
    # Stary kod nie zna ``scheduled`` i przed tym ticketem pokazywał
    # przedłużenia jako osobne aktywne karty. Przywracamy dokładnie ten stan,
    # żeby rollback był wykonalny także po założeniu przyszłych zamówień.
    op.execute(
        "UPDATE client_order_groups SET status = 'active' WHERE status = 'scheduled'"
    )
    op.create_check_constraint(
        "ck_client_order_groups_status",
        "client_order_groups",
        f"status IN {_PREVIOUS_GROUP_STATUSES}",
    )
