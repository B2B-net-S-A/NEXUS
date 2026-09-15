"""Rekrutacje technicznego klienta nie trafiają do rejestru ani dashboardów (UAT B73).

Import Traffita zakłada ukrytego klienta `__traffit_orphans` na rekrutacje bez
klienta. Ukrycie działało tylko na listach klientów — rejestr rekrutacji,
dashboard procesów i dashboard Delivery pokazywały jego rekrutacje jak zwykłą,
aktywną pracę.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.api.jobs import jobs_register_base_clause
from app.models.job import Job
from app.services import recruitment_operations as operations
from app.services.client_identity import job_client_listed_clause

pytestmark = pytest.mark.unit


def _sql(*conditions) -> str:
    statement = select(Job.id).where(*conditions)
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def test_listed_clause_excludes_hidden_and_deleted_clients_but_not_archived():
    sql = _sql(job_client_listed_clause(Job.client_id))
    assert "EXISTS" in sql
    assert "clients.id = jobs.client_id" in sql
    assert "clients.hidden IS false" in sql
    assert "clients.deleted_at IS NULL" in sql
    assert "archived_at" not in sql


def test_job_register_uses_the_listed_client_clause():
    assert "clients.hidden IS false" in _sql(jobs_register_base_clause())


def test_recruitment_operations_skip_hidden_client_jobs():
    scope = operations._RecruitmentOperationsScope(preset="finance")
    filters = operations._job_filters(SimpleNamespace(id=1), scope=scope)
    assert "clients.hidden IS false" in _sql(*filters)


def test_clause_keeps_its_own_client_row_when_outer_query_joins_clients():
    from app.models.client import Client

    statement = (
        select(Job.id)
        .join(Client, Client.id == Job.client_id)
        .where(job_client_listed_clause(Job.client_id))
    )
    sql = " ".join(str(statement.compile(dialect=postgresql.dialect())).split())
    assert "EXISTS (SELECT clients.id FROM clients WHERE" in sql
