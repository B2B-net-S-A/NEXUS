"""R9-N1-2: dziennik kandydata w „podglądzie jako” zapisuje prawdziwego sprawcę.

`record_candidate_audit` dostaje od wołającego `current_user.id`, czyli w
podglądzie osobę PODGLĄDANĄ. Pobranie CV albo eksport wykonuje jednak admin —
jego konto stempluje w sesji `deps.get_authenticated_user` (`stamp_actor`).
"""

from __future__ import annotations

from app.services import candidate_audit
from app.services.order_change_audit import ACTOR_INFO_KEY, stamp_actor


class _Session:
    def __init__(self) -> None:
        self.info: dict = {}
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)


def test_preview_records_real_actor_and_viewed_user() -> None:
    db = _Session()
    stamp_actor(db.info, 7)  # admin z tokenu

    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.CV_DOWNLOADED,
        user_id=42,  # osoba podglądana (current_user)
        entity_id=5,
        details={"format": "pdf"},
    )

    (row,) = db.added
    assert row.user_id == 7
    assert row.details == {"format": "pdf", "viewed_as_user_id": 42}


def test_own_request_keeps_user_and_details_untouched() -> None:
    db = _Session()
    stamp_actor(db.info, 42)
    details = {"format": "xlsx"}

    candidate_audit.record_candidate_audit(
        db, action=candidate_audit.EXPORT_REQUESTED, user_id=42, details=details
    )

    (row,) = db.added
    assert row.user_id == 42
    assert row.details == {"format": "xlsx"}
    assert details == {"format": "xlsx"}  # słownik wołającego nietknięty


def test_background_session_without_actor_keeps_given_user() -> None:
    db = _Session()
    assert ACTOR_INFO_KEY not in db.info

    candidate_audit.record_candidate_audit(
        db, action=candidate_audit.NOTES_FACT_APPLIED, user_id=None, entity_id=3
    )
    candidate_audit.record_candidate_audit(
        db, action=candidate_audit.NOTES_FACT_APPLIED, user_id=9, entity_id=3
    )

    assert [row.user_id for row in db.added] == [None, 9]
    assert all("viewed_as_user_id" not in row.details for row in db.added)
