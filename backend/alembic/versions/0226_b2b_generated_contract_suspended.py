"""Czwarty status umowy B2B („Zawieszona") + dziennik zmian statusu.

DLACZEGO CZWARTY STATUS. Kontraktor kończy projekt u klienta, ale umowa B2B
dalej obowiązuje — czeka na kolejny projekt. Dotąd nie było jak tego zapisać:
`active` kłamał („nikt nie pracuje"), `closed` kłamał („umowa żyje"). `suspended`
opisuje dokładnie ten stan i zasila zakładkę „Umowy bez projektu".

POWODY ZAMKNIĘCIA SĄ WYMIENIANE, NIE ZAWĘŻANE. Katalog z 0203
(`resignation_before_signing`, `termination`, `mutual_agreement`) opisywał
ROZSTANIE Z PARTNEREM; nowy opisuje KONIEC PROJEKTU. Trzy stare wartości zostają
w CHECK-u mimo zniknięcia z pickera: produkcja ma wiersze `closed`, które je
niosą, więc zawężenie predykatu wywaliłoby `ADD CONSTRAINT` na skanie tabeli,
a nawet gdyby przeszło — historyczny powód zamieniłby się w puste miejsce.
CHECK jest tu domeną dopuszczalnych wartości, nie listą podpowiedzi w UI.

TRZY CHECK-I RAZEM, WIDEN FIRST (wzorzec 0224/0222). `ck_..._closure_coherence`
przypina obie gałęzie do konkretnych statusów, więc wiersz `suspended` łamie je
obie. Samo poszerzenie `ck_..._contract_status` dałoby IntegrityError przy
pierwszym zawieszeniu umowy. Kolejność wewnątrz upgrade'u też nie jest dowolna:
`contract_status` musi przyjmować `suspended`, zanim koherencja zacznie się do
niego odwoływać. `alembic/env.py` nie ustawia `transaction_per_migration`, więc
całość leci w jednej transakcji i okno niespójności nie istnieje.

`suspended` W KOHERENCJI ZACHOWUJE SIĘ JAK `closed`: wymaga powodu i daty.
„Zawieszona" bez odpowiedzi na pytanie „co i kiedy się skończyło" jest
bezużyteczna dokładnie tak samo jak „Zakończona" bez tych pól.

DLACZEGO OSOBNA TABELA ZDARZEŃ, A NIE KOLUMNY NA UMOWIE. Powrót z zawieszenia
na `active` MUSI wyczyścić `closure_*` (wymusza to koherencja), więc data i powód
poprzedniego zakończenia projektu nie mają gdzie zostać. Kolumna
„poprzednie zawieszenie" pamiętałaby wyłącznie ostatnie i dublowała semantykę
pól, które już istnieją. Dziennik odpowiada na pytanie „ile razy ten kontraktor
był bez projektu i dlaczego", którego żaden pojedynczy wiersz nie udźwignie.

ON DELETE CASCADE, nie RESTRICT. `DELETE /api/b2b-generator/generated/{id}`
istnieje i zwalnia numer umowy do ponownego użycia; RESTRICT zamieniłby dziennik
w blokadę tej operacji.

Revision ID: 0226_b2b_generated_contract_suspended
Revises: 0225_contract_survives_candidate_delete
"""

from alembic import op


revision = "0226_b2b_generated_contract_suspended"
down_revision = "0225_contract_survives_candidate_delete"
branch_labels = None
depends_on = None


_STATUS_WIDE = (
    "CHECK (contract_status IN ('active', 'in_progress', 'suspended', 'closed'))"
)
_STATUS_NARROW = "CHECK (contract_status IN ('active', 'in_progress', 'closed'))"

# Siedem powodów z bieżącego katalogu + trzy z 0203, których nie wolno wyciąć
# (patrz docstring). Kolejność jak w UI, legacy na końcu.
_REASON_WIDE = """CHECK (
            closure_reason IS NULL
            OR closure_reason IN (
                'no_client_budget',
                'contractor_found_other_project',
                'contractor_health_reasons',
                'contractor_underperformance',
                'project_completed',
                'internalization',
                'other',
                'resignation_before_signing',
                'termination',
                'mutual_agreement'
            )
        )"""

# Dosłowna treść z 0203 — downgrade wraca do niej, nie do parafrazy.
_REASON_NARROW = """CHECK (
            closure_reason IS NULL
            OR closure_reason IN (
                'resignation_before_signing',
                'termination',
                'mutual_agreement',
                'other'
            )
        )"""

_COHERENCE_WIDE = """CHECK (
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

# Dosłowna treść z 0224.
_COHERENCE_NARROW = """CHECK (
            (
                contract_status IN ('active', 'in_progress')
                AND closure_reason IS NULL
                AND closure_date IS NULL
                AND closure_reason_other IS NULL
            )
            OR (
                contract_status = 'closed'
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
    # 1. WIDEN FIRST — kolejność jak w docstringu: domena statusu, potem domena
    #    powodu, na końcu koherencja, która odwołuje się do obu.
    _rewrite("ck_b2b_generated_contracts_contract_status", _STATUS_WIDE)
    _rewrite("ck_b2b_generated_contracts_closure_reason", _REASON_WIDE)
    _rewrite("ck_b2b_generated_contracts_closure_coherence", _COHERENCE_WIDE)

    # 2. Dziennik zmian statusu. `IF NOT EXISTS` bo to samo DDL leci
    #    safety-netem z `entrypoint.sh` i może pójść pierwsze.
    #
    #    `to_status` NOT NULL, `from_status` nullowalne: pierwszy wpis dla umowy
    #    sprzed wdrożenia dziennika nie ma udokumentowanego stanu wyjściowego,
    #    a zmyślenie go („pewnie active") byłoby fałszywym zapisem w rejestrze,
    #    który ma służyć jako dowód.
    #
    #    Bez CHECK-a na `to_status`: dziennik jest zapisem TEGO, CO SIĘ STAŁO.
    #    Gdyby katalog statusów kiedyś się zmienił, ograniczenie tutaj kazałoby
    #    przepisywać historię, żeby dopasować ją do bieżącego słownika.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS b2b_generated_contract_status_events (
            id SERIAL PRIMARY KEY,
            generated_contract_id INTEGER NOT NULL
                REFERENCES b2b_generated_contracts (id) ON DELETE CASCADE,
            from_status VARCHAR(16) NULL,
            to_status VARCHAR(16) NOT NULL,
            effective_date DATE NULL,
            reason VARCHAR(32) NULL,
            reason_other TEXT NULL,
            job_id INTEGER NULL REFERENCES jobs (id) ON DELETE SET NULL,
            client_id INTEGER NULL REFERENCES clients (id) ON DELETE SET NULL,
            changed_by INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_b2b_gc_status_events_contract
            ON b2b_generated_contract_status_events (generated_contract_id)
        """
    )

    # 3. Bez backfillu. Istniejące wiersze mają poprawny status, a historia
    #    sprzed wdrożenia siedzi w `activities` (`action='status_changed'`) —
    #    przepisywanie jej tutaj udawałoby, że dziennik istniał wcześniej.


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS b2b_generated_contract_status_events")

    # RECLASSIFY FIRST (wzorzec 0224). Zawężone CHECK-i odrzuciłyby istniejące
    # dane, więc wartości spoza starych domen muszą zniknąć, ZANIM wrócą wąskie
    # predykaty.
    #
    # `suspended` → `closed`, nie → `active`: wiersz zawieszony MA wypełnione
    # `closure_reason`/`closure_date`, a wąska koherencja wymaga dla `active`
    # kompletu NULL. Reklasyfikacja na `active` bez czyszczenia tych pól
    # wyprodukowałaby sprzeczność; czyszczenie ich kasowałoby dane. `closed`
    # jest jedynym statusem, który przyjmuje taki wiersz bez straty.
    op.execute(
        "UPDATE b2b_generated_contracts SET contract_status = 'closed' "
        "WHERE contract_status = 'suspended'"
    )
    # Powody spoza katalogu 0203 → `other`. `closure_reason_other` musi wtedy
    # być NIEPUSTE (wąska koherencja wiąże `other` z tym polem), więc w tym
    # samym UPDATE zapisujemy tam czytelny ślad po pierwotnej wartości —
    # inaczej downgrade wywaliłby się na własnym constraincie.
    op.execute(
        """
        UPDATE b2b_generated_contracts
           SET closure_reason_other = COALESCE(
                   NULLIF(TRIM(closure_reason_other), ''),
                   'Powód sprzed migracji 0226: ' || closure_reason
               ),
               closure_reason = 'other'
         WHERE closure_reason IS NOT NULL
           AND closure_reason NOT IN (
               'resignation_before_signing',
               'termination',
               'mutual_agreement',
               'other'
           )
        """
    )

    _rewrite("ck_b2b_generated_contracts_closure_coherence", _COHERENCE_NARROW)
    _rewrite("ck_b2b_generated_contracts_closure_reason", _REASON_NARROW)
    _rewrite("ck_b2b_generated_contracts_contract_status", _STATUS_NARROW)
