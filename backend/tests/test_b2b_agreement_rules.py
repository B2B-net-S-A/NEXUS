"""Czyste reguły „umowy w rekrutacji” (04.10.2026) — bez bazy.

Powody spraw w grupie „Umowy” (``agreement_tasks.classify``), kto poprawia
umowę pod tym samym numerem (``_may_correct_generated``) i lustro migracji
0417 w ``entrypoint.sh`` (prod alembic bywa osierocony).
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api.b2b_contract_generator import _may_correct_generated
from app.models.notification import NotificationType
from app.models.user import UserRole
from app.services.agreement_tasks import (
    REASON_CLOSED_SIGNED_ACTIVE,
    REASON_CLOSED_UNSIGNED,
    REASON_HIRED_UNSIGNED,
    REASON_REQUESTED,
    classify,
)
from app.services.notification_access import NOTIFICATION_SECTION_BY_TYPE
from app.services.notification_categories import CATEGORY_BY_TYPE

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            dict(
                signature_status="unsigned",
                contract_status="in_progress",
                contract_live=False,
                requested=True,
                column="new",
            ),
            REASON_REQUESTED,
        ),
        (
            dict(
                signature_status="unsigned",
                contract_status="in_progress",
                contract_live=False,
                requested=False,
                column="new",
            ),
            None,
        ),
        # „Zatrudniony” wygrywa z prośbą — to już rozjazd, nie tylko prośba.
        (
            dict(
                signature_status="unsigned",
                contract_status="in_progress",
                contract_live=False,
                requested=True,
                column="hired",
            ),
            REASON_HIRED_UNSIGNED,
        ),
        (
            dict(
                signature_status="unsigned",
                contract_status="in_progress",
                contract_live=False,
                requested=False,
                column="closed",
            ),
            REASON_CLOSED_UNSIGNED,
        ),
        (
            dict(
                signature_status="signed_both",
                contract_status="active",
                contract_live=True,
                requested=False,
                column="closed",
            ),
            REASON_CLOSED_SIGNED_ACTIVE,
        ),
        # Podpisana i pracuje — nic do zrobienia.
        (
            dict(
                signature_status="signed_both",
                contract_status="active",
                contract_live=True,
                requested=False,
                column="hired",
            ),
            None,
        ),
        # Kontrakt już zakończony — zamknięta karta niczego nie wymaga.
        (
            dict(
                signature_status="signed_both",
                contract_status="active",
                contract_live=False,
                requested=False,
                column="closed",
            ),
            None,
        ),
        # Anulowana umowa nie jest sprawą.
        (
            dict(
                signature_status="unsigned",
                contract_status="cancelled",
                contract_live=False,
                requested=True,
                column="hired",
            ),
            None,
        ),
    ],
)
def test_classify(kwargs: dict, expected: str | None) -> None:
    assert classify(**kwargs) == expected


def _user(uid: int, *roles: UserRole) -> SimpleNamespace:
    return SimpleNamespace(
        id=uid,
        has_any_role=lambda *wanted: any(r in roles for r in wanted),
    )


def _row(created_by: int | None, job_id: int | None = 7) -> SimpleNamespace:
    return SimpleNamespace(created_by=created_by, job_id=job_id)


def test_who_may_correct() -> None:
    recruiter = _user(1, UserRole.recruiter)
    assert _may_correct_generated(recruiter, _row(created_by=1), set())
    assert not _may_correct_generated(recruiter, _row(created_by=2), set())
    assert _may_correct_generated(recruiter, _row(created_by=2), {7})
    assert not _may_correct_generated(recruiter, _row(created_by=2, job_id=None), {7})
    tcm = _user(3, UserRole.talent_community_manager)
    assert _may_correct_generated(tcm, _row(created_by=2), set())
    admin = _user(4, UserRole.admin)
    assert _may_correct_generated(admin, _row(created_by=None, job_id=None), set())


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_migration_0417_is_mirrored_in_entrypoint() -> None:
    ns: dict = {}
    source = (ROOT / "alembic/versions/0417_b2b_signature_request.py").read_text()
    exec(compile(source.replace("from alembic import op", ""), "m", "exec"), ns)
    entry = _squash((ROOT / "entrypoint.sh").read_text())
    for statement in ns["COLUMNS"]:
        assert _squash(statement).replace('"', "") in entry.replace('" "', "").replace(
            '"', ""
        ), statement
    assert ns["ENUM"] in entry


def test_signature_request_bell_is_a_mandatory_pipeline_task() -> None:
    kind = NotificationType.b2b_signature_requested
    assert NOTIFICATION_SECTION_BY_TYPE[kind].value == "pipeline"
    assert CATEGORY_BY_TYPE[kind].value == "mentions"
