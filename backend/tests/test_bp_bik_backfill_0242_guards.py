"""Bramki rewizji 0242 — poszerzenie domeny zdarzeń + trzy korekty danych.

Testy czytają PLIKI jako tekst (konwencja pozostałych testów migracji w tym
repo, patrz ``test_bik_backfill_0239_guards.py``): produkcyjny alembic bywa
osierocony, a i tak nie da się tu odpalić prawdziwego ``UPDATE`` bez pełnego
schematu.

Trzy klasy regresji, wszystkie CICHE na produkcji:

* **poszerzenie CHECK-a przez samo ``ADD``** — ``EXCEPTION WHEN duplicate_object``
  nie robi nic, gdy więz o tej nazwie już istnieje ze starą, węższą listą, czyli
  dokładnie wtedy, gdy poszerzenie jest potrzebne. Pierwszy zapis ``transfer_md``
  wywróciłby wtedy transakcję importu z Finansów;
* **migracja bez lustra w ``entrypoint.sh``** — prod ma ``alembic_version``
  osierocony, więc sama migracja jest tam no-opem, a deploy zostaje zielony;
* **marker zapisany mimo zera dopasowań** — jednorazowa korekta konsumuje swoją
  jedyną szansę, nic nie zmieniając (to jest dokładnie błąd, dla którego powstały
  bramki 0239).

Asymetria migracja/entrypoint jest ŚWIADOMA i też jest tu przybita: migracja ma
przerywać ``RAISE``-em, a lustro w ``entrypoint.sh`` NIE MOŻE — tam wyjątek
wywraca cały blok razem z markerem, a jedynym śladem jest linijka
„backfill data skip" w logu kontenera.
"""

from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = (
    BACKEND / "alembic" / "versions" / "0242_order_md_transfer_and_bp_bik_backfill.py"
)
ENTRYPOINT = BACKEND / "entrypoint.sh"
MODEL = BACKEND / "app" / "models" / "client_order_group.py"

MARKER = "0242_bp_bik_order_and_contract_backfill"


def _migration() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def _migration_messages() -> str:
    """Treść migracji ze sklejonymi sąsiednimi literałami.

    Komunikaty ``RAISE`` są w źródle łamane na kilka literałów, więc asercja na
    całe zdanie szukana w SUROWYM tekście pliku nie trafia — a wygląda to jak
    brak bramki, nie jak wada testu.
    """
    import re

    return re.sub(r"'\s*\n\s*'", "", _migration())


def _entrypoint() -> str:
    return ENTRYPOINT.read_text(encoding="utf-8")


# ── Poszerzenie domeny event_type ───────────────────────────────────────────


def test_event_type_is_widened_through_drop_not_only_add():
    """``ADD`` bez ``DROP`` przechodzi na zielono i nie zmienia nic."""
    sql = _migration()
    drop = sql.index("DROP CONSTRAINT IF EXISTS ck_client_order_group_events_type")
    add = sql.index("ADD CONSTRAINT ck_client_order_group_events_type")
    assert drop < add, "DROP musi poprzedzać ADD, inaczej stary, wąski CHECK zostaje"


def test_transfer_md_lands_in_migration_model_and_entrypoint():
    """Trzy lustra tej samej domeny — brak któregokolwiek = IntegrityError na prodzie."""
    assert "'transfer_md'" in _migration()
    assert "transfer_md" in MODEL.read_text(encoding="utf-8")
    assert "'transfer_md'" in _entrypoint()


def test_event_registry_matches_the_database_check():
    """Czwarte lustro tej samej domeny — rejestr w Pythonie.

    Do 0242 nic nie pilnowało zgodności ``EVENT_TYPES`` z CHECK-iem, więc typ
    dodany po jednej stronie mógł żyć miesiącami: zapis z wartością spoza
    CHECK-a wywraca transakcję na produkcji, a wartość bez etykiety renderuje
    się użytkownikowi surowym slugiem. Test czyta OBIE listy ze źródła, więc
    dopisanie typu tylko w jednym miejscu daje czerwień, a nie cichy dryf.
    """
    import re

    from app.models.client_order_group import ClientOrderGroupEvent
    from app.services.multi_consultant_orders import EVENT_TYPE_LABELS, EVENT_TYPES

    check = next(
        c
        for c in ClientOrderGroupEvent.__table_args__
        if getattr(c, "name", None) == "ck_client_order_group_events_type"
    )
    in_check = set(re.findall(r"'([a-z_]+)'", str(check.sqltext)))

    assert in_check == set(EVENT_TYPES), (
        "rejestr EVENT_TYPES rozjechał się z CHECK-iem w modelu: "
        f"tylko w CHECK={in_check - set(EVENT_TYPES)}, "
        f"tylko w EVENT_TYPES={set(EVENT_TYPES) - in_check}"
    )
    assert set(EVENT_TYPE_LABELS) == set(EVENT_TYPES), (
        "każdy typ zdarzenia musi mieć etykietę PL — bez niej historia "
        "pokaże surowy slug"
    )


def test_entrypoint_keeps_every_pre_existing_event_type():
    """Poszerzenie nie może po drodze zgubić wartości, które mają wiersze na prodzie."""
    entry = _entrypoint()
    for value in (
        "utworzenie",
        "dodanie_konsultanta",
        "import_md",
        "zamiana_kontraktora",
        "edycja_reczna",
        "zakonczenie",
        "przywrocenie",
        "wyczerpanie",
        "przedluzenie",
        "import_faktur",
    ):
        assert f"'{value}'" in entry, value


def test_downgrade_clears_rows_before_narrowing_the_domain():
    """Zwężenie CHECK-a przy istniejących wierszach odbiłoby się od własnych danych."""
    sql = _migration()
    delete = sql.index("DELETE FROM client_order_group_events")
    narrow = sql.rindex("ADD CONSTRAINT ck_client_order_group_events_type")
    assert delete < narrow


# ── Korekty danych: zero dopasowań musi być ROZSTRZYGNIĘTE ──────────────────


def test_migration_resolves_every_zero_match_instead_of_consuming_the_marker():
    """Każda z trzech korekt ma własne „a może już jest dobrze" i własny RAISE."""
    sql = _migration()
    # Osobne wyjątki — jeden wspólny nie odróżniłby, która korekta nie
    # rozpoznała kształtu danych.
    assert sql.count("RAISE EXCEPTION") >= 4
    assert sql.count("was NOT consumed") >= 4
    messages = _migration_messages()
    assert "is neither active-with-predecessor nor already scheduled" in messages
    assert "has no MD line that is either completed-with-budget-left" in messages
    assert "to repoint it to" in messages


def test_migration_stays_silent_when_there_is_simply_nothing_to_fix():
    """Świeża baza (CI, nowe środowisko) nie ma tych wierszy w ogóle.

    To NIE jest ten sam stan co „rozpoznaję cel, ale nie umiem go ruszyć".
    Mylenie ich wywraca `alembic upgrade heads` każdemu, kto stawia projekt od
    zera — zmierzone: pierwsza wersja tej migracji przerywała na pustej bazie.
    Każdy RAISE musi więc siedzieć pod warunkiem „sonda coś ZNALAZŁA".
    """
    sql = _migration()
    assert "IF probe_id IS NOT NULL THEN" in sql
    # Wariant odwrotny (`IS NULL` → RAISE) to dokładnie ta regresja.
    assert "IF probe_id IS NULL THEN" not in sql


def test_marker_key_is_identical_in_migration_and_entrypoint():
    """Rozjazd klucza = korekta wykonana DWA razy, raz z każdej strony."""
    assert MARKER in _migration()
    assert MARKER in _entrypoint()


def test_marker_short_circuits_before_any_write():
    for text in (_migration(), _entrypoint()):
        marker_at = text.index(f"'{MARKER}'")
        first_update = text.index("UPDATE client_order_groups", marker_at)
        assert marker_at < first_update


# ── Korekta 1: grupa → scheduled ────────────────────────────────────────────


def test_scheduling_a_group_also_sends_its_lines_back_to_draft():
    """Grupa ``scheduled`` z aktywnymi liniami to stan zabroniony w reszcie modułu.

    Materializator przy promocji sam ustawia ``draft → active`` i stempluje
    ``filled_at`` właściwą datą — linia zostawiona jako ``active`` nigdy jej
    nie dostanie, a do tego będzie liczona do ``active_consultants`` i do
    dopasowania importu MD.
    """
    for text in (_migration(), _entrypoint()):
        assert "SET status = 'scheduled'" in text
        assert "'draft'::clientorderstatus" in text
        assert "filled_at = NULL" in text


def test_group_is_matched_by_business_keys_not_by_bare_id():
    for text in (_migration(), _entrypoint()):
        assert "g.client_id = 18" in text
        assert "g.order_number = '4500029903'" in text
        assert "g.predecessor_group_id IS NOT NULL" in text


# ── Korekta 2: linia MD → active ────────────────────────────────────────────


def test_md_line_is_reactivated_only_when_the_budget_really_is_left():
    """Bez ``md_remaining > 0`` korekta wskrzesiłaby linię wyczerpaną, czyli
    poprawnie zamkniętą — a to jest stan, którego nowa reguła właśnie broni."""
    for text in (_migration(), _entrypoint()):
        assert "o.md_total IS NOT NULL" in text
        assert "o.md_remaining > 0" in text
        assert "g.order_number = '4500030067'" in text


# ── Korekta 3: przepięcie podpisanej umowy B2B ──────────────────────────────


def test_target_contract_is_confirmed_by_candidate_and_client_not_by_id():
    """Id 600 pochodzi ze zrzutu produkcji. Przepięcie PODPISANEJ umowy na
    wiersz wskazany samym id byłoby zakładem o to, że zrzut jest aktualny."""
    for text in (_migration(), _entrypoint()):
        assert "c.candidate_id = 154325" in text
        assert "c.client_id = 16" in text
        assert "c.status <> 'void'" in text
        assert "contract_id = target_contract_id" in text


def test_repointing_touches_only_the_signed_agreement_in_question():
    for text in (_migration(), _entrypoint()):
        assert "contract_number = '1476/2026'" in text
        assert "signature_status = 'signed_both'" in text
        # Bez tego powtórny start kontenera liczyłby 0 zmienionych wierszy
        # i (w migracji) uznał to za nierozpoznany kształt danych.
        assert "contract_id IS DISTINCT FROM target_contract_id" in text


def test_client_and_job_follow_the_contract_they_are_repointed_to():
    """Sam ``contract_id`` zostawiłby wiersz w połowie drogi: blocker patrzy na
    FK, a generator i replay podpisu na ``client_id``/``job_id``."""
    for text in (_migration(), _entrypoint()):
        assert "client_id = 16" in text
        assert "job_id = (" in text


# ── Asymetria migracja / entrypoint ─────────────────────────────────────────


def test_entrypoint_mirror_never_raises():
    """W ``_DATA_STATEMENTS`` wyjątek wywraca CAŁY blok razem z markerem, a log
    kontenera to jedna linijka „backfill data skip" przy zielonym ``/api/health``.
    Głośna asercja zamieniłaby się tam w cichą pętlę przy każdym starcie."""
    mirror_start = _entrypoint().index(f"'{MARKER}'")
    mirror = _entrypoint()[mirror_start : mirror_start + 6000]
    assert "RAISE EXCEPTION" not in mirror


def test_entrypoint_marker_insert_tolerates_a_concurrent_writer():
    entry = _entrypoint()
    at = entry.index(f"'{MARKER}'")
    assert "ON CONFLICT (key) DO NOTHING" in entry[at : at + 6000]


def test_energa_project_is_not_deleted_by_the_backfill():
    """Kasowanie kontraktu ciągnie kaskadę (dokumenty, aneksy, faktury, linie
    zamówień) i jest nieodwracalne. Po przepięciu umowy operator usuwa pusty
    projekt z interfejsu, widząc, co usuwa."""
    for text in (_migration(), _entrypoint()):
        assert "DELETE FROM contracts" not in text
