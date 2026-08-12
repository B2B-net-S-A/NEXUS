"""Trzeci status wygenerowanej umowy B2B + snapshot danych Partnera na liście.

DLACZEGO TRZECI STATUS. Świeżo wygenerowana umowa dostawała dotąd `active`
z defaultu kolumny — rejestr twierdził „Aktywna" o dokumencie, który dopiero
poszedł do podpisu. Od teraz `active` znaczy „podpisana obustronnie" i ustawia
je WYŁĄCZNIE potwierdzenie podpisu; generowanie ustawia `in_progress`. ZERO
retroaktywności: istniejące wiersze zostają `active`. O żadnym z nich nie wiemy,
czy jest podpisany, a zgadywanie w rejestrze dokumentów prawnych jest gorsze niż
brak informacji.

PUŁAPKA, KTÓRA WYMUSZA PRZEPISANIE DWÓCH CHECK-ÓW RAZEM.
`ck_b2b_generated_contracts_closure_coherence` (migracja 0203) ma OBIE gałęzie
przypięte do `contract_status = 'active'` / `= 'closed'`. Wiersz `in_progress`
łamie obie, więc samo poszerzenie `ck_..._contract_status` dałoby IntegrityError
na KAŻDYM generowaniu umowy. `in_progress` jest w koherencji traktowany jak
`active`: komplet pól `closure_*` musi być NULL.

WIDEN FIRST, WRITE SECOND (wzorzec 0222). Oba CHECK-i lecą przed jakimkolwiek
zapisem nowej wartości i w jednej transakcji (`alembic/env.py` nie ustawia
`transaction_per_migration`) — okno, w którym `contract_status` przyjmuje
`in_progress`, a koherencja jeszcze nie, odrzucałoby każdy INSERT.

GOŁY `ADD CONSTRAINT`, BEZ `NOT VALID` (wzorzec 0212, nie 0203). Poszerzenie
CHECK-a to nadzbiór starego predykatu, który 0203 już zwalidowało — skan nie ma
na czym paść, a tabela ma na produkcji ~5 wierszy. `NOT VALID` zostawiłby za to
`pg_constraint.convalidated = false` na stałe, czyli trwały brud w katalogu.
Pętla `NOT VALID` + `VALIDATE` z 0203 opisuje ograniczony czasowo start
kontenera z entrypointu, nie pięciowierszowe poszerzenie w alembicu.

NOWE KOLUMNY = ODNORMALIZOWANY SNAPSHOT `render_payload`. Lista „Wygenerowane
umowy" pokazuje nazwę firmy z rejestru, NIP i datę rozpoczęcia usług oraz
filtruje po zakresie daty rozpoczęcia po stronie serwera. Wyciąganie tego
z JSONB per wiersz jest niefiltrowalne po stronie SQL-a i nieczytelne w kodzie.

`partner_entity_type` (JDG vs spółka) jest snapshotem BINARNEGO sygnału
z rejestru (CEIDG → `sole_trader`, KRS → `company`) z momentu generowania i NIE
jest backfillowany: w zapisanych payloadach nie ma ani `source`, ani `krs`.
Dla wierszy historycznych typ podmiotu wyznacza heurystyka po nazwie w warstwie
serializacji, z regułą „niejednoznaczne → spółka". NULL w kolumnie znaczy
dokładnie „brak sygnału z rejestru" i to jest informacja, nie brak danych.

Revision ID: 0223_b2b_generated_contract_in_progress
Revises: 0222_rename_talent_radar_source
"""

from alembic import op


revision = "0223_b2b_generated_contract_in_progress"
down_revision = "0222_rename_talent_radar_source"
branch_labels = None
depends_on = None


_STATUS_WIDE = "CHECK (contract_status IN ('active', 'in_progress', 'closed'))"
_STATUS_NARROW = "CHECK (contract_status IN ('active', 'closed'))"

# `in_progress` jest tu traktowany jak `active`: umowa w drodze do podpisu nie
# ma i nie może mieć pól zamknięcia.
_COHERENCE_WIDE = """CHECK (
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

# Dosłowna treść z 0203 — downgrade musi wrócić do niej, nie do parafrazy.
_COHERENCE_NARROW = """CHECK (
            (
                contract_status = 'active'
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

_ENTITY_TYPE = (
    "CHECK (partner_entity_type IS NULL "
    "OR partner_entity_type IN ('sole_trader', 'company'))"
)


def _rewrite(name: str, definition: str) -> None:
    """DROP + ADD zamiast `EXCEPTION WHEN duplicate_object THEN NULL`.

    Ten drugi idiom (0203) po cichu ZOSTAWIA stary constraint — a produkcja ma
    już wąski CHECK z 0203, więc bez DROP-a zostałaby z `IN ('active','closed')`
    na zawsze. Ta sama para leci w lustrze w `entrypoint.sh`.
    """
    op.execute(f"ALTER TABLE b2b_generated_contracts DROP CONSTRAINT IF EXISTS {name}")
    op.execute(
        f"ALTER TABLE b2b_generated_contracts ADD CONSTRAINT {name} {definition}"
    )


def upgrade() -> None:
    # 1. Kolumny. Produkcja dostaje to samo DDL safety-netem z entrypoint.sh,
    #    więc każda instrukcja musi tolerować, że lustro poszło pierwsze.
    op.execute(
        """
        ALTER TABLE b2b_generated_contracts
            ADD COLUMN IF NOT EXISTS partner_legal_name VARCHAR(255) NULL,
            ADD COLUMN IF NOT EXISTS partner_nip VARCHAR(32) NULL,
            ADD COLUMN IF NOT EXISTS start_date DATE NULL,
            ADD COLUMN IF NOT EXISTS partner_entity_type VARCHAR(16) NULL
        """
    )

    # 2. WIDEN FIRST. Oba CHECK-i razem — patrz docstring.
    _rewrite("ck_b2b_generated_contracts_contract_status", _STATUS_WIDE)
    _rewrite("ck_b2b_generated_contracts_closure_coherence", _COHERENCE_WIDE)

    # 3. Domena typu podmiotu. NULL dozwolony = wiersz bez sygnału z rejestru.
    _rewrite("ck_b2b_generated_contracts_partner_entity_type", _ENTITY_TYPE)

    # 4. Backfill ze snapshotu `render_payload`. Klucze są 1:1 nazwami pól
    #    `B2BRenderRequest` (bez aliasów, bez `exclude_none`).
    #
    #    `WHERE <kolumna> IS NULL`: idempotencja. Ten sam SQL siedzi
    #    w `_DATA_STATEMENTS` entrypointu i leci przy KAŻDYM starcie kontenera —
    #    wartość raz poprawiona ręcznie nie może zostać nadpisana starym
    #    payloadem.
    #
    #    `jsonb_typeof(...) = 'object'`: payload skalarny (`"x"`, `123`) nie ma
    #    z czego wyjąć klucza; bez tego `->>` byłby zakładem o wersję Postgresa.
    #
    #    `left(..., 255)`: payload trzyma dowolnie długi string z formularza,
    #    kolumna ma 255 — bez obcięcia `value too long` wywala CAŁY start
    #    kontenera, nie jeden wiersz.
    op.execute(
        """
        UPDATE b2b_generated_contracts
           SET partner_legal_name =
               left(NULLIF(TRIM(render_payload ->> 'partner_legal_name'), ''), 255)
         WHERE partner_legal_name IS NULL
           AND render_payload IS NOT NULL
           AND jsonb_typeof(render_payload) = 'object'
           AND NULLIF(TRIM(render_payload ->> 'partner_legal_name'), '') IS NOT NULL
        """
    )
    #    NIP kanonicznie do samych cyfr: surowe formatowanie zostaje
    #    w `render_payload` (dokument renderuje się bez zmian), a kolumna jest
    #    jednoznaczna — inaczej „1234563218" nie znajdzie wiersza zapisanego
    #    jako „123-456-32-18".
    op.execute(
        r"""
        UPDATE b2b_generated_contracts
           SET partner_nip = left(
                   NULLIF(
                       regexp_replace(
                           COALESCE(render_payload ->> 'partner_nip', ''),
                           '\D', '', 'g'
                       ),
                       ''
                   ),
                   32
               )
         WHERE partner_nip IS NULL
           AND render_payload IS NOT NULL
           AND jsonb_typeof(render_payload) = 'object'
           AND NULLIF(
                   regexp_replace(
                       COALESCE(render_payload ->> 'partner_nip', ''), '\D', '', 'g'
                   ),
                   ''
               ) IS NOT NULL
        """
    )
    #    Regex-guard zamiast `NULLIF(..., '')::date`: CI-sentinel
    #    (`scripts/verify_b2b_signature_migration.py`) sieje payload
    #    `{"probe":"0196","preserve":true}` BEZ klucza `start_date`, a formularz
    #    umie zapisać pusty string. `::date` na jednym i drugim wywala migrację.
    #    `[0-9]` a nie `\d` — `\d` w nie-rawowym stringu to SyntaxWarning na 3.12.
    op.execute(
        """
        UPDATE b2b_generated_contracts
           SET start_date = (render_payload ->> 'start_date')::date
         WHERE start_date IS NULL
           AND render_payload IS NOT NULL
           AND jsonb_typeof(render_payload) = 'object'
           AND render_payload ->> 'start_date' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
        """
    )
    # `partner_entity_type` świadomie BEZ backfillu — patrz docstring.


def downgrade() -> None:
    # RECLASSIFY FIRST (wzorzec 0212). Zawężony CHECK odrzuciłby `in_progress`,
    # więc wartość musi zniknąć z danych, ZANIM wróci wąski predykat.
    # `in_progress` → `active`, bo zawężona koherencja wymaga dla `active`
    # kompletu `closure_*` = NULL, a szeroki CHECK gwarantował to dla
    # `in_progress` — reklasyfikacja nie może więc wyprodukować sprzeczności.
    op.execute(
        "UPDATE b2b_generated_contracts SET contract_status = 'active' "
        "WHERE contract_status = 'in_progress'"
    )

    op.execute(
        "ALTER TABLE IF EXISTS b2b_generated_contracts "
        "DROP CONSTRAINT IF EXISTS "
        "ck_b2b_generated_contracts_partner_entity_type"
    )
    _rewrite("ck_b2b_generated_contracts_closure_coherence", _COHERENCE_NARROW)
    _rewrite("ck_b2b_generated_contracts_contract_status", _STATUS_NARROW)

    for column in (
        "partner_entity_type",
        "start_date",
        "partner_nip",
        "partner_legal_name",
    ):
        op.execute(
            f"""
            ALTER TABLE IF EXISTS b2b_generated_contracts
                DROP COLUMN IF EXISTS {column}
            """
        )
