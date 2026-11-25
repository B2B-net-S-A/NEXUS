"""Treść dokumentów kontraktu (0788) — bramki tras i odmowy, bez bazy.

Fragment podpisanej umowy niesie stawki tak samo jak PDF, więc bramka jest ta
sama co pobranie pliku (``download_contract_document``): „Stawki i kwoty:
podgląd”, a konto z rolą Delivery Leada tylko u klienta z przypisania.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import contract_document_text as api
from app.api import contracts
from app.models.contract import Contract
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.services.contract_document_text import index, service
from app.services.jarvis import nexus_sources
from tests.test_permissions_contracts_rules import (
    FINANCE,
    LEAD,
    TCM,
    _everything_but,
    _gate_refusal,
    _holder,
    _portfolio,
    _route_id,
    _user,
)

ROUTES = (
    api.search_contract_documents,
    api.contract_termination_terms,
    api.read_contract_document_text,
)


@pytest.mark.parametrize("endpoint", ROUTES, ids=_route_id)
async def test_document_text_requires_the_amounts_view(endpoint) -> None:
    assert await _gate_refusal(endpoint, _holder("amounts_view")) is None
    refusal = await _gate_refusal(endpoint, _everything_but("amounts_view"))
    assert refusal["permission"] == "amounts_view"


class _Db:
    """Atrapa sesji: ``scalar`` oddaje kontrakt albo dokument po encji zapytania."""

    def __init__(self, contract=None, document=None):
        self.contract = contract
        self.document = document

    async def scalar(self, statement, *_args, **_kwargs):
        entity = statement.column_descriptions[0]["entity"]
        if entity is Contract:
            return self.contract
        if entity is ContractDocument:
            return self.document
        raise AssertionError(f"nieoczekiwane zapytanie: {entity}")


class _Reached(Exception):
    """Handler przeszedł bramki i sięgnął po treść."""


@pytest.fixture
def portfolio(monkeypatch):
    monkeypatch.setattr(contracts, "resolve_delivery_lead_client_ids", _portfolio(5))
    monkeypatch.setattr(
        contracts, "resolve_delivery_lead_finance_client_ids", _portfolio(5)
    )

    async def reached(*_args, **_kwargs):
        raise _Reached

    monkeypatch.setattr(service, "search_contract_documents", reached)
    monkeypatch.setattr(service, "read_contract_document", reached)
    monkeypatch.setattr(service, "termination_terms", reached)


def _contract(client_id: int):
    return SimpleNamespace(id=1, client_id=client_id)


async def test_delivery_lead_reads_only_at_an_assigned_client(portfolio) -> None:
    lead = _user(LEAD)
    with pytest.raises(_Reached):
        await api.search_contract_documents(
            contract_id=1, current_user=lead, q="wypowiedzenie", db=_Db(_contract(5))
        )
    # Klient spoza przypisania: kontrakt nie istnieje dla tego konta.
    with pytest.raises(HTTPException) as denied:
        await api.contract_termination_terms(
            contract_id=1, current_user=lead, db=_Db(_contract(6))
        )
    assert denied.value.status_code in (403, 404)

    # Finanse i osoba z nadanym podglądem kwot: każdy klient.
    for user in (_user(FINANCE), _holder("amounts_view", role=TCM)):
        with pytest.raises(_Reached):
            await api.contract_termination_terms(
                contract_id=1, current_user=user, db=_Db(_contract(6))
            )


def _document(doc_type=ContractDocumentType.contract, contract_id: int = 1):
    return SimpleNamespace(id=10, contract_id=contract_id, doc_type=doc_type)


async def test_document_text_refusals(portfolio) -> None:
    lead = _user(LEAD)
    with pytest.raises(HTTPException) as missing:
        await api.read_contract_document_text(
            document_id=10, current_user=lead, from_chunk=0, db=_Db(_contract(5))
        )
    assert missing.value.status_code == 404

    # Dokument kontraktu u cudzego klienta — ta sama odmowa co pobranie pliku.
    with pytest.raises(HTTPException) as foreign:
        await api.read_contract_document_text(
            document_id=10,
            current_user=lead,
            from_chunk=0,
            db=_Db(_contract(6), _document()),
        )
    assert foreign.value.status_code in (403, 404)

    # Zaświadczenie NIP nie jest treścią umowy.
    with pytest.raises(HTTPException) as other_type:
        await api.read_contract_document_text(
            document_id=10,
            current_user=lead,
            from_chunk=0,
            db=_Db(_contract(5), _document(ContractDocumentType.nip)),
        )
    assert other_type.value.status_code == 422

    with pytest.raises(_Reached):
        await api.read_contract_document_text(
            document_id=10,
            current_user=lead,
            from_chunk=0,
            db=_Db(_contract(5), _document(ContractDocumentType.annex)),
        )


def test_only_contract_terms_are_read() -> None:
    assert {t.value for t in index.READ_TYPES} == {
        "contract",
        "annex",
        "termination_notice",
        "termination_agreement",
    }
    assert index.is_read_type("contract") and not index.is_read_type("oc_policy")
    # Kolekcja nie może zaczynać się od ``nexus_candidates`` (kasowanie
    # punktów kandydata po id skasowałoby fragment o tym samym numerze).
    assert not index.COLLECTION.startswith("nexus_candidates")


def test_reading_state_says_why_there_is_no_text() -> None:
    doc = SimpleNamespace(
        doc_type="contract",
        file_path="c/1/a.pdf",
        text_file_path=None,
        text_status=None,
        text_pages=None,
        text_chars=None,
        text_ocr_pages=None,
    )
    assert "czytany" in index.reading_note(doc)
    assert index.needs_indexing(
        SimpleNamespace(**{**doc.__dict__, "text_attempted_at": None})
    )
    failed = SimpleNamespace(
        **{**doc.__dict__, "text_file_path": "c/1/a.pdf", "text_status": "failed"}
    )
    assert "nie udał" in index.reading_note(failed)
    assert not index.has_current_text(failed)


def test_jarvis_sources_come_from_the_tool_result() -> None:
    shaped = {
        "contract_id": 7,
        "passages": [
            {"document_id": 3, "ref": "umowa nr 12/2025 § 8 ust. 2", "text": "…"},
            {"document_id": 3, "ref": "umowa nr 12/2025 § 8 ust. 2", "text": "…"},
        ],
    }
    found = nexus_sources.collect("search_contract_documents", {}, shaped)
    assert found[0] == {
        "url": "/contracts/7?tab=documents",
        "title": "umowa nr 12/2025 § 8 ust. 2",
        "origin": "nexus",
        "kind": "contract_document",
    }
    merged: list = []
    nexus_sources.merge(merged, found)
    assert len(merged) == 1

    framework = nexus_sources.collect(
        "read_framework_contract",
        {"client_id": 4},
        {"passage": {"contract_name": "Umowa ramowa 2024", "amendment_name": None}},
    )
    assert framework[0]["url"] == "/clients/4?tab=umowy-ramowe"
    # Bez identyfikatora z bazy nie ma źródła; inne narzędzia nie dają źródeł.
    assert (
        nexus_sources.collect("search_contract_documents", {}, {"passages": []}) == []
    )
    assert "list_contracts" not in nexus_sources.TOOLS


def test_jarvis_tools_keep_contract_text_whole_and_off_the_web() -> None:
    from app.services.jarvis.tools import MAX_RESULT_CHARS, TOOLS_BY_NAME, render_result
    from app.services.jarvis.web import WEB_SAFE_TOOLS
    from app.services.framework_contract_text import PASSAGE_BUDGET

    text = "Każda ze Stron może wypowiedzieć Umowę. " * (PASSAGE_BUDGET // 40)
    search = TOOLS_BY_NAME["search_contract_documents"]
    shaped = search.shape(
        {
            "contract_id": 7,
            "query": "wypowiedzenie",
            "retrieval": "keywords",
            "passages": [
                {
                    "document_id": 3,
                    "first_chunk": 2,
                    "last_chunk": 4,
                    "ref": "umowa nr 12/2025 § 8",
                    "text": text,
                    "url": "/contracts/7?tab=documents",
                    "filename": "umowa.pdf",
                }
            ],
            "documents": [
                {
                    "id": 3,
                    "filename": "umowa.pdf",
                    "doc_type": "contract",
                    "in_current_folder": True,
                    "readable": True,
                    "pages": 6,
                    "total_chunks": 9,
                    "note": None,
                }
            ],
        },
        {},
    )
    assert shaped["passages"][0]["text"] == text
    assert len(render_result(shaped)) <= MAX_RESULT_CHARS
    read = TOOLS_BY_NAME["read_contract_document"]
    assert read.path == "/api/contract-documents/{document_id}/text"
    assert {search.name, read.name}.isdisjoint(WEB_SAFE_TOOLS)
    assert search.any_permission == read.any_permission == ("amounts_view",)
