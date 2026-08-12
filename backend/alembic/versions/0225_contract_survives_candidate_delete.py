"""Usunięcie kandydata NIE kasuje umów, faktur ani podpisów.

DLACZEGO. Hard delete kandydata (przywracany w tym samym PR) idzie kaskadą
`candidates` → `contracts` → `invoices` / `document_signatures` /
`client_orders`. Te trzy nie mają własnego FK na kandydata — wiszą na umowie —
więc skasowanie umowy zabiera ze sobą fakturę i podpis. „Usuń profil kandydata"
znaczyłoby wtedy „usuń faktury", a to dokumenty księgowe i dowodowe, których
retencja nie zależy od tego, czy dana osoba jest jeszcze w bazie rekrutacyjnej.
Skalę tej nadmiarowości mierzy `/api/admin/candidate-pii-orphans`
(`evidence_rows_a_hard_delete_would_destroy`).

CO SIĘ ZMIENIA. `contracts.candidate_id` przechodzi z `ON DELETE CASCADE` na
`SET NULL` i staje się nullowalny. Umowa przestaje wskazywać osobę, ale zostaje
w rejestrze razem z całym poddrzewem finansowym.

DLACZEGO PSEUDONIM, A NIE SAMO NULL. Po wyzerowaniu FK nic już nie wiąże ze sobą
faktur tej samej osoby — księgowość traci informację „te trzy umowy dotyczyły
jednego podmiotu", a bez niej nie da się nawet uzgodnić rozrachunków.
`candidate_subject_ref` trzyma kluczowany HMAC (ten sam wzorzec i klucz co
`candidate_identity_quarantine._fingerprint`), stemplowany w momencie usuwania.
Jest stabilny i nieodwracalny bez klucza, więc łączy dokumenty bez przywracania
tożsamości. Kolumna jest NULL dla wszystkich umów żyjących kandydatów — sens ma
wyłącznie tam, gdzie osoba już nie istnieje.

FK DROPOWANY PRZEZ INTROSPEKCJĘ, nie po nazwie. Migracja 0146 przepisała te
więzy sweepem generującym nazwy (`contracts_candidate_id_candidates_fkey`), ale
starsze bazy mogą mieć nazwę z czasów `create_table`
(`contracts_candidate_id_fkey`). Kasowanie po zgadniętej nazwie zostawiłoby na
prodzie stary CASCADE i cała ta migracja byłaby bezczynna.

Revision ID: 0225_contract_survives_candidate_delete
Revises: 0224_b2b_generated_contract_in_progress
"""

from alembic import op


revision = "0225_contract_survives_candidate_delete"
down_revision = "0224_b2b_generated_contract_in_progress"
branch_labels = None
depends_on = None


_FK_NAME = "contracts_candidate_id_candidates_fkey"

# Zdejmij KAŻDY więz `contracts.candidate_id → candidates`, niezależnie od
# nazwy, i dopiero potem dołóż własny.
_DROP_EXISTING = """
DO $$
DECLARE
    con RECORD;
BEGIN
    FOR con IN
        SELECT c.conname
          FROM pg_constraint c
          JOIN pg_attribute a
            ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
         WHERE c.conrelid = 'contracts'::regclass
           AND c.contype = 'f'
           AND c.confrelid = 'candidates'::regclass
           AND a.attname = 'candidate_id'
    LOOP
        EXECUTE format(
            'ALTER TABLE contracts DROP CONSTRAINT %I', con.conname
        );
    END LOOP;
END $$
"""


def upgrade() -> None:
    op.execute(
        "ALTER TABLE contracts "
        "ADD COLUMN IF NOT EXISTS candidate_subject_ref VARCHAR(64) NULL"
    )
    # Bez tego `SET NULL` wywala się na NOT NULL w momencie usuwania kandydata,
    # czyli dokładnie wtedy, gdy ma zadziałać.
    op.execute("ALTER TABLE contracts ALTER COLUMN candidate_id DROP NOT NULL")
    op.execute(_DROP_EXISTING)
    op.execute(
        f"ALTER TABLE contracts ADD CONSTRAINT {_FK_NAME} "
        "FOREIGN KEY (candidate_id) REFERENCES candidates (id) "
        "ON DELETE SET NULL"
    )
    # Odpięta umowa musi być odnajdywalna — rejestr filtruje po tym kluczu przy
    # uzgadnianiu rozrachunków osób, których już nie ma.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contracts_candidate_subject_ref "
        "ON contracts (candidate_subject_ref)"
    )


def downgrade() -> None:
    # Powrót do CASCADE wymaga NOT NULL, a NOT NULL nie zniesie umów już
    # odpiętych od usuniętych kandydatów. Kasujemy je świadomie: przy CASCADE
    # i tak by nie istniały, więc downgrade odtwarza stan, w którym ich nie ma.
    # (Ta migracja nie jest odpalana w CI — patrz komentarz w 0224.)
    op.execute("DELETE FROM contracts WHERE candidate_id IS NULL")
    op.execute("DROP INDEX IF EXISTS ix_contracts_candidate_subject_ref")
    op.execute(_DROP_EXISTING)
    op.execute("ALTER TABLE contracts ALTER COLUMN candidate_id SET NOT NULL")
    op.execute(
        f"ALTER TABLE contracts ADD CONSTRAINT {_FK_NAME} "
        "FOREIGN KEY (candidate_id) REFERENCES candidates (id) "
        "ON DELETE CASCADE"
    )
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS candidate_subject_ref")
