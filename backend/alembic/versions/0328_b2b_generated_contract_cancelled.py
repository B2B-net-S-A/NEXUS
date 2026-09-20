"""Piąty status umowy B2B: „Anulowana" (umowa, która nie doszła do skutku).

Partner wycofuje się przed podpisem. Do tej migracji jedynym wyjściem była
„Zakończona", co kłamie: nie skończył się projekt, tylko umowa nigdy nie zaczęła
obowiązywać. Numer jest już zużyty i nie wraca do puli (UNIQUE(year, seq)), więc
wpis musi zostać w rejestrze z uczciwym oznaczeniem.

Dwa CHECK-i, nie jeden — ta sama pułapka co w 0224 i 0226:
`ck_..._closure_coherence` ma obie gałęzie przypięte do konkretnych statusów,
więc poszerzenie samej domeny `contract_status` dałoby wiersz `cancelled`
łamiący OBIE gałęzie, czyli IntegrityError przy pierwszym anulowaniu.

`cancelled` trafia do gałęzi „pola zamknięcia puste" (razem z `active`
i `in_progress`), a NIE do `('closed', 'suspended')`: umowa, która nie doszła do
skutku, nie ma czego ani kiedy kończyć. Katalogu `closure_reason` ta migracja
nie rusza.

Revision ID: 0328_b2b_generated_contract_cancelled
Revises: 0327_cv_factual_verification
"""

from alembic import op


revision = "0328_b2b_generated_contract_cancelled"
down_revision = "0327_cv_factual_verification"
branch_labels = None
depends_on = None


_STATUS_WIDE = (
    "CHECK (contract_status IN "
    "('active', 'in_progress', 'cancelled', 'suspended', 'closed'))"
)
# Dosłowna treść z 0226 — downgrade wraca do niej, nie do parafrazy.
_STATUS_NARROW = (
    "CHECK (contract_status IN ('active', 'in_progress', 'suspended', 'closed'))"
)

_COHERENCE_WIDE = """CHECK (
            (
                contract_status IN ('active', 'in_progress', 'cancelled')
                AND closure_reason IS NULL
                AND closure_date IS NULL
                AND closure_reason_other IS NULL
            )
            OR (
                contract_status IN ('closed', 'suspended')
                AND closure_reason IS NOT NULL
                AND closure_date IS NOT NULL
                AND (
                    (closure_reason = 'other')
                    = (closure_reason_other IS NOT NULL)
                )
            )
        )"""

# Dosłowna treść z 0226.
_COHERENCE_NARROW = """CHECK (
            (
                contract_status IN ('active', 'in_progress')
                AND closure_reason IS NULL
                AND closure_date IS NULL
                AND closure_reason_other IS NULL
            )
            OR (
                contract_status IN ('closed', 'suspended')
                AND closure_reason IS NOT NULL
                AND closure_date IS NOT NULL
                AND (
                    (closure_reason = 'other')
                    = (closure_reason_other IS NOT NULL)
                )
            )
        )"""


def _rewrite(name: str, definition: str) -> None:
    """DROP + ADD zamiast `EXCEPTION WHEN duplicate_object THEN NULL`.

    Ten drugi idiom (0203) po cichu ZOSTAWIA stary constraint — a produkcja ma
    już węższe CHECK-i, więc bez DROP-a zostałaby z nimi na zawsze. Ta sama para
    leci w lustrze w `entrypoint.sh`.
    """
    op.execute(f"ALTER TABLE b2b_generated_contracts DROP CONSTRAINT IF EXISTS {name}")
    op.execute(
        f"ALTER TABLE b2b_generated_contracts ADD CONSTRAINT {name} {definition}"
    )


def upgrade() -> None:
    # WIDEN FIRST: najpierw domena statusu, potem koherencja, która się do niej
    # odwołuje. Odwrotna kolejność wywala się na tym, że koherencja dopuszcza
    # wartość, której domena jeszcze nie zna.
    _rewrite("ck_b2b_generated_contracts_contract_status", _STATUS_WIDE)
    _rewrite("ck_b2b_generated_contracts_closure_coherence", _COHERENCE_WIDE)

    # Bez backfillu i bez zmian w dzienniku statusów: `to_status`/`from_status`
    # celowo nie mają CHECK-a (0226), więc nowa wartość przechodzi tam bez DDL.


def downgrade() -> None:
    # RECLASSIFY FIRST (wzorzec 0224/0226). Zawężony CHECK odrzuciłby istniejące
    # wiersze `cancelled`, więc muszą zniknąć, ZANIM wróci wąski predykat.
    #
    # `cancelled` → `in_progress`, nie → `closed`: anulowana umowa jest
    # z definicji niepodpisana i ma KOMPLET pól zamknięcia pustych. `closed`
    # wymaga powodu i daty, których ten wiersz nie ma i których nie wolno
    # zmyślić; `in_progress` przyjmuje go bez straty i jest jego prawdziwym
    # poprzednikiem — dokumentem czekającym na podpis.
    op.execute(
        "UPDATE b2b_generated_contracts SET contract_status = 'in_progress' "
        "WHERE contract_status = 'cancelled'"
    )

    _rewrite("ck_b2b_generated_contracts_closure_coherence", _COHERENCE_NARROW)
    _rewrite("ck_b2b_generated_contracts_contract_status", _STATUS_NARROW)
