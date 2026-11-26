"""Linki Pracuj.pl z panelu pracodawcy zamienione na publiczne (26.11.2026).

Revision ID: 0793_pracuj_public_links
Revises: 0792_cv_page1_highlight_ai

Pomiar 26.11.2026: 47 z 96 zapisanych linków do ogłoszeń na Pracuj.pl
prowadziło do panelu pracodawcy, który otwiera tylko ktoś zalogowany na konto
firmy. ``showjoboffer/<id>`` staje się ``www.pracuj.pl/praca?groupId=<id>``,
reszta stron panelu traci link (oznaczenie „opublikowane” zostaje). Same
UPDATE-y danych, bez zmian schematu. SQL ma jedno źródło
(``app/services/job_ad_publication_schema.PRACUJ_PANEL_LINKS_DML``) — te same
instrukcje stoją w ``entrypoint.sh``.
"""

from alembic import op

from app.services import job_ad_publication_schema as schema

revision = "0793_pracuj_public_links"
down_revision = "0792_cv_page1_highlight_ai"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.PRACUJ_PANEL_LINKS_DML:
        op.execute(stmt)


def downgrade() -> None:
    # Stare linki z panelu i tak nie otwierały się bez logowania; kod sprzed
    # tej rewizji czyta publiczny link bez zmian. Nie ma czego cofać.
    pass
