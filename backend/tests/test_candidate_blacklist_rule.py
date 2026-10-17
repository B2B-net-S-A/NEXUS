"""Okno „Czarna lista…” — część czysta, bez bazy (17.10.2026).

Trasy na żywej bazie sprawdza ``test_candidate_blacklist_api.py`` (CI).
Imiona są wymyślone (repo jest publiczne).
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.candidate_blacklist import BlacklistAdd, BlacklistRemove
from app.models.candidate import CandidateStatus
from app.models.user import UserRole
from app.services.candidate_blacklist import (
    REMOVER_ROLES,
    blacklist_info,
    clear_blacklist,
    mark_blacklisted,
)

AT = datetime(2026, 10, 17, 9, 30, tzinfo=timezone.utc)


def _candidate(status=CandidateStatus.active, **fields):
    return SimpleNamespace(
        status=status,
        blacklisted_at=fields.get("at"),
        blacklisted_by_user_id=fields.get("by"),
        blacklist_reason=fields.get("reason"),
    )


def test_mark_and_clear_keep_status_and_columns_together():
    candidate = _candidate()

    mark_blacklisted(candidate, user_id=7, reason="Zrezygnował przed startem", at=AT)

    assert candidate.status == CandidateStatus.blacklisted
    assert (
        candidate.blacklisted_at,
        candidate.blacklisted_by_user_id,
        candidate.blacklist_reason,
    ) == (AT, 7, "Zrezygnował przed startem")

    clear_blacklist(candidate)

    assert candidate.status == CandidateStatus.active
    assert (
        candidate.blacklisted_at,
        candidate.blacklisted_by_user_id,
        candidate.blacklist_reason,
    ) == (None, None, None)


def test_info_only_for_a_blacklisted_person():
    assert blacklist_info(_candidate()) is None

    info = blacklist_info(
        _candidate(CandidateStatus.blacklisted, at=AT, by=7, reason="Powód"),
        "Ewa Przykładowa",
    )

    assert (info.since, info.by_user_id, info.by_name, info.reason) == (
        AT,
        7,
        "Ewa Przykładowa",
        "Powód",
    )


def test_entry_from_before_the_window_has_no_details():
    """37 osób z dopisków Traffita: zablokowane, bez powodu i autora."""
    info = blacklist_info(_candidate(CandidateStatus.blacklisted))

    assert info is not None
    assert (info.since, info.by_user_id, info.by_name, info.reason) == (
        None,
        None,
        None,
        None,
    )


def test_reason_is_trimmed_and_required():
    body = BlacklistAdd(scope="global", reason="  Kłamał o doświadczeniu  ")
    assert body.reason == "Kłamał o doświadczeniu"

    for reason in ("", "   ", "abc", "  abcd "):
        with pytest.raises(ValidationError):
            BlacklistAdd(scope="global", reason=reason)
        with pytest.raises(ValidationError):
            BlacklistRemove(reason=reason)

    with pytest.raises(ValidationError):
        BlacklistAdd(scope="global", reason="x" * 2001)


def test_client_scope_needs_a_client():
    with pytest.raises(ValidationError):
        BlacklistAdd(scope="client", reason="Klient prosił po rozmowie")

    body = BlacklistAdd(scope="client", client_id=5, reason="Klient prosił")
    assert (body.scope, body.client_id) == ("client", 5)

    with pytest.raises(ValidationError):
        BlacklistAdd(scope="everywhere", reason="Nieznany zakres")


def test_only_leads_and_admins_remove_the_global_blacklist():
    assert set(REMOVER_ROLES) == {
        UserRole.admin,
        UserRole.delivery_lead,
        UserRole.head_of_recruitment,
    }
    assert UserRole.recruiter not in REMOVER_ROLES
