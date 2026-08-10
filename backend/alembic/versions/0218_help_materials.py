"""Materiały w zakładce Pomoc — biblioteka linków do dokumentów w SharePoincie.

Revision ID: 0218_help_materials
Revises: 0217_cv_interactive_share
Create Date: 2026-08-10

Zakładka Pomoc dostaje sekcję „Materiały": firmowe wzory i formularze
onboardingowe klientów wystawione jako LINKI. NEXUS ich nie hostuje — pliki
zostają w SharePoincie, gdzie są natywnie edytowalne w Word Online i
wersjonowane przez M365. Tabela trzyma wyłącznie metadane i adres.

``is_editable_template`` wyróżnia nasze własne wzory (szablon umowy, profil
Championa, notatka po screeningu), którym FE dokłada przycisk „Edytuj";
formularze klientów zostają tylko do otwarcia.

Odczyt: każdy zalogowany. Edycja wpisów: wyłącznie admin (jak ``procedures``).
Całość zdublowana w safety-net ``entrypoint.sh`` (prod alembic bywa orphaned).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0218_help_materials"
down_revision = "0217_cv_interactive_share"
branch_labels = None
depends_on = None


# ─────────────────────────────────────────────────────────────────────────────
# SEED
#
# 26 pozycji: 3 wzory własne w kategorii „Szablony i wzory" + formularze
# onboardingowe klientów NORDEA, BNP CARDIF, BNP Paribas, Bank Pocztowy, ERGO,
# PFRON, POLKOMTEL, TAURON, VeloBank.
#
# Format pól:
#   (slug, category, title, url, is_editable_template, sort_order, description)
# `is_editable_template=True` mają DOKŁADNIE 3 wiersze — „Szablon do umowy",
# „Profil Championa", „Notatka po screeningu". To nasze własne wzory, którym
# frontend dokłada skrót „Edytuj w Word Online"; formularze klientów zawsze
# False (tylko do otwarcia).
#
# Tożsamością wiersza jest ``slug``, nie ``url`` — adresy SharePointa to
# share-linki z tokenem ``?e=``, który wygasa przy ponownym udostępnieniu
# pliku. Gdy link padnie, admin podmienia sam URL z UI i nic innego się nie
# rozjeżdża.
#
# WAŻNE — gdzie to realnie zadziała: jeśli ta migracja została już raz
# zastosowana, alembic jej NIE powtórzy, więc zmiana wierszy tutaj nie ruszy
# istniejącej bazy. Efektywnym kanałem jest wtedy lustro w ``entrypoint.sh``
# (``_DATA_STATEMENTS`` leci przy każdym boocie i jest rerun-safe przez
# ON CONFLICT). Zmieniasz tu — zmień też tam, żeby kanały się nie rozjechały.
# ─────────────────────────────────────────────────────────────────────────────

_SEED_ROWS: list[tuple[str, str, str, str, bool, int, str | None]] = [
    (
        "szablon-umowy-b2b-2026",
        "Szablony i wzory",
        "Nowy szablon do Umowy B2B 2026.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQBYCLTZTfqoQIw5DkZA-cO9AVTZkGhqkY4tfhq5AGXgv3E?e=HmRSwm",
        True,
        10,
        "Szablon do umowy",
    ),
    (
        "profil-championa-wzor",
        "Szablony i wzory",
        "Profil_Championa_WZÓR.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQAXQ2XHDxDdTY-sIuR1URcmASEIat4mo1UbzjlPGtowpF4?e=gY6p9K",
        True,
        20,
        "Profil championa",
    ),
    (
        "notatka-po-screeningu-wzor",
        "Szablony i wzory",
        "Notatka po screeningu_WZÓR.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQAH82MUIw8NQIA_awLVQa-OAa3Sp9NH3uuJ2--0Zh2w_Yk?e=B4d1Ee",
        True,
        30,
        "Notatka po screeningu",
    ),
    (
        "nordea-appendix-3-confidentiality",
        "Onboarding — NORDEA",
        "Appendix 3 (Confidentiality undertaking template).docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQCNrQioV9HRW5Cg2hPDrkvmAaoRkll4bOvCRtM9DVrguJY?e=hWCrNJ",
        False,
        100,
        None,
    ),
    (
        "nordea-oswiadczenie-krk-2026",
        "Onboarding — NORDEA",
        "OŚWIADCZENIE o niekaralności KRK_2026.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQDkqOfMK4lFQLBAP5nReg_xATO6ea46CcWlOG28H2GjoOo?e=AeHgut",
        False,
        110,
        None,
    ),
    (
        "bnp-cardif-zgoda-dane-osobowe",
        "Onboarding — BNP CARDIF",
        "Zgoda na przetwarzanie danych osobowych przez BNP_CPL (1).doc",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQBQzJjtYMnlTo61T78myddsAcbI62g1FlkFgO2weFZ-acc?e=kLgtvU",
        False,
        200,
        None,
    ),
    (
        "bnp-paribas-oswiadczenie-zdalny-dostep",
        "Onboarding — BNP Paribas Bank Polska",
        "Oświadczenie_zdalny dostęp_Kontraktor BNP.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQBYka4c_dUyXrtKfSyBKh3tARHMTWrB_E_j7LCY3O2I2iE?e=DROMA9",
        False,
        300,
        None,
    ),
    (
        "bank-pocztowy-oswiadczenie-niekaralnosci",
        "Onboarding — Bank Pocztowy",
        "Oświadczenie o niekaralności Bank Pocztowy.doc",
        "https://b2bnetsa.sharepoint.com/:b:/s/B2B_ALL/IQDGbFJOOMiEWJl6Q5mRjahnAf4P_hvVBiHxAhgDkn4jt8M?e=hSNYsc",
        False,
        400,
        None,
    ),
    (
        "bank-pocztowy-oswiadczenie-poufnosci",
        "Onboarding — Bank Pocztowy",
        "Oświadczenie o zachowaniu poufności.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQC5Pk2IFiJmVJYq8Wbe3snAAUibIPmUIMhXdS4ITVMhVGo?e=Jpm70p",
        False,
        410,
        None,
    ),
    (
        "ergo-oswiadczenia-folder",
        "Onboarding — ERGO",
        "Oświadczenia (folder)",
        "https://b2bnetsa.sharepoint.com/:f:/s/B2B_ALL/IgB4aG8FiGNCWIkwKfKEfFRQAalrkypJlOnZx5nf1QI9-_s?e=7DoJ7E",
        False,
        500,
        None,
    ),
    (
        "ergo-opis-dokumentow-onboarding",
        "Onboarding — ERGO",
        "ERGO_opis dokumentów do podpisania przed onboardingiem.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQDlucxDIrS-Wo2W4VxrFLqUARzxom-pr3tedyLsaOd7Jw0?e=cfUxnJ",
        False,
        510,
        None,
    ),
    (
        "pfron-oswiadczenie-bhp",
        "Onboarding — PFRON",
        "oswiadczenie bhp.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQBh6_04XLdNQKGgyoztq3nuAVscjlXYUdX3rtDDzHY08Ag?e=SuVP2a",
        False,
        600,
        None,
    ),
    (
        "pfron-oswiadczenie-wzor",
        "Onboarding — PFRON",
        "oświadczenie_wzór.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQCSIrWRj3NfSr6qJqvUsosyARbm-LGN9VFG2ShtUpCx7fs?e=6ERa0W",
        False,
        610,
        None,
    ),
    (
        "pfron-zalacznik-polityka-oswiadczenie",
        "Onboarding — PFRON",
        "załącznik do Polityki - oświadczenie.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQBh8IMyyPqGT5jG1rWpqPr-AdOkcdtDAhQRaFbz5pHsYqo?e=PYyXZi",
        False,
        620,
        None,
    ),
    (
        "polkomtel-informacja-przetwarzanie-danych",
        "Onboarding — POLKOMTEL",
        "Informacja o przetwarzaniu danych osobowych.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQDoSxX3OKNiU7MK4E8bzIWfAfn7Fe6YDFBmo1NBesju4AY?e=8bGTaA",
        False,
        700,
        None,
    ),
    (
        "tauron-zalacznik-1-zakres-uslug",
        "Onboarding — TAURON",
        "ZAŁĄCZNIK NR 1 Zakres usług.pdf",
        "https://b2bnetsa.sharepoint.com/:b:/s/B2B_ALL/IQBTNdLh2w4ISZoJmXNOee50AfWL8fNj-R9pBWsSANPbZL4?e=8xgiVe",
        False,
        800,
        None,
    ),
    (
        "tauron-draft-umowy",
        "Onboarding — TAURON",
        "draft umowy Tauron.pdf",
        "https://b2bnetsa.sharepoint.com/:b:/s/B2B_ALL/IQCsLARwCnQ5Qbp0xKlhZRDJAUvCkm6RxKF7oc1ubBfOKOc?e=id9xUp",
        False,
        810,
        None,
    ),
    (
        "tauron-zalacznik-2-raport-miesieczny",
        "Onboarding — TAURON",
        "ZAŁĄCZNIK NR 2 Raport Miesięczny — uproszczony.pdf",
        "https://b2bnetsa.sharepoint.com/:b:/s/B2B_ALL/IQDxLFIyvELvTajgG7nVN0HcAfWrBK2oS6ce460XAA00RMY?e=LYdn9h",
        False,
        820,
        None,
    ),
    (
        "tauron-zalacznik-3-upowaznienie-dane-osobowe",
        "Onboarding — TAURON",
        "ZAŁĄCZNIK NR 3 Upoważnienie szczególne do Przetwarzania Danych Osobowych.pdf",
        "https://b2bnetsa.sharepoint.com/:b:/s/B2B_ALL/IQCrCdKO5SFZQqGZ9Sm861fmAXSv0DJeI3a8BtcOVv-CxsA?e=jizscN",
        False,
        830,
        None,
    ),
    (
        "tauron-zalacznik-4-vpn",
        "Onboarding — TAURON",
        "ZAŁĄCZNIK NR 4 Zasady Zdalnego Dostępu VPN dla Wykonawcy.pdf",
        "https://b2bnetsa.sharepoint.com/:b:/s/B2B_ALL/IQAigsT1LENsQIk3IZ-AH79kAccTfb7jIJa4MTrODwKv0vc?e=cimF4u",
        False,
        840,
        None,
    ),
    (
        "tauron-zalacznik-5a-porozumienie-przesylanie-dokumentow",
        "Onboarding — TAURON",
        "ZAŁĄCZNIK NR 5a Porozumienie przesyłanie dokumentów (1).pdf",
        "https://b2bnetsa.sharepoint.com/:b:/s/B2B_ALL/IQC4sflP6q8eSabZNsID3c_mAeq-_iwcTWpnWEk65cGTsd8?e=DNhDsP",
        False,
        850,
        None,
    ),
    (
        "tauron-zalacznik-5b-ksef",
        "Onboarding — TAURON",
        "ZAŁĄCZNIK NR 5b Zasady przesyłania faktur i załączników za pośrednictwem Krajowego Systemu e-Faktur (KSeF).pdf",
        "https://b2bnetsa.sharepoint.com/:b:/s/B2B_ALL/IQCc79RRqqAPRLt0h8St_5OtAfVBGgrWjhNTdNLqqZA1-B0?e=FtKyx8",
        False,
        860,
        None,
    ),
    (
        "tauron-zalacznik-6-incydenty-bezpieczenstwa",
        "Onboarding — TAURON",
        "ZAŁĄCZNIK NR 6 Wymagania dot. zgłaszania i obsługi incydentów bezpieczeństwa.pdf",
        "https://b2bnetsa.sharepoint.com/:b:/s/B2B_ALL/IQCwHFWV-XG6RpjNCDW6_ebmAeG4-jyaM9YSknnsjjNqp_A?e=bOhHjT",
        False,
        870,
        None,
    ),
    (
        "velobank-dokumenty-etat-umowa-ramowa",
        "Onboarding — VeloBank",
        "Dokumenty_Etat_VeloBank_umowa ramowa.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQCj4OMyTYoIQKqTu5r0GlsTAfAVb6np3ZmEDei0lQhCzew?e=DX5iEM",
        False,
        900,
        None,
    ),
    (
        "velobank-dokumenty-podwykonawcy-nowy",
        "Onboarding — VeloBank",
        "Dokumenty_Podwykonawcy_VeloBank NOWY.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQAiRlr-0uFzVp_uqPTdh724AX5H89ZunbnOxy-5w_zrLAU?e=heH4fX",
        False,
        910,
        None,
    ),
    (
        "velobank-dokumenty-podwykonawcy-instrukcja",
        "Onboarding — VeloBank",
        "Dokumenty_Podwykonawcy_VeloBank+Instrukcja.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQBQwWFCXgP-QJhd4B43CxucAfoTp9f5T6MGOkJWA_nr-M8?e=IpwtCU",
        False,
        920,
        None,
    ),
]


_INSERT_SQL = sa.text(
    """
    INSERT INTO help_materials (
        slug, category, title, url, description,
        is_editable_template, sort_order, is_published,
        created_at, updated_at
    )
    VALUES (
        :slug, :category, :title, :url, :description,
        :is_editable_template, :sort_order, TRUE,
        now(), now()
    )
    ON CONFLICT (slug) DO NOTHING
    """
)


def upgrade() -> None:
    op.create_table(
        "help_materials",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_editable_template",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "is_published",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_help_materials_slug", "help_materials", ["slug"], unique=True)
    op.create_index("ix_help_materials_category", "help_materials", ["category"])
    op.create_index("ix_help_materials_sort_order", "help_materials", ["sort_order"])
    op.create_index("ix_help_materials_id", "help_materials", ["id"])

    # Seed idempotentny — ON CONFLICT (slug) DO NOTHING.
    conn = op.get_bind()
    for (
        slug,
        category,
        title,
        url,
        is_editable_template,
        sort_order,
        description,
    ) in _SEED_ROWS:
        conn.execute(
            _INSERT_SQL,
            {
                "slug": slug,
                "category": category,
                "title": title,
                "url": url,
                "description": description,
                "is_editable_template": is_editable_template,
                "sort_order": sort_order,
            },
        )


def downgrade() -> None:
    op.drop_index("ix_help_materials_id", table_name="help_materials")
    op.drop_index("ix_help_materials_sort_order", table_name="help_materials")
    op.drop_index("ix_help_materials_category", table_name="help_materials")
    op.drop_index("ix_help_materials_slug", table_name="help_materials")
    op.drop_table("help_materials")
