"""Kontrakt migracji 0226: status „Zawieszona" + dziennik zmian statusu.

Prod alembic bywa osierocony (`entrypoint.sh` toleruje porażkę `upgrade heads`),
więc KAŻDA zmiana schematu musi mieć lustro w `entrypoint.sh` albo po cichu nigdy
nie dociera na produkcję — a deploy zostaje zielony, bo smoke-test puka wyłącznie
w `/api/health`.

Ten plik pilnuje rzeczy, których nie złapie test funkcjonalny na świeżej bazie:
CI stawia schemat z migracji, więc rozjazd między migracją a lustrem jest tam
niewidoczny z definicji.
"""

from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

MIGRATION = BACKEND / "alembic/versions/0226_b2b_generated_contract_suspended.py"
MODEL = BACKEND / "app/models/b2b_generated_contract.py"
EVENT_MODEL = BACKEND / "app/models/b2b_generated_contract_status_event.py"
ENTRYPOINT = BACKEND / "entrypoint.sh"
MAIN = BACKEND / "app/main.py"

_NEW_REASONS = (
    "no_client_budget",
    "contractor_found_other_project",
    "contractor_health_reasons",
    "contractor_underperformance",
    "project_completed",
    "internalization",
)
_LEGACY_REASONS = ("resignation_before_signing", "termination", "mutual_agreement")


def test_migration_chains_onto_the_single_head():
    """Jedna głowa alembica jest bramką CI (`test_analytics_release_gates`)."""
    src = MIGRATION.read_text("utf-8")
    assert 'revision = "0226_b2b_generated_contract_suspended"' in src
    assert 'down_revision = "0225_contract_survives_candidate_delete"' in src


def test_migration_widens_status_before_coherence_references_it():
    """Kolejność nie jest kosmetyczna.

    `ck_..._closure_coherence` odwołuje się do `suspended`; gdyby poszła przed
    poszerzeniem domeny statusu, w bazie istniałaby chwila, w której constraint
    dopuszcza wartość, której druga reguła jeszcze odrzuca.
    """
    src = MIGRATION.read_text("utf-8")
    upgrade = src[src.index("def upgrade()") :]
    status_at = upgrade.index("_STATUS_WIDE")
    coherence_at = upgrade.index("_COHERENCE_WIDE")
    assert status_at < coherence_at


def test_legacy_closure_reasons_survive_in_every_layer():
    """Produkcja ma wiersze `closed` niosące katalog sprzed 0226.

    Zawężenie domeny wywaliłoby `ADD CONSTRAINT` na skanie tabeli, a gdyby nawet
    przeszło — historyczny powód zamieniłby się w puste miejsce. CHECK jest tu
    domeną dopuszczalnych wartości, nie listą podpowiedzi w UI.
    """
    schema = (BACKEND / "app/schemas/b2b_contract_generator.py").read_text("utf-8")
    for layer in (MIGRATION, MODEL, ENTRYPOINT):
        src = layer.read_text("utf-8")
        for reason in _LEGACY_REASONS + _NEW_REASONS:
            assert reason in src, f"brak {reason} w {layer.name}"
    for reason in _LEGACY_REASONS + _NEW_REASONS:
        assert reason in schema


def test_selectable_catalog_excludes_legacy_reasons():
    """Legacy zostaje do ODCZYTU, ale nie wolno go już wybrać w formularzu."""
    from app.schemas.b2b_contract_generator import (
        B2B_SELECTABLE_CLOSURE_REASONS,
    )

    assert set(B2B_SELECTABLE_CLOSURE_REASONS) == set(_NEW_REASONS) | {"other"}
    assert not set(B2B_SELECTABLE_CLOSURE_REASONS) & set(_LEGACY_REASONS)


def test_coherence_treats_suspended_like_closed():
    """„Zawieszona" bez daty i powodu byłaby wierszem, który nie odpowiada na
    pytanie, po co ten status w ogóle powstał."""
    for layer in (MIGRATION, MODEL, ENTRYPOINT):
        src = layer.read_text("utf-8")
        assert "contract_status IN ('closed', 'suspended')" in src, (
            f"{layer.name}: gałąź wymagająca powodu i daty musi objąć suspended"
        )


def test_migration_drops_before_adding_each_rewritten_check():
    """`EXCEPTION WHEN duplicate_object THEN NULL` nie aktualizuje istniejącego
    constraintu — bez DROP-a prod zostałby z węższym CHECK-iem na zawsze."""
    src = MIGRATION.read_text("utf-8")
    assert "DROP CONSTRAINT IF EXISTS {name}" in src
    assert "ADD CONSTRAINT {name} {definition}" in src


def test_entrypoint_drops_the_closure_reason_check_before_adding_it():
    """Zaległość domknięta w 0226: ten wpis miał dotąd WYŁĄCZNIE
    `EXCEPTION WHEN duplicate_object`, więc poszerzenie katalogu nigdy nie
    zadziałałoby na produkcji — stary constraint zostałby nietknięty, a pierwsze
    zamknięcie umowy nowym powodem poleciałoby CheckViolation."""
    entry = ENTRYPOINT.read_text("utf-8")
    name = "ck_b2b_generated_contracts_closure_reason"
    drop = f"DROP CONSTRAINT IF EXISTS {name}"
    assert drop in entry
    assert entry.index(drop) < entry.rindex(f"ADD CONSTRAINT {name}")


def test_entrypoint_creates_the_events_table_itself():
    """`Base.metadata.create_all` NIE wystarcza: ten blok jest jedną transakcją
    i na produkcji potrafi paść w całości przez jedną złą tabelę (incydent
    Cortex, PR #664), zostawiając UndefinedTable na żywym endpointcie."""
    entry = ENTRYPOINT.read_text("utf-8")
    assert "CREATE TABLE IF NOT EXISTS b2b_generated_contract_status_events" in entry
    assert "ix_b2b_gc_status_events_contract" in entry


def test_events_table_cascades_on_delete():
    """`DELETE /generated/{id}` istnieje i zwalnia numer umowy do ponownego
    użycia — RESTRICT zamieniłby dziennik w blokadę tej operacji."""
    for layer in (MIGRATION, ENTRYPOINT):
        src = layer.read_text("utf-8")
        assert "b2b_generated_contracts (id) ON DELETE CASCADE" in src
    assert 'ondelete="CASCADE"' in EVENT_MODEL.read_text("utf-8")


def test_deep_health_probe_covers_the_new_table():
    """Bramka deployu wykrywa dryf, safety-net go leczy — komplementarne.
    Bez wpisu w `core_checks` brak tabeli na prodzie przechodzi jako zielony
    deploy i wychodzi dopiero przy pierwszym otwarciu historii statusów."""
    main = MAIN.read_text("utf-8")
    assert '"b2b_generated_contract_status_events"' in main


def test_downgrade_reclassifies_before_narrowing():
    """Zawężone CHECK-i odrzuciłyby istniejące dane, więc wartości spoza starych
    domen muszą zniknąć, ZANIM wrócą wąskie predykaty (wzorzec 0212/0224)."""
    src = MIGRATION.read_text("utf-8")
    downgrade = src[src.index("def downgrade()") :]
    reclassify_status = downgrade.index("SET contract_status = 'closed'")
    reclassify_reason = downgrade.index("closure_reason = 'other'")
    narrow = downgrade.index("_COHERENCE_NARROW")
    assert reclassify_status < narrow
    assert reclassify_reason < narrow
