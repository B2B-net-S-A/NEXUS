"""Plan przeniesienia rekrutacji z Traffita — czysta logika (bez bazy).

Przypadki wzięte z pomiaru na produkcji 11.10.2026: 99,2% osób zgodnych,
a rozjazdy to remis czasu dwóch wpisów historii, brakujący wiersz i osoba
zdjęta z rekrutacji w Traffit.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.traffit_transfer_plan import (
    TIE_STEP,
    Insert,
    Promote,
    Remove,
    StageRow,
    plan_job,
    roster_is_trustworthy,
)

T0 = datetime(2026, 9, 24, 10, 58, tzinfo=timezone.utc)
NEW, SCREENING, SENT = "19", "23", "24"


def _row(row_id, candidate_id, emp, state, *, at=T0, source="traffit") -> StageRow:
    return StageRow(row_id, candidate_id, emp, source, state, at)


def test_same_state_needs_no_correction():
    plan = plan_job({"500": SCREENING}, [_row(1, 10, "500", SCREENING)], {})

    assert plan.matched == 1
    assert plan.corrections == 0
    assert plan.people_in_traffit == 1


def test_tied_timestamp_promotes_the_row_that_lost_the_tie():
    # Import czyta historię od najnowszych: „Screening” (nowszy wpis Traffita)
    # dostał niższe id niż „Nowy” z tej samej sekundy i przegrywa remis.
    rows = [_row(44616299, 10, "500", SCREENING), _row(44616300, 10, "500", NEW)]

    plan = plan_job({"500": SCREENING}, rows, {})

    assert plan.promotes == [Promote(10, 44616299, T0 + TIE_STEP)]
    assert plan.inserts == []
    assert plan.matched == 0


def test_missing_state_row_is_inserted_not_promoted():
    # Wiersz docelowego stanu istnieje, ale jest STARSZY niż bieżący — to nie
    # remis; przesunięcie go zmieniłoby datę dawnego zdarzenia.
    rows = [
        _row(1, 10, "500", SCREENING, at=T0 - timedelta(days=20)),
        _row(2, 10, "500", NEW, at=T0),
    ]

    plan = plan_job({"500": SCREENING}, rows, {})

    assert plan.promotes == []
    assert plan.inserts == [Insert(10, "500", SCREENING)]


def test_person_without_any_card_gets_a_row_when_nexus_knows_them():
    plan = plan_job({"500": NEW}, [], {"500": 17858})

    assert plan.inserts == [Insert(17858, "500", NEW)]
    assert plan.unknown_people == []


def test_person_nexus_does_not_know_is_reported_not_created():
    plan = plan_job({"500": NEW}, [], {})

    assert plan.unknown_people == ["500"]
    assert plan.corrections == 0


def test_person_removed_in_traffit_is_taken_off_the_board():
    rows = [_row(1, 10, "500", SCREENING), _row(2, 11, "501", NEW)]

    plan = plan_job({"500": SCREENING}, rows, {})

    assert plan.removes == [Remove(11, 2)]
    assert plan.matched == 1


def test_move_made_in_nexus_wins_over_traffit_state():
    rows = [
        _row(1, 10, "500", NEW),
        _row(2, 10, "500", None, at=T0 + timedelta(hours=1), source="manual"),
    ]

    plan = plan_job({"500": SCREENING}, rows, {})

    assert plan.nexus_on_top == 1
    assert plan.corrections == 0


def test_card_moved_in_nexus_is_not_removed_when_gone_from_traffit():
    rows = [
        _row(1, 10, "500", NEW),
        _row(2, 10, "500", None, at=T0 + timedelta(hours=1), source="manual"),
    ]

    plan = plan_job({}, rows, {})

    assert plan.removes == []
    assert plan.nexus_on_top == 1


def test_cards_added_in_nexus_are_left_alone():
    # Karta ze scrapera / dodana ręcznie: żadnego wiersza z Traffita.
    rows = [
        _row(1, 10, "500", None, source="manual"),
        _row(2, 11, None, None, source=None),
    ]

    plan = plan_job({}, rows, {})

    assert plan.nexus_only == 2
    assert plan.removes == []


def test_traffit_rows_of_candidate_without_traffit_number_are_not_removed():
    # Kandydat po scaleniu nie ma numeru osoby Traffita — nie da się sprawdzić,
    # czy nadal jest w rekrutacji, więc karta zostaje.
    plan = plan_job({}, [_row(1, 10, None, SCREENING)], {})

    assert plan.unverified == 1
    assert plan.removes == []


def test_candidate_present_under_another_traffit_number_is_not_duplicated():
    # Osoba 777 z Traffita mapuje się na kandydata 10, który ma już kartę jako
    # osoba 500 — dwie karty Traffita, jeden kandydat. Nie dokładamy wiersza.
    rows = [_row(1, 10, "500", SCREENING)]

    plan = plan_job({"500": SCREENING, "777": SENT}, rows, {"777": 10})

    assert plan.matched == 1
    assert plan.unverified == 1
    assert plan.inserts == []


def test_latest_row_follows_moved_at_then_id():
    rows = [
        _row(5, 10, "500", SENT, at=T0 - timedelta(days=1)),
        _row(3, 10, "500", SCREENING, at=T0),
    ]

    plan = plan_job({"500": SCREENING}, rows, {})

    assert plan.matched == 1


def test_roster_must_match_recruitment_headcount():
    people = {"500": NEW, "501": SCREENING}

    assert roster_is_trustworthy(people, 2)
    # Urwana odpowiedź jednego stanu wyglądałaby jak zdjęcie ludzi z rekrutacji.
    assert not roster_is_trustworthy(people, 3)
    assert not roster_is_trustworthy({}, None)


# ── Fala, bliźniaki, kolumny (moduł `traffit_transfer`, nadal bez bazy) ──────


def test_twin_is_a_nexus_recruitment_with_nearly_the_same_title():
    from app.services.traffit_transfer import find_twin

    nexus_jobs = [(1, "Java Developer"), (2, "Senior Data Engineer (Azure)")]

    assert find_twin("senior data engineer  (azure)", nexus_jobs) == 2
    assert find_twin("Senior Data Engineer (Azure) - Nordea", nexus_jobs) == 2
    # Ta sama rola to za mało — „Java Developer” i „Java Architect” to dwa requesty.
    assert find_twin("Java Architect", nexus_jobs) is None
    assert find_twin("Scrum Master", []) is None


def test_wave_key_identifies_the_same_wave_regardless_of_order():
    from app.services.traffit_transfer import Scope

    assert Scope(job_ids=(3, 1, 2)).key() == Scope(job_ids=(1, 2, 3)).key()
    assert Scope(client_id=7).key() != Scope(client_id=8).key()
    assert Scope(client_id=7).key() != Scope(client_id=7, active_days=14).key()
    # Próba bez bliźniaków nie autoryzuje wykonania z bliźniakami.
    assert Scope(client_id=7).key() != Scope(client_id=7, include_twins=True).key()


def test_columns_follow_the_board_rule_for_traffit_state_names():
    from app.services.traffit_transfer import StageDef, columns_after

    defs = {
        "19": StageDef(1, "Nowy", "new", "internal", None),
        "24": StageDef(2, "Wysłany do Klienta", "cv_sent", "external", None),
        "36": StageDef(3, "Interview - Prep", "interview", "internal", None),
        "41": StageDef(4, "NORDEA: Wysłać do Cpro", "screening", "internal", None),
        "21": StageDef(5, "Odrzucony", "rejected", "terminal", "rejected"),
    }
    people = {"1": "19", "2": "24", "3": "36", "4": "41", "5": "21", "6": "999"}

    assert columns_after(people, defs) == {
        "new": 1,
        "cv_sent": 1,
        "client_interview": 1,
        "cv_qc": 1,
        "closed": 1,
        "unknown": 1,
    }


def test_closed_card_of_a_person_removed_in_traffit_is_left_as_is():
    # Zatrudniony zdjęty z rekrutacji w Traffit nie może stać się „Wycofanym”.
    rows = [
        StageRow(1, 10, "500", "traffit", "20", T0, "hired"),
        StageRow(2, 11, "501", "traffit", "21", T0, "rejected"),
        StageRow(3, 12, "502", "traffit", SCREENING, T0, "screening"),
    ]

    plan = plan_job({"777": NEW}, rows, {})

    assert plan.already_closed == 2
    assert plan.removes == [Remove(12, 3)]


def test_empty_roster_is_never_trusted():
    # Brak nagłówka z licznikiem czyta się jako 0 — pusta lista zdjęłaby wszystkich.
    assert not roster_is_trustworthy({}, 0)
