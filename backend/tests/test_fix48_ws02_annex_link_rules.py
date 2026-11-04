"""Powiązanie aneksu z kontraktem — reguły bez bazy (audyt 48 h, 13.10.2026).

Trasa ``POST /documents/{id}/link-contract`` i dowiązanie wiersza rejestru
przy generowaniu aneksu wołane wprost, z sesją-atrapą: odczyty i bramki
dostępu są podmienione, sprawdzamy wyłącznie to, co trasa robi z osobą,
klientem i kontraktem. Pełną ścieżkę na bazie sprawdza
``test_fix48_ws02_annex_api.py``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import b2b_documents
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.services.b2b_documents.registry import TYPES


class _Session:
    """Atrapa ``AsyncSession``: ``get`` z mapy, zapisy do listy."""

    def __init__(self, objects: dict, *, scalar=None):
        self.objects = objects
        self.added: list = []
        self.committed = False
        self._scalar = scalar

    async def get(self, model, key):
        return self.objects.get((model, key))

    async def execute(self, *_a, **_kw):
        return None

    async def scalar(self, *_a, **_kw):
        return self._scalar

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def refresh(self, *_a, **_kw):
        return None


def _person(pid: int, name: str, lastname: str) -> SimpleNamespace:
    return SimpleNamespace(id=pid, name=name, lastname=lastname, email=None)


def _contract(cid: int, *, candidate_id: int, client_id: int, status=None):
    return SimpleNamespace(
        id=cid,
        candidate_id=candidate_id,
        client_id=client_id,
        job_id=None,
        status=status or ContractStatus.active,
    )


def _annex(*, contract_id, candidate_id, client_id) -> SimpleNamespace:
    return SimpleNamespace(
        id=90,
        document_type="annex_start_date",
        status="issued",
        signature_status="unsigned",
        contract_id=contract_id,
        candidate_id=candidate_id,
        client_id=client_id,
        job_id=None,
    )


@pytest.fixture
def link(monkeypatch):
    """``link_document_contract`` z bramkami i odczytami podmienionymi."""

    def _run(doc, target, objects, *, own_agreement=None):
        async def _noop(*_a, **_kw):
            return None

        async def _load_document(*_a, **_kw):
            return doc, TYPES["annex_start_date"], None

        async def _load_subject_contract(*_a, **_kw):
            return target

        async def _serialize(_db, rows, _user):
            return rows

        monkeypatch.setattr(
            b2b_documents, "_require_generated_contract_management", lambda _u: None
        )
        monkeypatch.setattr(b2b_documents, "_require_contract_binding", lambda _u: None)
        monkeypatch.setattr(b2b_documents, "_load_document", _load_document)
        monkeypatch.setattr(b2b_documents, "_authorize_document_write", _noop)
        monkeypatch.setattr(
            b2b_documents, "_load_subject_contract", _load_subject_contract
        )
        monkeypatch.setattr(b2b_documents, "_serialize", _serialize)
        db = _Session(objects, scalar=own_agreement)
        call = b2b_documents.link_document_contract(
            doc.id,
            b2b_documents.LinkContractRequest(contract_id=target.id),
            SimpleNamespace(id=1),
            db,
        )
        return db, call

    return _run


async def test_relinking_refuses_a_contract_of_another_person(link):
    """Aneks osoby A z unieważnionym kontraktem dawał się powiązać
    z kontraktem osoby B — podpis zapisywał wtedy firmę, NIP i stawkę A
    w kontrakcie B (audyt 13.10.2026, pkt 7)."""
    void = _contract(10, candidate_id=1, client_id=5, status=ContractStatus.void)
    other = _contract(20, candidate_id=2, client_id=5)
    doc = _annex(contract_id=10, candidate_id=1, client_id=5)
    db, call = link(
        doc,
        other,
        {
            (Contract, 10): void,
            (Candidate, 1): _person(1, "Anna", "Testowa"),
            (Candidate, 2): _person(2, "Bartosz", "Przykładowy"),
            (Client, 5): SimpleNamespace(id=5, merged_into_client_id=None),
        },
    )
    with pytest.raises(HTTPException) as refused:
        await call
    assert refused.value.status_code == 409
    assert "innej osoby" in refused.value.detail
    assert (doc.contract_id, doc.candidate_id) == (10, 1)
    assert db.committed is False


async def test_relinking_refuses_a_contract_at_another_client(link):
    """Aneks „Bez kontraktu” nie zna osoby — zna klienta, przy którym go
    zapisano. Kontrakt u innego klienta to inny projekt."""
    elsewhere = _contract(30, candidate_id=3, client_id=8)
    doc = _annex(contract_id=None, candidate_id=None, client_id=5)
    db, call = link(
        doc,
        elsewhere,
        {(Client, 5): SimpleNamespace(id=5, merged_into_client_id=None)},
    )
    with pytest.raises(HTTPException) as refused:
        await call
    assert refused.value.status_code == 409
    assert "innego klienta" in refused.value.detail
    assert (doc.contract_id, doc.client_id) == (None, 5)
    assert db.committed is False


async def test_relinking_accepts_the_same_person_in_a_duplicate_record(link):
    """Zdublowany rekord tej samej osoby przechodzi — jak „Powiąż z
    kontraktem” w rejestrze umów (klucz osoby z ``contractor_identity``)."""
    void = _contract(10, candidate_id=1, client_id=5, status=ContractStatus.void)
    twin = _contract(40, candidate_id=4, client_id=5)
    doc = _annex(contract_id=10, candidate_id=1, client_id=5)
    db, call = link(
        doc,
        twin,
        {
            (Contract, 10): void,
            (Candidate, 1): _person(1, "Anna", "Testowa"),
            (Candidate, 4): _person(4, " ANNA ", "Testowa"),
        },
    )
    linked = await call
    assert linked is doc
    assert (doc.contract_id, doc.candidate_id, doc.client_id) == (40, 4, 5)
    assert db.committed is True


async def test_bez_kontraktu_follows_its_client_after_a_client_merge(link):
    """Scalenie klientów nie przenosi dokumentów generatora — aneks przy
    duplikacie wiąże się z kontraktem u klienta kanonicznego."""
    canonical = _contract(50, candidate_id=5, client_id=9)
    doc = _annex(contract_id=None, candidate_id=None, client_id=5)
    db, call = link(
        doc,
        canonical,
        {(Client, 5): SimpleNamespace(id=5, merged_into_client_id=9)},
    )
    await call
    assert (doc.contract_id, doc.client_id) == (50, 9)
    assert db.committed is True


async def test_relinking_refuses_a_contract_that_has_its_own_agreement(link):
    """Kontrakt z żywą umową w rejestrze dostaje aneks przez tę umowę —
    wybór kontraktu wprost omijał wiersz rejestru (wyszukiwarka takiego
    kontraktu nie pokazuje, trasa go przyjmowała)."""
    target = _contract(60, candidate_id=6, client_id=5)
    doc = _annex(contract_id=None, candidate_id=None, client_id=5)
    db, call = link(
        doc,
        target,
        {(Client, 5): SimpleNamespace(id=5, merged_into_client_id=None)},
        own_agreement="1600/2026",
    )
    with pytest.raises(HTTPException) as refused:
        await call
    assert refused.value.status_code == 422
    assert "1600/2026" in refused.value.detail
    assert doc.contract_id is None
    assert db.committed is False


async def test_annex_links_an_unlinked_row_through_apply_contract_link(monkeypatch):
    """Dowiązanie umowy z Excela przy aneksie ustawiało samo ``contract_id``:
    kontrakt nie dostawał numeru umowy, a oś czasu umowy — wpisu (audyt
    13.10.2026). Rdzeń „Powiąż z kontraktem” robi oba."""
    row = SimpleNamespace(id=70, contract_id=None, candidate_id=7, client_id=5)
    contract = _contract(71, candidate_id=7, client_id=5)
    calls: list[tuple] = []

    async def _live(*_a, **_kw):
        return [71]

    async def _load_parent(*_a, **_kw):
        return row

    async def _apply(db, linked_row, linked_contract, *, user_id):
        calls.append((linked_row, linked_contract, user_id))
        linked_row.contract_id = linked_contract.id

    monkeypatch.setattr(
        b2b_documents.effects, "live_contract_ids_for_unlinked_row", _live
    )
    monkeypatch.setattr(b2b_documents, "_load_parent", _load_parent)
    monkeypatch.setattr(b2b_documents, "apply_contract_link", _apply, raising=False)
    db = _Session({(Contract, 71): contract})

    locked, linked = await b2b_documents._lock_parent_linking_contract(
        db, row, None, may_link=True, user_id=3
    )
    assert (locked, linked) == (row, 71)
    assert calls == [(row, contract, 3)]
