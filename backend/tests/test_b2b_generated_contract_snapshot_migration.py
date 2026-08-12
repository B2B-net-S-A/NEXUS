"""Kontrakt migracji 0224: trzeci status + snapshot danych Partnera.

Prod alembic bywa osierocony (`entrypoint.sh` toleruje porażkę `upgrade heads`),
więc KAŻDA zmiana schematu musi mieć lustro w `entrypoint.sh` albo po cichu nigdy
nie dociera na produkcję. Ten plik pilnuje dwóch rzeczy, których nie złapie żaden
test funkcjonalny na świeżej bazie:

1. lustro istnieje i jest zgodne z migracją,
2. przepisywane CHECK-i są poprzedzone DROP-em — bo idiom
   `EXCEPTION WHEN duplicate_object THEN NULL` po cichu ZOSTAWIA stary
   constraint, a prod ma już wąski CHECK z 0203.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

MIGRATION = BACKEND / "alembic/versions/0224_b2b_generated_contract_in_progress.py"
MODEL = BACKEND / "app/models/b2b_generated_contract.py"
ENTRYPOINT = BACKEND / "entrypoint.sh"

_SNAPSHOT_COLUMNS = (
    "partner_legal_name",
    "partner_nip",
    "start_date",
    "partner_entity_type",
)


def test_migration_chains_onto_the_single_head():
    """Jedna głowa alembica jest bramką CI (`test_analytics_release_gates`).

    Ta rewizja była pierwotnie numerowana 0223 z rodzicem 0222 — i to był realny
    rozjazd: równolegle wszedł na maina `0223_cv_backfill_ai_feature` z TYM SAMYM
    rodzicem, co dawało dwie głowy. Git tego nie zgłasza (żadnych konfliktów,
    dwa różne pliki), więc bramka CI jest jedynym miejscem, gdzie to widać.
    """
    src = MIGRATION.read_text("utf-8")
    assert 'revision = "0224_b2b_generated_contract_in_progress"' in src
    assert 'down_revision = "0223_cv_backfill_ai_feature"' in src


def test_migration_widens_both_checks_not_just_the_status_one():
    """Sedno tej migracji.

    `ck_..._closure_coherence` z 0203 ma obie gałęzie przypięte do
    `active`/`closed`. Wiersz `in_progress` łamie OBIE, więc poszerzenie samego
    `ck_..._contract_status` dałoby IntegrityError na każdym generowaniu umowy.
    """
    src = MIGRATION.read_text("utf-8")
    assert "contract_status IN ('active', 'in_progress', 'closed')" in src
    assert "contract_status IN ('active', 'in_progress')" in src, (
        "closure_coherence musi traktować in_progress jak active — "
        "inaczej wiersz in_progress łamie obie gałęzie CHECK-a"
    )


def test_migration_drops_before_adding_each_rewritten_check():
    """`EXCEPTION WHEN duplicate_object THEN NULL` nie aktualizuje istniejącego
    constraintu — bez DROP-a prod zostałby z wąskim CHECK-iem z 0203 na zawsze."""
    src = MIGRATION.read_text("utf-8")
    assert "DROP CONSTRAINT IF EXISTS {name}" in src
    assert "ADD CONSTRAINT {name} {definition}" in src


def test_migration_downgrade_reclassifies_before_narrowing():
    """Zawężony CHECK odrzuciłby `in_progress`, więc wartość musi zniknąć
    z danych, ZANIM wróci wąski predykat (wzorzec 0212)."""
    src = MIGRATION.read_text("utf-8")
    downgrade = src[src.index("def downgrade()") :]
    reclassify = downgrade.index("SET contract_status = 'active'")
    narrow = downgrade.index("_STATUS_NARROW")
    assert reclassify < narrow, (
        "UPDATE reklasyfikujący in_progress musi wyprzedzać zawężenie CHECK-a"
    )


def test_backfill_guards_the_date_cast():
    """CI-sentinel (`scripts/verify_b2b_signature_migration.py`) sieje payload
    bez klucza `start_date`, a formularz umie zapisać pusty string. `::date` na
    jednym i drugim wywala CAŁY start kontenera, nie jeden wiersz."""
    for path in (MIGRATION, ENTRYPOINT):
        src = path.read_text("utf-8")
        assert "^[0-9]{4}-[0-9]{2}-[0-9]{2}$" in src, f"brak regex-guarda w {path.name}"
        assert "jsonb_typeof(render_payload) = 'object'" in src


def test_backfill_is_idempotent_in_both_places():
    """`_DATA_STATEMENTS` leci przy KAŻDYM starcie kontenera, więc bez
    `WHERE <kolumna> IS NULL` ręczna poprawka nazwy firmy byłaby cyklicznie
    nadpisywana starym payloadem."""
    for path in (MIGRATION, ENTRYPOINT):
        src = path.read_text("utf-8")
        for column in ("partner_legal_name", "partner_nip", "start_date"):
            assert f"WHERE {column} IS NULL" in src or f"{column} IS NULL" in src, (
                f"backfill {column} w {path.name} musi być idempotentny"
            )


def test_entrypoint_mirrors_every_new_column():
    entry = ENTRYPOINT.read_text("utf-8")
    for column in _SNAPSHOT_COLUMNS:
        assert f"ADD COLUMN IF NOT EXISTS {column}" in entry, (
            f"brak lustra kolumny {column} — na prodzie z osieroconym alembicem "
            "pierwszy GET /generated poleci UndefinedColumn"
        )


def test_entrypoint_mirrors_render_payload_the_backfill_reads():
    """Zaległość z 0132 domknięta w tym PR-ze: backfill w `_DATA_STATEMENTS`
    czyta `render_payload`, więc bez lustra tej kolumny spadłby milcząco do
    `backfill data skip: ... UndefinedColumn`."""
    entry = ENTRYPOINT.read_text("utf-8")
    assert "ADD COLUMN IF NOT EXISTS render_payload JSONB" in entry


def test_entrypoint_drops_rewritten_checks_before_adding_them():
    entry = ENTRYPOINT.read_text("utf-8")
    for name in (
        "ck_b2b_generated_contracts_contract_status",
        "ck_b2b_generated_contracts_closure_coherence",
    ):
        drop = f"DROP CONSTRAINT IF EXISTS {name}"
        assert drop in entry, f"brak DROP-a przed ADD dla {name}"
        assert entry.index(drop) < entry.rindex(f"ADD CONSTRAINT {name}")


def test_entrypoint_mirrors_the_widened_checks_and_entity_type_domain():
    entry = ENTRYPOINT.read_text("utf-8")
    assert "contract_status IN ('active', 'in_progress', 'closed')" in entry
    assert "contract_status IN ('active', 'in_progress')" in entry
    assert "ck_b2b_generated_contracts_partner_entity_type" in entry


def test_model_matches_the_migration():
    """`Base.metadata.create_all` w entrypoincie tworzy schemat z CHECK-ów ORM,
    nie z migracji — rozjazd oznacza, że świeża baza i CI mają inny constraint
    niż produkcja."""
    model = MODEL.read_text("utf-8")
    assert "contract_status IN ('active', 'in_progress', 'closed')" in model
    assert "contract_status IN ('active', 'in_progress')" in model
    assert "ck_b2b_generated_contracts_partner_entity_type" in model
    for column in _SNAPSHOT_COLUMNS:
        assert re.search(rf"^\s+{column}: Mapped", model, re.M), (
            f"kolumna {column} nie jest zadeklarowana w modelu"
        )


def test_model_keeps_active_as_the_column_default():
    """Default kolumny opisuje wiersz wstawiony BEZ decyzji o statusie (seed,
    safety-net, surowy INSERT). `in_progress` ustawia jawnie tylko handler
    `/render`; zmiana defaultu przepisałaby historię takich wierszy."""
    model = MODEL.read_text("utf-8")
    assert 'default="active", server_default="active"' in model
