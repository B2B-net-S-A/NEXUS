"""Pomoc → Procedury: instrukcja obsługi zamówień dla Delivery Leada.

Revision ID: 0253_orders_procedure_seed
Revises: 0252_md_cost_result_precision3

Treść NIE jest przepisana do tej migracji, tylko czytana z
``app/data/procedures/zamowienia-instrukcja-delivery-lead.md``. Instrukcja ma
kilkadziesiąt kilobajtów i będzie poprawiana przy każdym tickecie ruszającym
zamówienia; wklejona tutaj (jak treść szablonu w 0229) musiałaby żyć naraz
w migracji i w safety-necie ``entrypoint.sh``, a dwie kopie długiego tekstu
rozjeżdżają się po pierwszej poprawce literówki w jednej z nich. Plik ``.md``
jest jednym źródłem dla obu kanałów i dodatkowo widać go w diffie PR-a jak
zwykły dokument, a nie jak ścianę stringów.

Konsekwencja, świadoma: powtórzenie tej migracji na świeżej bazie za rok
zasieje treść AKTUALNĄ, nie tę z dnia jej powstania. Dla dokumentacji, która ma
opisywać dzisiejszy system, to jest zachowanie pożądane — odwrotne (zamrożenie
treści sprzed roku) dałoby nowemu środowisku instrukcję, o której z góry
wiadomo, że kłamie.

Upsert, nie ``DO NOTHING``: instrukcja musi dać się poprawić kolejnym wdrożeniem,
bo inaczej pierwszy zasiew zostaje na zawsze i cały mechanizm pilnowania
świeżości (``tests/test_orders_procedure_freshness.py``) kończyłby się na
repozytorium, nie docierając do czytelnika.

Warunek ``WHERE procedures.updated_by IS NULL`` chroni pracę admina: zasiew
zostawia to pole puste, a każda edycja z aplikacji (``PUT /api/procedures/{id}``)
stempluje w nim autora. Wiersz raz poprawiony ręcznie przestaje być nadpisywany
— zamiast tego przy najbliższym wdrożeniu zostaje taki, jaki zapisał człowiek.
Sama instrukcja mówi o tym czytelnikowi wprost, więc nie jest to niespodzianka.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.data.procedures import ORDERS_PROCEDURE

revision = "0253_orders_procedure_seed"
down_revision = "0252_md_cost_result_precision3"
branch_labels = None
depends_on = None


_UPSERT = sa.text(
    """
    INSERT INTO procedures
        (title, slug, content, sort_order, is_published, created_at, updated_at)
    VALUES
        (:title, :slug, :content, :sort_order, TRUE, now(), now())
    ON CONFLICT (slug) DO UPDATE
        SET title = EXCLUDED.title,
            content = EXCLUDED.content,
            sort_order = EXCLUDED.sort_order,
            is_published = EXCLUDED.is_published,
            updated_at = now()
        WHERE procedures.updated_by IS NULL
    """
)


def upgrade() -> None:
    op.get_bind().execute(
        _UPSERT,
        {
            "title": ORDERS_PROCEDURE.title,
            "slug": ORDERS_PROCEDURE.slug,
            "content": ORDERS_PROCEDURE.read(),
            "sort_order": ORDERS_PROCEDURE.sort_order,
        },
    )


def downgrade() -> None:
    # Tylko wiersz, którego nikt nie tknął. Procedura poprawiona ręcznie przez
    # admina jest jego pracą, a nie artefaktem tej migracji — cofnięcie
    # migracji nie jest zgodą na skasowanie cudzego tekstu.
    op.get_bind().execute(
        sa.text(
            "DELETE FROM procedures WHERE slug = :slug AND updated_by IS NULL"
        ),
        {"slug": ORDERS_PROCEDURE.slug},
    )
