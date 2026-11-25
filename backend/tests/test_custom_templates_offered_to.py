"""Wzór „dla wybranych klientów”: podgląd i prefill też pilnują listy klientów.

Przegląd bezpieczeństwa 25.11: ``preview`` i ``prefill`` sprawdzały tylko, czy
wzór jest zatwierdzony — HTML wzoru jednego klienta i dane kandydata z
rekrutacji innego klienta szły do każdego z dostępem do Generatora. Bez bazy:
zależności tras są podmienione, sprawdzamy samą decyzję.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import custom_document_templates as api

ALLOWED, OTHER = 11, 22


def _version(scope: str = "selected"):
    return SimpleNamespace(
        client_scope=scope, client_ids=[ALLOWED], docx=b"", fields=[], id=1
    )


@pytest.fixture
def routes(monkeypatch):
    version = _version()

    async def issuable(_db, _user, _tid):
        return SimpleNamespace(id=1), version

    async def assignable(_db, client_id):
        return SimpleNamespace(id=client_id)

    async def access(*_a, **_kw):
        return None

    async def job(_db, _user, job_id, write=False):
        return SimpleNamespace(id=job_id, client_id=OTHER if job_id == 2 else ALLOWED)

    async def link(*_a, **_kw):
        return None

    monkeypatch.setattr(api, "_issuable", issuable)
    monkeypatch.setattr(api, "assert_client_assignable", assignable)
    monkeypatch.setattr(api, "_assert_generator_client_access", access)
    monkeypatch.setattr(api, "_load_legal_scoped_job", job)
    monkeypatch.setattr(api, "_validate_candidate_job_link", link)
    monkeypatch.setattr(api.svc, "fields_of", lambda _v: [])
    monkeypatch.setattr(api.sandbox, "render", lambda *_a, **_kw: pytest.fail("render bez zgody"))
    return version


@pytest.mark.asyncio
@pytest.mark.parametrize("client_id", [None, OTHER])
async def test_preview_refuses_client_outside_the_list(routes, client_id):
    request = api.CustomDocumentRequest(values={}, client_id=client_id)
    with pytest.raises(HTTPException) as exc:
        await api.custom_document_preview(1, request, SimpleNamespace(id=5), db=None)
    assert exc.value.status_code == 422 and "wybranych klientów" in exc.value.detail


@pytest.mark.asyncio
async def test_preview_refuses_candidate_from_other_clients_job(routes):
    request = api.CustomDocumentRequest(values={}, candidate_id=7, job_id=2)
    with pytest.raises(HTTPException) as exc:
        await api.custom_document_preview(1, request, SimpleNamespace(id=5), db=None)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_prefill_refuses_candidate_from_other_clients_job(routes):
    class _Db:
        async def get(self, *_a):
            pytest.fail("dane kandydata czytane mimo odmowy")

    with pytest.raises(HTTPException) as exc:
        await api.custom_document_prefill(
            1, SimpleNamespace(id=5), candidate_id=7, job_id=2, db=_Db()
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_prefill_for_offered_client_reads_candidate(routes):
    class _Db:
        async def get(self, *_a):
            return SimpleNamespace(
                name="Anna", lastname="Przykładowa", legal_name=None,
                business_address=None, nip=None, regon=None, email=None, phone=None,
            )

    out = await api.custom_document_prefill(
        1, SimpleNamespace(id=5), candidate_id=7, job_id=1, db=_Db()
    )
    assert out == {"values": {}}  # wzór bez pól — ważne, że nie było odmowy
