"""Sweep: ON DELETE CASCADE/SET NULL na WSZYSTKICH FK → candidates.id.

Revision ID: 0146_candidate_fk_cascade_sweep
Revises: 0145_contracts_order_consumption
Create Date: 2026-06-24

Twarde usuwanie kandydata (``DELETE /api/candidates/{id}``) wywalało się na
prodzie jako "Network Error". Przyczyna: FK-i wskazujące na ``candidates.id``
(np. ``talent_pool_memberships.candidate_id``, ``contracts.candidate_id``,
``screening_notes``, ``match_history``) NIE miały reguły ``ON DELETE`` na bazie
produkcyjnej. Migracja ``0141`` miała to naprawić dla 5 tabel, ale na prodzie
nie zadziałała (prawdopodobnie quirk ``op.create_foreign_key(..., ondelete=)``
w użytej wersji Alembica — FK powstawał bez reguły). Postgres rzucał
``IntegrityError`` → nieobsłużony 500 → Starlette generuje go PONAD CORS
middleware → brak nagłówka ``Access-Control-Allow-Origin`` → przeglądarka
raportuje to jako "Network Error" (a transakcja jest rollbackowana, więc
kandydat zostaje — stąd wrażenie, że "nic się nie dzieje").

Tabele takie jak ``talent_pool_memberships`` nie mają nawet relacji ORM na
``Candidate`` (w przeciwieństwie do ``notes``), więc kasowanie zależało WYŁĄCZNIE
od reguły ON DELETE na bazie — której nie było.

Ta migracja jest KOMPLETNA, IDEMPOTENTNA i ODPORNA:
  * Introspektuje KAŻDĄ tabelę i znajduje FK do ``candidates`` (dowolna nazwa
    kolumny — np. ``graph_subscriptions.parsed_candidate_id``), nie tylko 5
    wybranych jak w 0141.
  * ``SET NULL`` dla wierszy, które mają PRZEŻYĆ usunięcie kandydata (maile,
    subskrypcje grafowe, oceny pytań, wydarzenia kalendarza, wygenerowane CV) —
    zgodnie z ``ondelete="SET NULL"`` w modelach ORM. ``CASCADE`` dla reszty.
  * Pomija FK już mające właściwą regułę → zero zbędnego churnu i locków.
  * Używa surowego ``ALTER TABLE ... ADD CONSTRAINT ... ON DELETE ... NOT VALID``
    (a NIE ``op.create_foreign_key``) — odporne na quirk z 0141 ORAZ ``NOT
    VALID`` pomija full-scan, więc wielkie tabele (``match_history``,
    ``candidate_job_match_scores``) nie grożą timeoutem migracji na starcie
    kontenera. Reguła ON DELETE działa niezależnie od stanu ``NOT VALID``.
"""

import sqlalchemy as sa
from alembic import op

revision = "0146_candidate_fk_cascade_sweep"
down_revision = "0145_contracts_order_consumption"
branch_labels = None
depends_on = None


# (table, column) których wiersz ma PRZEŻYĆ usunięcie kandydata (odlinkowany).
# Wszystko inne wskazujące na candidates.id → CASCADE. Wyprowadzone z modeli
# ORM (deklarowane ``ondelete="SET NULL"``).
_SET_NULL = frozenset(
    {
        ("emails", "candidate_id"),
        ("graph_subscriptions", "parsed_candidate_id"),
        ("interview_question_ratings", "candidate_id"),
        ("calendar_events", "candidate_id"),
        ("cv_generated_documents", "candidate_id"),
    }
)


def _current_rule(fk: dict) -> str:
    """Normalizowana aktualna reguła ON DELETE ('' == brak / NO ACTION)."""
    v = ((fk.get("options") or {}).get("ondelete") or "").strip().upper()
    # Ustawiamy tylko CASCADE / SET NULL, więc NO ACTION/RESTRICT == "do naprawy".
    return v if v in ("CASCADE", "SET NULL") else ""


def _candidate_fks(insp):
    """Yield (table, column, fk_name) dla każdego pojedynczego FK → candidates."""
    for table in insp.get_table_names():
        for fk in insp.get_foreign_keys(table):
            if fk.get("referred_table") != "candidates":
                continue
            cols = fk.get("constrained_columns") or []
            if len(cols) != 1:  # pomijamy ewentualne FK złożone
                continue
            yield table, cols[0], fk.get("name"), _current_rule(fk)


def _apply(rule_for) -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table, col, name, current in list(_candidate_fks(insp)):
        desired = rule_for(table, col)
        if current == (desired or ""):
            continue
        if name:
            op.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT "{name}"')
        clause = f" ON DELETE {desired}" if desired else ""
        op.execute(
            f'ALTER TABLE "{table}" ADD CONSTRAINT "{table}_{col}_candidates_fkey" '
            f'FOREIGN KEY ("{col}") REFERENCES candidates (id){clause} NOT VALID'
        )


def upgrade() -> None:
    _apply(lambda table, col: "SET NULL" if (table, col) in _SET_NULL else "CASCADE")


def downgrade() -> None:
    # Świadomie NIE odwracamy do "gołych" FK: te reguły ON DELETE są zgodne z
    # intencją modeli ORM, a ich zdjęcie ponownie zepsułoby twarde usuwanie
    # kandydata (oryginalny bug). Migracja jest konwergentna — downgrade to
    # no-op.
    pass
