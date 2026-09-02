"""Focused regressions for Finance organization-wide business reads."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from inspect import getsource
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import (
    candidate_stage_cv,
    candidates,
    client_order_groups,
    client_orders,
    job_shortlist,
    proposals,
    recruitment_access,
)
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.user import User, UserRole


def _user(role: UserRole) -> User:
    return User(
        id=1,
        email=f"{role.value}@example.com",
        name=role.value,
        role=role,
        roles=[role.value],
        is_active=True,
    )


def test_finance_recruitment_gets_use_read_scope_but_commands_keep_membership():
    history_source = getsource(candidates.get_candidate_history)
    assert history_source.count("job_read_scope_clause") == 2
    assert "job_scope_clause" not in history_source.replace("job_read_scope_clause", "")

    for endpoint in (
        job_shortlist.list_shortlist,
        proposals.get_latest_proposal,
        proposals.list_proposals,
    ):
        source = getsource(endpoint)
        assert "ensure_job_read_access" in source
        assert "await ensure_job_membership(" not in source

    for endpoint in (
        job_shortlist.add_to_shortlist,
        job_shortlist.update_shortlist_entry,
        job_shortlist.delete_shortlist_entry,
        job_shortlist.promote_shortlist_entry,
        proposals.regenerate_proposals,
    ):
        source = getsource(endpoint)
        assert "await ensure_job_membership(" in source
        assert "await ensure_job_read_access(" not in source


@pytest.mark.asyncio
async def test_job_read_access_bypasses_membership_only_for_finance(monkeypatch):
    calls = []

    async def membership(db, user, job_id, *, oversight_bypass=True):
        calls.append((user.role, job_id, oversight_bypass))

    monkeypatch.setattr(recruitment_access, "ensure_job_membership", membership)

    await recruitment_access.ensure_job_read_access(
        SimpleNamespace(), _user(UserRole.finance), 41
    )
    assert calls == []

    await recruitment_access.ensure_job_read_access(
        SimpleNamespace(), _user(UserRole.recruiter), 42
    )
    assert calls == [(UserRole.recruiter, 42, True)]


def test_stage_cv_gets_opt_into_read_access_and_commands_do_not():
    for endpoint in (
        candidate_stage_cv.get_original_cv,
        candidate_stage_cv.download_original_cv,
        candidate_stage_cv.get_branded_cv,
        candidate_stage_cv.render_branded_cv_for_print,
        candidate_stage_cv.list_cv_share_tokens,
    ):
        assert "read_access=True" in getsource(endpoint)

    for endpoint in (
        candidate_stage_cv.update_branded_cv,
        candidate_stage_cv.finalize_branded_cv,
        candidate_stage_cv.create_cv_share_token,
        candidate_stage_cv.revoke_all_cv_share_tokens,
    ):
        assert "read_access=True" not in getsource(endpoint)

    assert "ensure_job_membership" in getsource(
        candidate_stage_cv.revoke_cv_share_token
    )


@pytest.mark.asyncio
async def test_finance_branded_cv_lazy_preview_does_not_persist(monkeypatch):
    csv = CandidateStageCV(
        id=31,
        candidate_stage_id=17,
        candidate_id=8,
        job_id=4,
        branded_status="none",
    )

    async def load_csv(db, stage_id, user, *, read_access=False):
        assert stage_id == 17
        assert read_access is True
        return csv

    async def load_candidate_and_job(db, loaded_csv):
        assert loaded_csv is csv
        return SimpleNamespace(name="Jan", lastname="Kowalski"), None

    class RecordingDb:
        def __init__(self):
            self.added = []
            self.commits = 0
            self.refreshes = 0

        def add(self, value):
            self.added.append(value)

        async def commit(self):
            self.commits += 1

        async def refresh(self, value):
            self.refreshes += 1

    db = RecordingDb()
    monkeypatch.setattr(candidate_stage_cv, "_load_csv_for_stage", load_csv)
    monkeypatch.setattr(
        candidate_stage_cv, "_load_candidate_and_job", load_candidate_and_job
    )
    monkeypatch.setattr(
        candidate_stage_cv,
        "_generate_cv_html",
        lambda candidate, template, language, job: "<p>transient</p>",
    )

    response = await candidate_stage_cv.get_branded_cv(
        stage_id=17,
        current_user=_user(UserRole.finance),
        db=db,
    )

    assert response.status == "draft"
    assert response.content_html == "<p>transient</p>"
    assert response.rendered_from_default is True
    assert csv.branded_status == "none"
    assert csv.branded_draft_html is None
    assert db.added == []
    assert db.commits == 0
    assert db.refreshes == 0


@pytest.mark.asyncio
async def test_finance_can_export_requested_standalone_order_ids(monkeypatch):
    # Eksport bierze wyłącznie zamówienia OBOWIĄZUJĄCE w dniu pobrania (jeden
    # wiersz na konsultanta), więc atrapa musi nieść status i okres obejmujący
    # dziś — inaczej test sprawdzałby wyłącznie pusty arkusz.
    today = date.today()
    order = SimpleNamespace(
        id=7,
        title="PO-7",
        status="active",
        rate_candidate=None,
        rate_client=Decimal("150"),
        start_date=today - timedelta(days=30),
        end_date=today + timedelta(days=30),
        order_type="md",
    )
    contractor = SimpleNamespace(
        contract_id=77,
        candidate_name="Jan Kowalski",
        rate_candidate=Decimal("100"),
        orders=[order],
    )
    calls = []

    async def assert_client(db, client_id):
        return SimpleNamespace(id=client_id)

    async def list_orders(client_id, user, db):
        calls.append((client_id, user.role))
        return SimpleNamespace(contractors=[contractor])

    async def run_in_threadpool(function, *args, **kwargs):
        return b"workbook"

    monkeypatch.setattr(client_orders, "_assert_client", assert_client)
    monkeypatch.setattr(client_orders, "list_contractors_with_orders", list_orders)
    monkeypatch.setattr(client_orders, "run_in_threadpool", run_in_threadpool)
    monkeypatch.setattr(
        client_orders, "effective_standalone_order_type", lambda client_id, value: value
    )
    monkeypatch.setattr(client_orders, "client_display_name", lambda client: "Client")

    response = await client_orders.export_client_orders(
        client_id=5,
        payload=client_orders.ClientOrderExportRequest(order_ids=[7]),
        user=_user(UserRole.finance),
        db=SimpleNamespace(),
    )

    assert response.body == b"workbook"
    assert calls == [(5, UserRole.finance)]


@pytest.mark.asyncio
async def test_consultant_options_preserve_dl_scope_and_add_finance():
    class AssignedResult:
        def scalar_one_or_none(self):
            return object()

    class AssignedDb:
        async def execute(self, statement):
            return AssignedResult()

    finance = _user(UserRole.finance)
    assert (
        await client_order_groups.require_consultant_options_reader(
            client_id=5, current_user=finance, db=SimpleNamespace()
        )
        is finance
    )

    admin = _user(UserRole.admin)
    assert (
        await client_order_groups.require_consultant_options_reader(
            client_id=5, current_user=admin, db=SimpleNamespace()
        )
        is admin
    )

    delivery_lead = _user(UserRole.delivery_lead)
    assert (
        await client_order_groups.require_consultant_options_reader(
            client_id=5, current_user=delivery_lead, db=AssignedDb()
        )
        is delivery_lead
    )

    class UnassignedResult:
        def scalar_one_or_none(self):
            return None

    class UnassignedDb:
        async def execute(self, statement):
            return UnassignedResult()

    with pytest.raises(HTTPException) as exc_info:
        await client_order_groups.require_consultant_options_reader(
            client_id=5,
            current_user=delivery_lead,
            db=UnassignedDb(),
        )
    assert exc_info.value.status_code == 403

    for role in (
        UserRole.head_of_recruitment,
        UserRole.tac,
        UserRole.recruiter,
        UserRole.sourcer,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await client_order_groups.require_consultant_options_reader(
                client_id=5,
                current_user=_user(role),
                db=SimpleNamespace(),
            )
        assert exc_info.value.status_code == 403
