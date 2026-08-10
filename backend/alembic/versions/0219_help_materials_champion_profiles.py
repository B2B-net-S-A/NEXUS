"""Materiały Pomocy: profile Championa per klient + angielskie KRK dla NORDEI.

Dokłada 15 pozycji do ``help_materials`` (tabela i pierwsze 26 wierszy — 0218):

* 14 profili Championa pod konkretnych klientów w nowej kategorii
  „Profile Championa — per klient". Wcześniej był tylko wzór ogólny; te są
  dopasowane do wymagań konkretnego klienta, więc dostają
  ``is_editable_template=True`` — to nasze dokumenty i bywają poprawiane.
* Angielska wersja oświadczenia o niekaralności w grupie „Onboarding — NORDEA"
  (kontraktorzy nieposługujący się polskim).

Literówka „niekaralnośći" w tytule jest CELOWA — tak nazywa się plik na
SharePoincie, a tytuł ma pozwalać go rozpoznać, nie poprawiać.

Etykiety klientów NIE zostały odgadnięte z kolejności wklejenia linków: każdy
adres rozwiązano w sesji SharePointa do nazwy pliku i dopiero to dało
przypisanie. Pomyłka dałaby pozycję „ALIOR" otwierającą dokument innego klienta
— błąd niewidoczny aż do wysyłki złego profilu.

Adresy oczyszczono z parametrów śledzących (``wdLOR``, ``clickparams``) oraz
z ``ovuser``, który niósł adres e-mail osoby kopiującej link.

Revision ID: 0219_help_materials_champion_profiles
Revises: 0218_help_materials
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0219_help_materials_champion_profiles"
down_revision = "0218_help_materials"
branch_labels = None
depends_on = None


# (slug, category, title, url, is_editable_template, sort_order, description)
#
# Slugi są DOSŁOWNIE takie, jakie wygenerowało API przy dodaniu tych pozycji
# przez panel admina na produkcji — dzięki temu ``ON CONFLICT (slug) DO NOTHING``
# czyni ten seed no-opem na istniejącej bazie, a zasiewa tylko odtworzoną.
_SEED_ROWS: list[tuple[str, str, str, str, bool, int, str | None]] = [
    (
        "profil-championa-wzor-alior-docx",
        "Profile Championa — per klient",
        "Profil_Championa_WZÓR_ALIOR.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQAqhBG2TeC-Rq5iZvv0eCIdAaU9wTC4GQsNeOQEIW6-pHU?e=gAcy15",
        True,
        40,
        None,
    ),
    (
        "profil-championa-wzor-bank-pocztowy-docx",
        "Profile Championa — per klient",
        "Profil_Championa_WZÓR_Bank_Pocztowy.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQDOeFoZ9jXlRZOOZS64x3jPATePmoyCq6n3Ey24KdM28wI?e=FRB6AY",
        True,
        41,
        None,
    ),
    (
        "profil-championa-wzor-bik-docx",
        "Profile Championa — per klient",
        "Profil_Championa_WZÓR_BIK.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQCGKeFvsfRdSJZQfx6ic3MIAd7ORch-9xFOn9SmTcYP9zQ?e=8TMS7l",
        True,
        42,
        None,
    ),
    (
        "profil-championa-wzor-bnp-paribas-docx",
        "Profile Championa — per klient",
        "Profil_Championa_WZÓR_BNP PARIBAS.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQCnzsRBh_jjRazf6E99DnujAfvlUPIlfS-il0gO7kARwWY?e=qi2sJ7",
        True,
        43,
        None,
    ),
    (
        "profil-championa-wzor-credit-agricole-docx",
        "Profile Championa — per klient",
        "Profil_Championa_WZÓR_Credit_Agricole.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQD2UQIpNGWNQazOxiiAzBwSAagOFte6eTs3bjTz1yVS6k0?e=O5obFf",
        True,
        44,
        None,
    ),
    (
        "profil-championa-wzor-energa-docx",
        "Profile Championa — per klient",
        "Profil_Championa_WZÓR_ENERGA.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQBuaj9FoVuqQ4kWjRWO-Q48AaREJPRIkwtkLuWktaoBWm4?e=y7aI5u",
        True,
        45,
        None,
    ),
    (
        "profil-championa-wzor-kir-docx",
        "Profile Championa — per klient",
        "Profil_Championa_WZÓR_KIR.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQCP1Cycr_nlSaamMIP9D3y0AX6qWLEcZ3g9VgXKMb0tgnc?e=a96UJd",
        True,
        46,
        None,
    ),
    (
        "profil-championa-wzor-nordea-docx",
        "Profile Championa — per klient",
        "Profil_Championa_WZÓR_Nordea.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQAdW75s9FA6T4ZtUzvWLQGvAYYmpHA-Ls7yqEDaCJhFe0I?e=e1WeCi",
        True,
        47,
        None,
    ),
    (
        "profil-championa-wzor-orlen-docx",
        "Profile Championa — per klient",
        "Profil_Championa_WZÓR_ORLEN.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQAtwxfeHg5ER69jFBwnZq-QAVmOsogbnKKDZBbzNu8gFjg?e=Q9DFPz",
        True,
        48,
        None,
    ),
    (
        "profil-championa-wzor-pansa-docx",
        "Profile Championa — per klient",
        "Profil_Championa_WZÓR_PANSA.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQBM19BRQcwNTqiKVYAhXRDZAXCJpfKjsFssyoRYyoW3dhQ?e=TvMegW",
        True,
        49,
        None,
    ),
    (
        "profil-championa-wzor-pfron-docx",
        "Profile Championa — per klient",
        "Profil_Championa_WZÓR_PFRON.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQDL2kX71z-0QYdvJzqjM93sAXPvO1Zll5DZEeX8M3oBJXI?e=ybfUNL",
        True,
        50,
        None,
    ),
    (
        "profil-championa-wzor-pko-bp-docx",
        "Profile Championa — per klient",
        "Profil_Championa_WZÓR_PKO_BP.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQD9_8XJmO59RK88a60JBHvrAewQThXykcP8aQ4zgjpJ9C0?e=BcPEVd",
        True,
        51,
        None,
    ),
    (
        "profil-championa-wzor-santander-docx",
        "Profile Championa — per klient",
        "Profil_Championa_WZÓR_SANTANDER.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQBiuBrkrRtWQ5tExRVDuDvgAXjxgxZOcFKOXPhrAvIii9k?e=CpPLwh",
        True,
        52,
        None,
    ),
    (
        "profil-championa-wzor-tauron-docx",
        "Profile Championa — per klient",
        "Profil_Championa_WZÓR_Tauron.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQBO8uaqIOaRTaCUnHvJ8KlHAdz0kAdvjQdC9bWFSK1VYas?e=1smhiG",
        True,
        53,
        None,
    ),
    (
        "oswiadczenie-o-niekaralnosci-eng-krk-2024-docx",
        "Onboarding — NORDEA",
        "Oświadczenie o niekaralnośći_ENG_KRK_2024.docx",
        "https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQANFFmetXfmS4PuZKyAAdTJAUlFelWJl0wN9bZVd4Gw1UE?e=itWxtg",
        False,
        120,
        "Wersja angielska oświadczenia o niekaralności (KRK 2024)",
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
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM help_materials WHERE slug = ANY(:slugs)"),
        {"slugs": [r[0] for r in _SEED_ROWS]},
    )
