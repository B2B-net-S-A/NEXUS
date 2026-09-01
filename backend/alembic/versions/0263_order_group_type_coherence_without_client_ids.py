"""Zdejmij produkcyjne ID klientów z więzu spójności typu zamówienia.

Revision ID: 0263_group_type_no_client_ids
Revises: 0262_separate_md_periodic

Migracja 0251 zakodowała politykę klientową wprost w więzie CHECK:
``client_id IN (155, 38339)`` (Lotte Wedel, Cyfrowy Polsat). Baza rozstrzygała
w ten sposób, KTO jest tymi klientami — a to jest wiedza aplikacji, nie schematu.

Skutek był realny, nie teoretyczny. Aplikacja traktuje tożsamość tych klientów
jako coś, co wolno podmienić: `tests/conftest.py` ma autouse fixture odpinającą
bramki (`LOTTE_WEDEL_CLIENT_ID = -2`, e-Zdrowie `-1`), właśnie po to, żeby
155. testowy klient nie dostał przypadkiem polityki Wedla — `clients.id` rośnie
między testami we wspólnej bazie shardu. Monkeypatch nie sięga jednak więzu
w bazie, więc gdy testowy klient dostawał serial 155:

* aplikacja liczyła ``client_uses_shared_md_pool(155) -> False`` i zapisywała
  generyczne MD per konsultant (``is_md_budget_based = FALSE``),
* baza wciąż uważała 155 za Wedla i żądała ``is_md_budget_based = TRUE``,
* zapis kończył się ``CheckViolationError`` i 500 w środku aktywacji szkicu.

Odtworzone deterministycznie: ``setval('clients_id_seq', 154)`` i
``test_completing_typed_draft_materializes_budget_at_the_correct_scope``
[md-md_quantity-75] pada w 14 s. Na produkcji ta sama niezgodność czeka na
każdą zmianę liczby plików testowych albo tempa przyrostu klientów.

Więz zostaje przy tym, co jest NAPRAWDĘ niezmiennikiem schematu: zgodność typu
z flagami (cost => pula PLN, md => brak puli PLN). Reguła „wspólną pulę MD mają
wyłącznie CP i Lotte Wedel" zostaje wyłącznie w aplikacji, gdzie już jest —
i to w OBU miejscach zapisu:

* ``api/client_order_groups.py`` — dwa jawne 422 w obie strony (wspólna pula
  u obcego klienta oraz jej brak u CP/Wedla),
* ``services/order_group_materializer.py`` — flaga jest WYPROWADZANA
  z ``client_uses_shared_md_pool``, więc niespójny kształt nie ma jak powstać.

Nowy predykat jest identyczny z ``_ROLLBACK_CHECK`` z 0251, czyli z kształtem
sprzed tamtej migracji. ``NOT VALID`` jak w 0251: nie chcemy, żeby historyczny
wiersz zablokował wdrożenie, a dla każdego INSERT/UPDATE Postgres i tak sprawdza.
Predykat jest ROZSZERZENIEM poprzedniego (dopuszcza ściśle więcej), więc żaden
istniejący wiersz nie staje się nielegalny i migracja nie potrzebuje UPDATE-a.
"""

from alembic import op


revision = "0263_group_type_no_client_ids"
down_revision = "0262_separate_md_periodic"
branch_labels = None
depends_on = None


# Bez client_id: schemat pilnuje spójności typu z flagami, a tożsamość klienta
# rozstrzyga aplikacja.
_COHERENCE_CHECK = (
    "order_type IS NULL OR "
    "(order_type = 'cost' AND is_cost_based = TRUE "
    "AND is_md_budget_based = FALSE) OR "
    "(order_type = 'md' AND is_cost_based = FALSE)"
)

# Kształt z 0251 — z zaszytymi ID. Wyłącznie do downgrade'u.
_CLIENT_SCOPED_CHECK = (
    "order_type IS NULL OR "
    "(order_type = 'cost' AND is_cost_based = TRUE "
    "AND is_md_budget_based = FALSE) OR "
    "(order_type = 'md' AND is_cost_based = FALSE "
    "AND ((client_id IN (155, 38339) AND is_md_budget_based = TRUE) "
    "OR (client_id NOT IN (155, 38339) AND is_md_budget_based = FALSE)))"
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_client_order_groups_explicit_type_coherence",
        "client_order_groups",
        type_="check",
    )
    op.create_check_constraint(
        "ck_client_order_groups_explicit_type_coherence",
        "client_order_groups",
        _COHERENCE_CHECK,
        postgresql_not_valid=True,
    )


def downgrade() -> None:
    # Powrót do kształtu z 0251. Uwaga: wiersz zapisany pod 0263 dla klienta
    # 155/38339 w kształcie per-konsultant staje się wtedy nielegalny przy
    # KAŻDYM późniejszym UPDATE tego wiersza — ``NOT VALID`` tego nie zdejmuje.
    # Na produkcji taki wiersz nie powstaje (aplikacja wyprowadza flagę
    # z polityki klienta), więc rollback jest bezpieczny, ale nie jest
    # bezwarunkowy.
    op.drop_constraint(
        "ck_client_order_groups_explicit_type_coherence",
        "client_order_groups",
        type_="check",
    )
    op.create_check_constraint(
        "ck_client_order_groups_explicit_type_coherence",
        "client_order_groups",
        _CLIENT_SCOPED_CHECK,
        postgresql_not_valid=True,
    )
