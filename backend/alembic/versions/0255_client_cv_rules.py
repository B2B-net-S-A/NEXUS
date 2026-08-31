"""Reguły CV per klient: nazwa pliku, język, blok zgody RODO.

Tworzy ``client_cv_rules`` (1:1 z klientem) i dokłada ``client_id`` do
``cv_generated_documents`` — do tej pory tabela miała tylko ``job_id``, więc
tryb "upload" (99,9% generacji) nie niósł żadnego kontekstu klienta.

Seed 14 reguł powstaje z szablonów „Profil Championa" z Pomocy (migracja
``0219``), ale **jako propozycje**: ``confirmed_at`` zostaje NULL, a runtime
stosuje wyłącznie reguły zatwierdzone przez człowieka. Powód jest w danych —
dopasowanie szablonu do wiersza w ``clients`` nie jest 1:1 (samych bytów „BNP"
jest siedem, „Credit Agricole" co najmniej dwa). Dlatego wiersz powstaje
wyłącznie przy **dokładnie jednym** trafieniu nazwy; przy zera lub wielu nie
powstaje nic, a ekran „Reguły CV per klient" w Ustawieniach pokazuje pozycję
jako wymagającą ręcznego wskazania klienta.

Dopasowanie po nazwie jest tu dopuszczalne wyłącznie dlatego, że nic z niego
nie wchodzi w życie samo z siebie. Bramki produkcyjne idą po ``client_id`` —
``Client.name`` nadpisuje sync Traffita.

Revision ID: 0255_client_cv_rules
Revises: 0254_orders_procedure_seed
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0255_client_cv_rules"
down_revision = "0254_orders_procedure_seed"
branch_labels = None
depends_on = None


# (seed_key, wzorzec nazwy klienta, filename_pattern, spaces_to_underscores,
#  cv_language, requires_en_copy, requires_rodo_consent_block)
#
# `cv_language` jest NULL dla klientów wymagających OBU wersji (ALIOR, BIK,
# BNP, SANTANDER) — wymuszenie „pl" zablokowałoby wygenerowanie wersji EN,
# czyli dokładnie tego, czego ci klienci oczekują. Ich wymóg niesie
# `requires_en_copy`, które jest przypomnieniem, nie blokadą.
_SEED: list[tuple[str, str, str, bool, str | None, bool, bool]] = [
    (
        "profil-championa-wzor-alior-docx",
        "%alior%",
        "B2B_{STANOWISKO}_{IMIE_NAZWISKO}",
        False,
        None,
        True,
        False,
    ),
    (
        "profil-championa-wzor-bik-docx",
        "%informacji kredytowej%",
        "B2B_{STANOWISKO}_{IMIE_NAZWISKO}",
        False,
        None,
        True,
        False,
    ),
    (
        "profil-championa-wzor-bnp-paribas-docx",
        "%bnp%",
        "B2B_{STANOWISKO}_{IMIE_NAZWISKO}",
        False,
        None,
        True,
        False,
    ),
    (
        "profil-championa-wzor-santander-docx",
        "%santander%",
        "B2B_{STANOWISKO}_{IMIE_NAZWISKO}",
        False,
        None,
        True,
        False,
    ),
    (
        "profil-championa-wzor-nordea-docx",
        "%nordea%",
        "B2B_{STANOWISKO}_{IMIE_NAZWISKO}",
        False,
        "en",
        False,
        False,
    ),
    (
        "profil-championa-wzor-pfron-docx",
        "%pfron%",
        "B2B_{STANOWISKO}_{IMIE_NAZWISKO}",
        False,
        "pl",
        False,
        False,
    ),
    (
        "profil-championa-wzor-kir-docx",
        "%krajowa izba rozliczeniowa%",
        "B2B_{STANOWISKO}_{IMIE_NAZWISKO}",
        True,
        "pl",
        False,
        False,
    ),
    (
        "profil-championa-wzor-bank-pocztowy-docx",
        "%pocztow%",
        "Bank_Pocztowy_{STANOWISKO}_{IMIE_NAZWISKO}",
        True,
        "pl",
        False,
        False,
    ),
    (
        "profil-championa-wzor-credit-agricole-docx",
        "%credit agricole%",
        "B2B.NET_{STANOWISKO}_{IMIE_NAZWISKO}_{DATA}",
        True,
        "pl",
        False,
        False,
    ),
    (
        "profil-championa-wzor-pansa-docx",
        "%pansa%",
        "B2B_PANSA_{STANOWISKO}_{IMIE_NAZWISKO}",
        True,
        "pl",
        False,
        False,
    ),
    (
        "profil-championa-wzor-tauron-docx",
        "%tauron%",
        "B2B_Tauron_{STANOWISKO}_{IMIE_NAZWISKO}",
        True,
        "pl",
        False,
        False,
    ),
    (
        "profil-championa-wzor-energa-docx",
        "%energa%",
        "ENERGA_{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}",
        False,
        "pl",
        False,
        False,
    ),
    (
        "profil-championa-wzor-orlen-docx",
        "%orlen%",
        "ORLEN_{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}",
        False,
        "pl",
        False,
        False,
    ),
    (
        "profil-championa-wzor-pko-bp-docx",
        "%pko%",
        "ZOB-{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}",
        False,
        "pl",
        False,
        True,
    ),
]


# Wiersz powstaje tylko przy dokładnie jednym żywym kliencie pasującym do
# wzorca. `hidden` / `merged_into_client_id` odsiewają zduplikowane warianty,
# które inaczej podbiłyby licznik i zablokowały zasianie poprawnej reguły.
_SEED_SQL = sa.text(
    """
    INSERT INTO client_cv_rules (
        client_id, filename_pattern, spaces_to_underscores, cv_language,
        requires_en_copy, requires_rodo_consent_block, seed_key,
        confirmed_at, created_at, updated_at
    )
    SELECT c.id, :filename_pattern, :spaces_to_underscores, :cv_language,
           :requires_en_copy, :requires_rodo, :seed_key,
           NULL, now(), now()
    FROM clients c
    WHERE lower(c.name) LIKE :name_pattern
      AND c.hidden = false
      AND c.merged_into_client_id IS NULL
      AND (
          SELECT count(*) FROM clients c2
          WHERE lower(c2.name) LIKE :name_pattern
            AND c2.hidden = false
            AND c2.merged_into_client_id IS NULL
      ) = 1
    ON CONFLICT (client_id) DO NOTHING
    """
)


def upgrade() -> None:
    op.create_table(
        "client_cv_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename_pattern", sa.String(length=300), nullable=True),
        sa.Column(
            "spaces_to_underscores",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("cv_language", sa.String(length=8), nullable=True),
        sa.Column(
            "requires_en_copy",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "requires_rodo_consent_block",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("seed_key", sa.String(length=64), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "confirmed_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "cv_language IS NULL OR cv_language IN ('pl', 'en')",
            name="ck_client_cv_rules_language",
        ),
    )
    op.create_index(
        "ux_client_cv_rules_client", "client_cv_rules", ["client_id"], unique=True
    )
    op.create_index("ix_client_cv_rules_seed_key", "client_cv_rules", ["seed_key"])
    op.create_index(
        "ix_client_cv_rules_confirmed_at", "client_cv_rules", ["confirmed_at"]
    )

    op.add_column(
        "cv_generated_documents", sa.Column("client_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_cv_generated_documents_client",
        "cv_generated_documents",
        "clients",
        ["client_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_cv_generated_documents_client_id", "cv_generated_documents", ["client_id"]
    )

    # Backfill klienta dla historycznych generacji z trybu "new" — tam klient
    # jest wyprowadzalny z oferty i bez tego lista „Wygenerowane CV" pokazałaby
    # „—" przy dokumentach, które klienta miały od zawsze.
    op.execute(
        """
        UPDATE cv_generated_documents d
        SET client_id = j.client_id
        FROM jobs j
        WHERE d.job_id = j.id
          AND d.client_id IS NULL
          AND j.client_id IS NOT NULL
        """
    )

    conn = op.get_bind()
    for (
        seed_key,
        name_pattern,
        filename_pattern,
        spaces_to_underscores,
        cv_language,
        requires_en_copy,
        requires_rodo,
    ) in _SEED:
        conn.execute(
            _SEED_SQL,
            {
                "seed_key": seed_key,
                "name_pattern": name_pattern,
                "filename_pattern": filename_pattern,
                "spaces_to_underscores": spaces_to_underscores,
                "cv_language": cv_language,
                "requires_en_copy": requires_en_copy,
                "requires_rodo": requires_rodo,
            },
        )


def downgrade() -> None:
    op.drop_index("ix_cv_generated_documents_client_id", "cv_generated_documents")
    op.drop_constraint(
        "fk_cv_generated_documents_client", "cv_generated_documents", type_="foreignkey"
    )
    op.drop_column("cv_generated_documents", "client_id")
    op.drop_index("ix_client_cv_rules_confirmed_at", "client_cv_rules")
    op.drop_index("ix_client_cv_rules_seed_key", "client_cv_rules")
    op.drop_index("ux_client_cv_rules_client", "client_cv_rules")
    op.drop_table("client_cv_rules")
