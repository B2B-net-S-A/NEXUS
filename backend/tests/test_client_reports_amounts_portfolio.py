"""Raporty klienta z kwotami tylko w portfelu kwot (audyt 24.11.2026, runda 4).

Generator z kwotami sprawdzał samo uprawnienie „Stawki i kwoty: podgląd”, a zakres
klientów liczył ``resolve_delivery_lead_client_ids``, które kontu Delivery Lead +
Talent Community Manager oddaje wszystkich klientów. Taka hybryda czytała marżę
i stawki klienta spoza swojego portfela kwot. Kwoty jednego klienta rozstrzyga
``can_read_client_finance`` (``docs/claude/uprawnienia/
delivery-lead-widzi-kwoty-wlasnego-portfela-profil.md``). Bez bazy: odczyty
trasy podmienione, klienci i progi fikcyjne.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import client_reports as api
from app.models.client_report import ClientReportDefinition
from app.models.user import UserRole
from app.services.access_scope import DL_CLIENT_OUT_OF_SCOPE_DETAIL
from app.services.client_reports import catalog
from app.services.client_reports.registry import ReportData, SummaryLine

pytestmark = pytest.mark.asyncio

OWN = 101  # klient z przypisania DL
OTHER = 202  # klient widoczny przez TCM, poza portfelem kwot
TIERS = [{"up_to": 1000.0, "rate": 1.0}, {"up_to": None, "rate": 2.0}]


def _user(*roles: UserRole, permissions: tuple[str, ...] = ()):
    role_set = set(roles)
    user = SimpleNamespace(
        id=17,
        is_active=True,
        role=roles[0],
        roles=[role.value for role in roles[1:]],
        get_all_roles=lambda: role_set,
        has_role=lambda role: role in role_set,
        has_any_role=lambda *required: bool(role_set.intersection(required)),
    )
    user.effective_action_access = {key: "manage" for key in permissions}
    user.effective_section_access = {}
    return user


def _hybrid():
    return _user(
        UserRole.delivery_lead,
        UserRole.talent_community_manager,
        permissions=("delivery_view", "amounts_view"),
    )


def _definition(client_id: int) -> ClientReportDefinition:
    return ClientReportDefinition(
        id=client_id,
        client_id=client_id,
        name="Rabat od obrotu",
        family="settlement",
        generator_key="annual_spend",
        params={"tiers": TIERS, "marginal": True, "currency": "EUR"},
        rhythm="annual",
        due_rule={},
        preparer="dl",
        source_kind="dl",
        status="active",
    )


class _FakeDb:
    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        return None


@pytest.fixture
def world(monkeypatch):
    """Hybryda widzi w Delivery obu klientów, kwoty tylko u ``OWN``."""

    async def finance_ids(user, db):
        return frozenset({OWN})

    async def definition(db, user, definition_id):
        return _definition(definition_id), frozenset({OWN, OTHER})

    async def load(db, definition, generator, period):
        client = SimpleNamespace(id=definition.client_id, name="Klient testowy")
        return client, ReportData(lines=(SummaryLine("Obrót", "1 000,00"),))

    monkeypatch.setattr(api, "resolve_delivery_lead_finance_client_ids", finance_ids)
    monkeypatch.setattr(api, "_definition", definition)
    monkeypatch.setattr(api, "_load", load)
    monkeypatch.setattr(
        api.storage_service,
        "save_client_report_file",
        lambda client_id, name, content: (f"raporty/{client_id}/{name}", len(content)),
    )


async def test_hybrid_preview_of_client_outside_amounts_portfolio_is_403(world):
    with pytest.raises(HTTPException) as denied:
        await api.preview_report(OTHER, _hybrid(), period="2026", db=_FakeDb())
    assert denied.value.status_code == 403
    assert denied.value.detail == DL_CLIENT_OUT_OF_SCOPE_DETAIL


async def test_hybrid_export_of_client_outside_amounts_portfolio_is_403(world):
    db = _FakeDb()
    with pytest.raises(HTTPException) as denied:
        await api.export_report(OTHER, _hybrid(), period="2026", db=db)
    assert denied.value.status_code == 403
    assert denied.value.detail == DL_CLIENT_OUT_OF_SCOPE_DETAIL
    assert db.added == []


async def test_hybrid_reads_amounts_of_own_client(world):
    preview = await api.preview_report(OWN, _hybrid(), period="2026", db=_FakeDb())
    assert preview["lines"] == [
        {"label": "Obrót", "value": "1 000,00", "strong": False}
    ]

    db = _FakeDb()
    response = await api.export_report(OWN, _hybrid(), period="2026", db=db)
    assert response.status_code == 200
    assert [run.client_id for run in db.added] == [OWN]


async def test_amounts_holder_without_dl_role_reads_every_client(world, monkeypatch):
    async def no_boundary(user, db):
        return None

    monkeypatch.setattr(api, "resolve_delivery_lead_finance_client_ids", no_boundary)
    holder = _user(
        UserRole.talent_community_manager,
        permissions=("delivery_view", "amounts_view"),
    )
    preview = await api.preview_report(OTHER, holder, period="2026", db=_FakeDb())
    assert preview["period_key"] == "2026"


async def test_without_amounts_permission_the_denial_names_it(world):
    lead = _user(UserRole.delivery_lead, permissions=("delivery_view",))
    with pytest.raises(HTTPException) as denied:
        await api.preview_report(OWN, lead, period="2026", db=_FakeDb())
    assert denied.value.status_code == 403
    assert denied.value.detail["permission"] == "amounts_view"


async def test_catalog_of_client_outside_portfolio_hides_amount_params(
    world, monkeypatch
):
    async def empty(*args, **kwargs):
        return {}

    monkeypatch.setattr(catalog, "dl_assignments", empty)
    monkeypatch.setattr(catalog, "user_names", empty)
    monkeypatch.setattr(catalog, "sent_periods", empty)

    payloads = await api._payloads(
        _FakeDb(),
        _hybrid(),
        [_definition(OWN), _definition(OTHER)],
        frozenset({OWN, OTHER}),
    )
    by_client = {p["client_id"]: p["params"] for p in payloads}
    assert by_client[OWN]["tiers"] == TIERS
    # Progi rabatu to warunki handlowe — u klienta spoza portfela kwot znikają,
    # zostają pola bez kwot.
    assert by_client[OTHER] == {"marginal": True, "currency": "EUR"}


async def test_hybrid_history_file_of_client_outside_amounts_portfolio_is_403(
    world, monkeypatch
):
    class _RunDb(_FakeDb):
        async def get(self, model, run_id):
            return SimpleNamespace(
                id=run_id, definition_id=OTHER, file_path="raporty/plik.xlsx"
            )

    read: list[str] = []
    monkeypatch.setattr(
        api.storage_service, "read_client_report_file", lambda path: read.append(path)
    )
    with pytest.raises(HTTPException) as denied:
        await api.run_file(1, _hybrid(), db=_RunDb())
    assert denied.value.status_code == 403
    assert denied.value.detail == DL_CLIENT_OUT_OF_SCOPE_DETAIL
    assert read == []
