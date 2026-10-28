"""Zamknięcie rekrutacji daje znać rekruterom osób, które czekają (28.10.2026).

Czyste reguły bez bazy: kto jest osobą karty, które kolumny się liczą, kogo
pomijamy i co mówi dzwonek. Trasy (409 z listą, dzwonek po zamknięciu, brak
dzwonka przy automacie) — ``test_job_close.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.models.recruitment_pipeline import PipelineStage
from app.services.job_closed_notices import (
    Recipient,
    WaitingPerson,
    group_recipients,
    notice_text,
    recipients_payload,
    waiting_cards,
)

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
_ids = iter(range(1, 10_000))


def _row(candidate_id, stage, moved_by, minutes, *, name=None, approved_at=None):
    return SimpleNamespace(
        id=next(_ids),
        candidate_id=candidate_id,
        stage=PipelineStage(stage),
        moved_by=moved_by,
        moved_at=T0 + timedelta(minutes=minutes),
        approved_at=approved_at,
        stage_name=name,
        stage_category=None,
        stage_terminal_type=None,
    )


def test_card_person_is_the_first_verifier_not_the_mover():
    """Rekruter 7 zweryfikował, DL 2 przesunął do „CV wysłane”."""
    rows = [
        _row(1, "new", 7, 0),
        _row(1, "verified", 7, 10),
        _row(1, "cv_sent", 2, 20),
    ]
    cards = waiting_cards(rows)
    assert [(c.candidate_id, c.user_id, c.column) for c in cards] == [(1, 7, "cv_sent")]


def test_dl_returning_the_card_does_not_steal_it():
    """Cofnięcie z „QC CV” przez DL-a to nowy wiersz „Zweryfikowany” — karta
    zostaje przy pierwszym weryfikującym (21.10.2026)."""
    rows = [
        _row(1, "verified", 7, 0),
        _row(1, "verified", 2, 30),
        _row(1, "client_interview", 2, 60),
    ]
    assert waiting_cards(rows)[0].user_id == 7


def test_assigned_owner_wins_over_the_verifier():
    """„Prowadzi” (25.10.2026): przypisana osoba prowadzi kandydata wszędzie."""
    rows = [_row(1, "verified", 7, 0), _row(1, "cv_sent", 2, 10)]
    assert waiting_cards(rows, {1: 11})[0].user_id == 11
    assert waiting_cards(rows, {99: 11})[0].user_id == 7


def test_card_without_verification_belongs_to_whoever_added_it():
    rows = [_row(1, "new", 5, 0), _row(1, "cv_sent", 2, 10)]
    assert waiting_cards(rows)[0].user_id == 5


def test_only_cv_sent_and_further_columns_count():
    rows = [
        _row(1, "new", 7, 0),
        _row(2, "screening", 7, 0),
        _row(3, "verified", 7, 0),
        _row(4, "cv_sent", 7, 0),
        _row(5, "client_interview", 7, 0),
        _row(6, "negotiation", 7, 0),
        _row(7, "cv_sent", 7, 0),
        _row(7, "rejected", 7, 5),
        _row(8, "hired", 7, 0),
    ]
    assert sorted(c.candidate_id for c in waiting_cards(rows)) == [4, 5, 6]


def test_qc_cv_card_waits_with_us_not_with_the_client():
    """Karta w „QC CV” (etap po nazwie) jeszcze nie poszła do klienta."""
    rows = [_row(1, "verified", 7, 0), _row(1, "interview", 7, 5, name="QC CV")]
    assert waiting_cards(rows) == []


def test_latest_row_is_the_card_regardless_of_input_order():
    rows = [_row(1, "rejected", 7, 50), _row(1, "cv_sent", 7, 10)]
    assert waiting_cards(list(reversed(rows))) == []


def test_import_without_author_has_nobody_to_tell():
    assert waiting_cards([_row(1, "cv_sent", None, 0)]) == []


def _cards():
    return waiting_cards(
        [
            _row(1, "cv_sent", 7, 0),
            _row(2, "client_interview", 7, 0),
            _row(3, "cv_sent", 8, 0),
            _row(4, "cv_sent", 9, 0),
        ]
    )


def test_actor_and_inactive_accounts_are_skipped():
    recipients = group_recipients(
        _cards(),
        # 9 nieaktywne — nie ma go w nazwach aktywnych kont.
        user_names={7: "Rekruterka A", 8: "Rekruterka B"},
        candidate_names={1: "Osoba X", 2: "Osoba Y", 3: "Osoba Z"},
        exclude_user_id=8,
    )
    assert [(r.user_id, [p.candidate_id for p in r.people]) for r in recipients] == [
        (7, [1, 2])
    ]


def test_recipients_sorted_by_people_and_payload_counts_columns():
    recipients = group_recipients(
        _cards(),
        user_names={7: "Rekruterka A", 8: "Rekruterka B", 9: "Rekruter C"},
        candidate_names={},
        exclude_user_id=None,
    )
    assert [r.user_id for r in recipients] == [7, 9, 8]
    assert recipients_payload(recipients)[0] == {
        "user_id": 7,
        "name": "Rekruterka A",
        "people": 2,
        "columns": {"cv_sent": 1, "client_interview": 1},
    }


def _recipient(count: int) -> Recipient:
    return Recipient(
        7,
        "Rekruterka A",
        tuple(WaitingPerson(i, f"Osoba {i}", "cv_sent") for i in range(count)),
    )


def test_notice_names_the_job_reason_and_people():
    title, message = notice_text(
        _recipient(2),
        job_title="Kierownik projektu",
        client_name="Klient K",
        actor_name="Delivery Lead D",
        reason="competitor",
    )
    assert title == "Rekrutacja zamknięta — daj znać 2 osobom"
    assert message.startswith("Kierownik projektu · Klient K. ")
    assert (
        "Zamknięcie: Delivery Lead D, powód: Klient wybrał kandydata innej firmy."
        in message
    )
    assert "Osoba 0 (CV wysłane), Osoba 1 (CV wysłane)" in message


def test_notice_without_reason_and_with_one_person():
    title, message = notice_text(
        _recipient(1),
        job_title="Tester",
        client_name=None,
        actor_name=None,
        reason=None,
    )
    assert title == "Rekrutacja zamknięta — daj znać 1 osobie"
    assert message.startswith("Tester. Zamknięcie. Twoje osoby")


def test_notice_caps_the_list_of_names():
    _, message = notice_text(
        _recipient(11),
        job_title="Java",
        client_name="Klient K",
        actor_name="DL",
        reason="budget",
    )
    assert "Osoba 7 (CV wysłane) i 3 innych" in message
    assert "Osoba 8" not in message
