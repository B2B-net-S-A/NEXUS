"""Materiały Pomocy: szablon zaproszenia na spotkanie przygotowujące (prep).

Do tej pory ``help_materials`` była biblioteką LINKÓW — każdy wiersz wskazywał
plik w SharePoincie (0218) i dlatego ``url`` był NOT NULL. Zaproszenie
kalendarzowe nie jest plikiem: rekruter potrzebuje TREŚCI (tematu i opisu
wydarzenia), którą wkleja do Outlooka. Stąd trzy zmiany schematu:

* ``url`` staje się NULLABLE — szablon nie ma adresu,
* dochodzą ``template_subject`` (temat) i ``template_body`` (treść),
* CHECK ``ck_help_materials_link_or_template`` wymusza, że wiersz jest ALBO
  linkiem, ALBO szablonem. Wiersz bez jednego i drugiego wyrenderowałby się
  w zakładce Pomoc jako martwa pozycja bez żadnej akcji — użytkownik czyta to
  jak awarię, a nie jak pustą treść.

Zdanie „UWAGA! Do zaproszenia załączamy CV wysłane pod dany projekt" jest
INSTRUKCJĄ DLA REKRUTERA i CELOWO nie ma go w ``template_body``: wylądowałoby
w zaproszeniu wysłanym kandydatowi jako wewnętrzna notatka operacyjna. Miejsce
tej podpowiedzi to UI obok przycisku, nie treść.

Nawiasy okrągłe w treści — „(nazwa Klienta)", „(data interview)" — są tym, co
rekruter podmienia ręcznie. To nie jest składnia szablonowania: ta sama treść
jest kopiowana do Outlooka, gdzie żaden silnik jej nie rozwinie.

Revision ID: 0229_help_materials_invite_template
Revises: 0228_finance_module_and_order_file_uploader
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0229_help_materials_invite_template"
down_revision = "0228_finance_module_and_order_file_uploader"
branch_labels = None
depends_on = None


_CHECK_NAME = "ck_help_materials_link_or_template"
_SEED_SLUG = "zaproszenie-prep-spotkanie"

_SEED_SUBJECT = (
    "Przygotowanie do interview z (nazwa Klienta) – (imię i nazwisko kandydata)"
)

# Treść dosłowna — puste linie są częścią układu wiadomości, więc zapisujemy je
# tak, jak mają wyjść w Outlooku (żadnego re-wrapowania przy odczycie).
#
# „(nazwa klienta)" małą literą jest CELOWO zostawione tak, jak podał autor.
# Podstawianie na profilu kandydata jest niewrażliwe na wielkość liter
# (patrz ``fillInviteTemplate``), więc oba warianty dostają realną nazwę.
_SEED_BODY = (
    "Dzień dobry (bądź per „Ty”),\n"
    "\n"
    "Zapraszam na spotkanie przygotowujące do interview z (nazwa Klienta) "
    "na stanowisko (nazwa stanowiska).\n"
    "Termin spotkania przygotowującego: (data prepa)\n"
    "\n"
    "Termin interview z (nazwa klienta): (data interview)\n"
    "Link do opisu stanowiska: (link do pracuj / rocketjobs / JJIT)\n"
    "\n"
    "W razie pytań pozostaję do dyspozycji.\n"
    "\n"
    "Pozdrawiam"
)

# sort_order 35 = zaraz za trzema wzorami własnymi (10/20/30) i przed profilami
# Championa per klient (od 40) — szablon jest wzorem, nie dokumentem klienta.
_SEED_SORT_ORDER = 35


_INSERT_SQL = sa.text(
    """
    INSERT INTO help_materials (
        slug, category, title, url, description,
        template_subject, template_body,
        is_editable_template, sort_order, is_published,
        created_at, updated_at
    )
    VALUES (
        :slug, :category, :title, NULL, :description,
        :template_subject, :template_body,
        FALSE, :sort_order, TRUE,
        now(), now()
    )
    ON CONFLICT (slug) DO NOTHING
    """
)


def upgrade() -> None:
    op.alter_column(
        "help_materials",
        "url",
        existing_type=sa.Text(),
        nullable=True,
    )
    op.add_column(
        "help_materials",
        sa.Column("template_subject", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "help_materials",
        sa.Column("template_body", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        _CHECK_NAME,
        "help_materials",
        "url IS NOT NULL OR template_body IS NOT NULL",
    )

    conn = op.get_bind()
    conn.execute(
        _INSERT_SQL,
        {
            "slug": _SEED_SLUG,
            "category": "Szablony i wzory",
            "title": "Zaproszenie na spotkanie przygotowujące (prep)",
            "description": (
                "Zaproszenie kalendarzowe wysyłane kandydatowi przed rozmową "
                "z klientem."
            ),
            "template_subject": _SEED_SUBJECT,
            "template_body": _SEED_BODY,
            "sort_order": _SEED_SORT_ORDER,
        },
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM help_materials WHERE slug = :slug"),
        {"slug": _SEED_SLUG},
    )
    op.drop_constraint(_CHECK_NAME, "help_materials", type_="check")
    op.drop_column("help_materials", "template_body")
    op.drop_column("help_materials", "template_subject")
    # Wiersze-szablony dodane przez admina po tej migracji NIE dają się wyrazić
    # w starym schemacie (url NOT NULL, brak kolumn treści). Kasujemy je jawnie,
    # bo inaczej sam ALTER wywala się na naruszeniu NOT NULL i downgrade staje
    # w połowie — z upuszczonymi już kolumnami treści.
    conn.execute(sa.text("DELETE FROM help_materials WHERE url IS NULL"))
    op.alter_column(
        "help_materials",
        "url",
        existing_type=sa.Text(),
        nullable=False,
    )
