"""Kontrakty za uprawnieniami z ekranu Osoby i role — reguły bez bazy.

Bramki tras są wołane wprost (zależność FastAPI trasy z kontem w pamięci),
a reguły ze środka handlerów — na obiektach-atrapach. Scenariusze HTTP na
prawdziwej bazie stoją w ``test_permissions_contracts.py``.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import get_args, get_type_hints

import pytest
from fastapi import HTTPException

from app.api import autenti, b2b_contract_generator, contracts, signing
from app.models.contract import ContractStatus, ContractTerminationReason
from app.models.user import User, UserRole
from app.schemas.contract import ContractUpdate
from app.services import access_scope, permission_catalog
from app.services.access_scope import is_delivery_lead_governed
from app.services.action_permissions import ProductAction
from app.services.b2b_documents import effects
from app.services.b2b_documents.registry import TYPES
from app.services.section_permissions import ProductSection

ADMIN = UserRole.admin
FINANCE = UserRole.finance
HOR = UserRole.head_of_recruitment
LEAD = UserRole.delivery_lead
TCM = UserRole.talent_community_manager
RECRUITER = UserRole.recruiter

COE = ProductAction.contracts_orders_edit
CS = ProductAction.contract_status


def _user(role: UserRole, *extra_roles: UserRole) -> User:
    """Konto z domyślnym zestawem uprawnień swoich ról (bez snapshotów)."""

    return User(
        id=1,
        email=f"{role.value}@example.com",
        name=role.value,
        role=role,
        roles=[role.value, *(extra.value for extra in extra_roles)],
        is_active=True,
    )


def _holder(*permissions: str, role: UserRole = RECRUITER) -> User:
    """Konto, które ma DOKŁADNIE te uprawnienia z ekranu (z zależnościami).

    Oba snapshoty są ustawione jawnie i spójnie, więc rola nie dokłada
    niczego — test mówi o uprawnieniu, a nie o domyślnym zestawie roli.
    """

    user = _user(role)
    held = permission_catalog.close(permissions)
    user.effective_action_access = {key: "manage" for key in held}
    user.effective_section_access = {
        **{section.value: "none" for section in ProductSection},
        **permission_catalog.derive_sections(held),
    }
    return user


def _everything_but(permission: str) -> User:
    """Komplet uprawnień, z których żadne nie pociąga ``permission``."""

    return _holder(
        *(
            key
            for key in permission_catalog.KEYS
            if permission not in permission_catalog.close((key,))
        )
    )


async def _gate_refusal(endpoint, user: User):
    """Odmowa bramki trasy dla konta (``None`` = bramka wpuszcza)."""

    annotation = get_type_hints(endpoint, include_extras=True)["current_user"]
    gate = get_args(annotation)[1].dependency
    try:
        assert await gate(user) is user
    except HTTPException as exc:
        assert exc.status_code == 403
        return exc.detail
    return None


def _route_id(endpoint) -> str:
    return f"{endpoint.__module__.rsplit('.', 1)[-1]}.{endpoint.__name__}"


def _portfolio(*client_ids: int):
    """Granica przypisania jak z bazy: zbiór dla konta z rolą DL, inaczej None."""

    async def resolve(user, _db):
        return frozenset(client_ids) if is_delivery_lead_governed(user) else None

    return resolve


# ── bramki tras ──────────────────────────────────────────────────────────────

READ_ROUTES = (
    contracts.list_contracts,
    contracts.export_client_register,
    contracts.list_client_register_subcategories,
    contracts.expiring_contracts,
    contracts.get_contract,
    contracts.contract_activities,
    contracts.contract_rate_history,
    contracts.list_contract_amendments,
    contracts.list_onboarding_items,
    contracts.list_contract_equipment,
    contracts.contract_timeline,
)

EDIT_ROUTES = (
    contracts.create_contract,
    contracts.bulk_extend_contracts,
    contracts.activate_contract,
    contracts.reopen_contract_endpoint,
    contracts.void_contract_endpoint,
    contracts.delete_contract,
    contracts.update_contract_draft,
    contracts.finalize_contract_draft,
    contracts.upload_contract_document,
    contracts.update_contract_document,
    contracts.delete_contract_document,
    contracts.create_contract_amendment,
    contracts.create_onboarding_item,
    contracts.seed_onboarding_items,
    contracts.update_onboarding_item,
    contracts.delete_onboarding_item,
    contracts.create_contract_equipment,
    contracts.update_contract_equipment,
    contracts.delete_contract_equipment,
    contracts.create_contract_note,
    autenti.send_contract_for_signature,
    autenti.withdraw_signature,
    autenti.remind_signer,
    signing.send_for_signature,
    signing.mark_sent_offline,
    signing.withdraw_signature,
    signing.regenerate_link,
)

STATUS_ROUTES = (
    contracts.update_contract_status,
    contracts.terminate_contract,
    contracts.bulk_mark_ended,
)

# Szkic, pliki i historia podpisów niosą stawki, których nie da się zredagować.
RATE_BEARING_READ_ROUTES = (
    contracts.get_contract_draft,
    contracts.render_draft_for_print,
    contracts.list_contract_documents,
    contracts.download_contract_document,
    autenti.list_signatures_for_contract,
    autenti.get_signature_detail,
    signing.list_signatures,
    signing.get_signature,
)


@pytest.mark.parametrize("endpoint", READ_ROUTES, ids=_route_id)
async def test_contract_reads_require_the_delivery_view(endpoint) -> None:
    assert await _gate_refusal(endpoint, _holder("delivery_view")) is None

    refusal = await _gate_refusal(endpoint, _everything_but("delivery_view"))
    assert refusal["code"] == "permission_denied"
    assert refusal["permission"] == "delivery_view"


@pytest.mark.parametrize("endpoint", EDIT_ROUTES, ids=_route_id)
async def test_contract_mutations_require_contract_editing(endpoint) -> None:
    assert await _gate_refusal(endpoint, _holder("contracts_orders_edit")) is None

    # Komplet pozostałych uprawnień (także zmiana kwot i statusu) nie zastępuje
    # edycji kontraktów.
    refusal = await _gate_refusal(endpoint, _everything_but("contracts_orders_edit"))
    assert refusal["code"] == "permission_denied"
    assert refusal["permission"] == "contracts_orders_edit"
    assert refusal["label"] == "Kontrakty i zamówienia: tworzenie i edycja"


@pytest.mark.parametrize("endpoint", STATUS_ROUTES, ids=_route_id)
async def test_status_and_termination_require_the_status_permission(endpoint) -> None:
    assert await _gate_refusal(endpoint, _holder("contract_status")) is None

    refusal = await _gate_refusal(endpoint, _everything_but("contract_status"))
    assert refusal["code"] == "permission_denied"
    assert refusal["permission"] == "contract_status"


@pytest.mark.parametrize("endpoint", RATE_BEARING_READ_ROUTES, ids=_route_id)
async def test_rate_bearing_documents_require_the_amounts_view(endpoint) -> None:
    assert await _gate_refusal(endpoint, _holder("amounts_view")) is None

    # Edycja kontraktów bez podglądu kwot nie otwiera dokumentów.
    refusal = await _gate_refusal(endpoint, _everything_but("amounts_view"))
    assert refusal["code"] == "permission_denied"
    assert refusal["permission"] == "amounts_view"


async def test_contract_patch_admits_contract_editors_and_amount_editors() -> None:
    """Trasa mieszana: edycja kontraktów ALBO sama zmiana kwot."""

    patch = contracts.update_contract
    assert await _gate_refusal(patch, _holder("contracts_orders_edit")) is None
    assert await _gate_refusal(patch, _holder("amounts_edit")) is None

    refusal = await _gate_refusal(
        patch, _holder("delivery_view", "amounts_view", "contract_status")
    )
    assert refusal["code"] == "permission_denied"
    assert refusal["permissions"] == ["contracts_orders_edit", "amounts_edit"]


class _ReachedDatabase(Exception):
    """Handler przeszedł bramki i sięgnął po kontrakt."""


class _NoDatabase:
    async def execute(self, *_args, **_kwargs):
        raise _ReachedDatabase


async def _patch_contract(user: User, **fields):
    await contracts.update_contract(
        contract_id=1,
        data=ContractUpdate(**fields),
        current_user=user,
        db=_NoDatabase(),
    )


async def test_amounts_only_holder_changes_nothing_but_amounts() -> None:
    """Kto wszedł samą zmianą kwot, nie edytuje reszty kontraktu — odmowa
    zapada, zanim handler odczyta wiersz."""

    amounts_only = _holder("amounts_edit")

    with pytest.raises(HTTPException) as denied:
        await _patch_contract(amounts_only, project_name="Nowy projekt", rate_client=1)
    assert denied.value.status_code == 403
    assert denied.value.detail["code"] == "finance_amounts_only"
    assert denied.value.detail["fields"] == ["project_name"]

    with pytest.raises(_ReachedDatabase):
        await _patch_contract(amounts_only, rate_client=175, rate_candidate=120)

    # Edycja kontraktów zdejmuje to ograniczenie — także Finansom, które od
    # 02.10.2026 mają ją domyślnie.
    with pytest.raises(_ReachedDatabase):
        await _patch_contract(
            _holder("contracts_orders_edit"), project_name="Nowy projekt"
        )
    with pytest.raises(_ReachedDatabase):
        await _patch_contract(_user(FINANCE), project_name="Nowy projekt")


# Kto przechodzi bramkę przy DOMYŚLNYCH uprawnieniach ról (to, co admin widzi
# na ekranie po migracji) — jedna trasa na każde uprawnienie.
DEFAULT_HOLDERS = (
    (contracts.get_contract, {ADMIN, FINANCE, LEAD, TCM}),
    # Decyzja Artura 02.10.2026: Finanse zakładają i edytują kontrakty.
    (contracts.create_contract, {ADMIN, FINANCE, LEAD}),
    (contracts.update_contract, {ADMIN, FINANCE, LEAD}),
    (signing.send_for_signature, {ADMIN, FINANCE, LEAD}),
    # Statusu Finanse nie zmieniają; TCM kończy współpracę — także zbiorczo.
    (contracts.update_contract_status, {ADMIN, LEAD, TCM}),
    (contracts.terminate_contract, {ADMIN, LEAD, TCM}),
    (contracts.bulk_mark_ended, {ADMIN, LEAD, TCM}),
    # TCM czyta rejestr operacyjnie, ale dokumentów ze stawkami nie otwiera.
    (contracts.list_contract_documents, {ADMIN, FINANCE, LEAD}),
    (signing.list_signatures, {ADMIN, FINANCE, LEAD}),
)


@pytest.mark.parametrize(
    ("endpoint", "holders"),
    DEFAULT_HOLDERS,
    ids=[_route_id(endpoint) for endpoint, _ in DEFAULT_HOLDERS],
)
async def test_default_role_permissions_decide_the_contract_gates(
    endpoint, holders
) -> None:
    admitted = {
        role for role in UserRole if await _gate_refusal(endpoint, _user(role)) is None
    }
    assert admitted == holders


# ── kwoty kontraktu ──────────────────────────────────────────────────────────

AMOUNT_FIELDS = {
    "rate_candidate",
    "rate_client",
    "candidate_rate_schedule",
    "framework_rate",
}


@pytest.mark.parametrize("role", [LEAD, HOR, TCM, RECRUITER])
async def test_contract_amounts_are_refused_without_the_amounts_edit(role) -> None:
    with pytest.raises(HTTPException) as denied:
        await contracts._assert_contract_finance_write_allowed(
            _user(role), AMOUNT_FIELDS, client_id=1, db=None
        )

    assert denied.value.status_code == 403
    detail = denied.value.detail
    # Kod i lista pól zostają dla frontu; odmowa nazywa brakujący przełącznik.
    assert detail["code"] == "finance_fields_forbidden"
    assert detail["fields"] == sorted(AMOUNT_FIELDS)
    assert detail["permission"] == "amounts_edit"
    assert detail["label"] == "Stawki i kwoty: zmiana"
    assert "„Stawki i kwoty: zmiana”" in detail["message"]


@pytest.mark.parametrize("role", [ADMIN, FINANCE])
async def test_contract_amounts_are_written_with_the_amounts_edit(role) -> None:
    await contracts._assert_contract_finance_write_allowed(
        _user(role), AMOUNT_FIELDS, client_id=1, db=None
    )


async def test_finance_without_the_amounts_edit_cannot_change_amounts() -> None:
    finance = _holder("delivery_view", "amounts_view", role=FINANCE)

    with pytest.raises(HTTPException) as denied:
        await contracts._assert_contract_finance_write_allowed(
            finance, {"rate_candidate"}, client_id=1, db=None
        )

    assert denied.value.status_code == 403
    assert denied.value.detail["permission"] == "amounts_edit"


async def test_operational_fields_never_reach_the_amount_gate() -> None:
    """Bez pól kwot bramka nie pyta o nic — także bez sięgania do bazy."""

    await contracts._assert_contract_finance_write_allowed(
        _user(LEAD), {"project_name", "end_date", "status"}, client_id=1, db=None
    )


async def test_granted_amounts_edit_binds_a_delivery_lead_to_the_portfolio(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        contracts, "resolve_delivery_lead_finance_client_ids", _portfolio(5)
    )
    lead = _holder("contracts_orders_edit", "amounts_edit", role=LEAD)

    await contracts._assert_contract_finance_write_allowed(
        lead, {"rate_candidate"}, client_id=5, db=None
    )
    with pytest.raises(HTTPException) as denied:
        await contracts._assert_contract_finance_write_allowed(
            lead, {"rate_candidate"}, client_id=6, db=None
        )

    assert denied.value.status_code == 403
    # Uprawnienie jest — odmowa mówi o portfelu, nie o brakującym przełączniku.
    assert denied.value.detail == "Ten klient jest poza Twoim portfelem."


# ── status i dane zakończenia w zwykłym PATCH-u ──────────────────────────────


def _contract(**overrides):
    values = {
        "status": ContractStatus.active,
        "end_date": None,
        "termination_reason": None,
        "termination_lessons": None,
        "terminated_at": None,
    }
    return SimpleNamespace(**{**values, **overrides})


def test_resending_the_same_status_needs_no_status_permission() -> None:
    """Formularz edycji odsyła status przy każdym zapisie."""

    finance = _user(FINANCE)  # edytuje kontrakty, statusu nie zmienia
    contracts._assert_contract_status_change_allowed(
        finance,
        _contract(),
        ContractUpdate(status="active", project_name="Nowa nazwa projektu"),
    )
    contracts._assert_contract_status_change_allowed(
        finance, _contract(), ContractUpdate(project_name="Bez statusu")
    )


def test_changing_the_status_in_a_patch_needs_the_status_permission() -> None:
    with pytest.raises(HTTPException) as denied:
        contracts._assert_contract_status_change_allowed(
            _user(FINANCE), _contract(), ContractUpdate(status="draft")
        )

    assert denied.value.status_code == 403
    assert denied.value.detail["code"] == "permission_denied"
    assert denied.value.detail["permission"] == "contract_status"

    # Delivery Lead ma domyślnie edycję i zmianę statusu.
    contracts._assert_contract_status_change_allowed(
        _user(LEAD), _contract(), ContractUpdate(status="draft")
    )
    # Wyłączony przełącznik roli odbiera zmianę statusu, edycja zostaje.
    lead_without_status = _holder("contracts_orders_edit", "amounts_view", role=LEAD)
    contracts._assert_contract_status_change_allowed(
        lead_without_status, _contract(), ContractUpdate(project_name="Edycja")
    )
    with pytest.raises(HTTPException) as denied:
        contracts._assert_contract_status_change_allowed(
            lead_without_status, _contract(), ContractUpdate(status="draft")
        )
    assert denied.value.detail["permission"] == "contract_status"


@pytest.mark.parametrize(
    ("stored", "payload"),
    [
        (
            {"termination_reason": None},
            {"termination_reason": "consultant_resigned"},
        ),
        ({"terminated_at": None}, {"terminated_at": "2026-10-31"}),
        ({"termination_lessons": None}, {"termination_lessons": "Wnioski"}),
        (
            {"terminated_at": date(2026, 10, 31)},
            {"terminated_at": None},
        ),
    ],
)
def test_changing_termination_data_in_a_patch_needs_the_status_permission(
    stored, payload
) -> None:
    with pytest.raises(HTTPException) as denied:
        contracts._assert_contract_status_change_allowed(
            _user(FINANCE), _contract(**stored), ContractUpdate(**payload)
        )
    assert denied.value.detail["permission"] == "contract_status"

    contracts._assert_contract_status_change_allowed(
        _user(TCM), _contract(**stored), ContractUpdate(**payload)
    )


@pytest.mark.parametrize(
    ("stored", "payload"),
    [
        # Data wsteczna na trwającej umowie kończy ją (nocny cron).
        ({"status": ContractStatus.active}, {"end_date": "2020-01-31"}),
        (
            {"status": ContractStatus.ending, "end_date": date(2999, 1, 31)},
            {"end_date": "2020-01-31"},
        ),
        # Wyczyszczenie daty „Kończącego się” odwołuje zakończenie.
        (
            {"status": ContractStatus.ending, "end_date": date(2999, 1, 31)},
            {"end_date": None},
        ),
        # Nowa data na „Zakończonym” przywraca współpracę albo poprawia jej koniec.
        (
            {"status": ContractStatus.ended, "end_date": date(2020, 1, 31)},
            {"end_date": "2999-12-31"},
        ),
        (
            {"status": ContractStatus.ended, "end_date": date(2020, 1, 31)},
            {"end_date": None},
        ),
        (
            {"status": ContractStatus.ended, "end_date": date(2020, 1, 31)},
            {"end_date": "2020-02-29"},
        ),
    ],
)
def test_end_date_that_ends_or_revives_cooperation_needs_the_status_permission(
    stored, payload
) -> None:
    """Data końca nie jest bocznymi drzwiami do zmiany statusu (pozycja 4)."""

    with pytest.raises(HTTPException) as denied:
        contracts._assert_contract_status_change_allowed(
            _user(FINANCE), _contract(**stored), ContractUpdate(**payload)
        )
    assert denied.value.detail["permission"] == "contract_status"

    contracts._assert_contract_status_change_allowed(
        _user(LEAD), _contract(**stored), ContractUpdate(**payload)
    )


@pytest.mark.parametrize(
    ("stored", "payload"),
    [
        # Termin umowy zlecenie/o pracę w przyszłości to zwykła edycja.
        ({"status": ContractStatus.active}, {"end_date": "2999-12-31"}),
        (
            {"status": ContractStatus.ending, "end_date": date(2999, 1, 31)},
            {"end_date": "2999-12-31"},
        ),
        # Formularz odsyła niezmienioną datę przy każdym zapisie.
        (
            {"status": ContractStatus.ended, "end_date": date(2020, 1, 31)},
            {"end_date": "2020-01-31", "project_name": "Poprawka nazwy"},
        ),
        # Szkic wpisu historycznej umowy — status się nie zmienia.
        ({"status": ContractStatus.draft}, {"end_date": "2020-01-31"}),
    ],
)
def test_ordinary_end_date_edits_need_no_status_permission(stored, payload) -> None:
    contracts._assert_contract_status_change_allowed(
        _user(FINANCE), _contract(**stored), ContractUpdate(**payload)
    )


def test_extending_an_ended_contract_needs_the_status_permission() -> None:
    """Aneks przedłużenia i zbiorcze „Przedłuż” wskrzeszają „Zakończony”."""

    ended = _contract(status=ContractStatus.ended, end_date=date(2020, 1, 31))
    with pytest.raises(HTTPException) as denied:
        contracts._assert_ended_revival_allowed(_user(FINANCE), ended)
    assert denied.value.detail["permission"] == "contract_status"

    contracts._assert_ended_revival_allowed(_user(LEAD), ended)
    # Przedłużenie trwającej umowy to edycja kontraktu.
    for live in (ContractStatus.active, ContractStatus.ending):
        contracts._assert_ended_revival_allowed(_user(FINANCE), _contract(status=live))


def test_unchanged_termination_data_needs_no_status_permission() -> None:
    stored = _contract(
        status=ContractStatus.ended,
        termination_reason=ContractTerminationReason.consultant_resigned,
        termination_lessons="Wnioski",
        terminated_at=date(2026, 9, 30),
    )
    contracts._assert_contract_status_change_allowed(
        _user(FINANCE),
        stored,
        ContractUpdate(
            status="ended",
            termination_reason="consultant_resigned",
            termination_lessons="Wnioski",
            terminated_at="2026-09-30",
            project_name="Poprawiona nazwa",
        ),
    )


def test_every_termination_field_of_the_patch_schema_is_guarded() -> None:
    """Nowe pole zakończenia w ``ContractUpdate`` nie może ominąć uprawnienia."""

    termination_like = {
        name
        for name in ContractUpdate.model_fields
        if name.startswith(("terminat", "agreement_termination"))
        or name == "agreement_last_day"
    }
    assert termination_like == set(contracts._CONTRACT_TERMINATION_FIELDS)


# ── kwoty na liście i dokumenty ──────────────────────────────────────────────


async def test_list_amounts_follow_the_same_rule_as_the_detail(monkeypatch) -> None:
    monkeypatch.setattr(
        contracts, "resolve_delivery_lead_finance_client_ids", _portfolio(5)
    )
    scope = contracts._contract_finance_read_scope

    assert await scope(_user(ADMIN), None) == (True, frozenset())
    assert await scope(_user(FINANCE), None) == (True, frozenset())
    assert await scope(_user(TCM), None) == (False, frozenset())
    # Delivery Lead: kwoty tylko u klientów z przypisania.
    assert await scope(_user(LEAD), None) == (False, frozenset({5}))
    assert await scope(_user(LEAD, TCM), None) == (False, frozenset({5}))
    # Podgląd kwot nadany osobie bez roli DL: kwoty każdego klienta.
    assert await scope(_holder("amounts_view", role=TCM), None) == (True, frozenset())
    # Wyłączony przełącznik odbiera kwoty także u własnego klienta.
    lead_without_amounts = _holder("delivery_view", "contracts_orders_edit", role=LEAD)
    assert await scope(lead_without_amounts, None) == (False, frozenset())


async def test_contract_documents_follow_the_amounts_view_in_scope(monkeypatch) -> None:
    monkeypatch.setattr(
        contracts, "resolve_delivery_lead_finance_client_ids", _portfolio(5)
    )
    check = contracts._assert_contract_document_client_access
    own = SimpleNamespace(client_id=5)
    foreign = SimpleNamespace(client_id=6)

    await check(own, _user(LEAD), None)
    with pytest.raises(HTTPException) as denied:
        await check(foreign, _user(LEAD), None)
    assert denied.value.status_code == 403
    assert denied.value.detail == (
        "Dokument umowy wymaga przypisania Delivery Leada do klienta"
    )

    # Finanse i osoba z nadanym podglądem kwot: każdy klient.
    await check(foreign, _user(FINANCE), None)
    await check(foreign, _holder("amounts_view", role=TCM), None)

    # Edycja kontraktów bez podglądu kwot: odmowa nazywa brakujące uprawnienie.
    editor = _holder("contracts_orders_edit", role=TCM)
    with pytest.raises(HTTPException) as denied:
        await check(own, editor, None)
    assert denied.value.status_code == 403
    assert denied.value.detail["permission"] == "amounts_view"
    assert denied.value.detail["label"] == "Stawki i kwoty: podgląd"


# ── szkic umowy ──────────────────────────────────────────────────────────────


def _draft_contract():
    return SimpleNamespace(
        id=17,
        client_id=5,
        contract_type="b2b",
        draft_content_html=None,
        draft_template_id=None,
        draft_updated_at=None,
        draft_updated_by=None,
        candidate=SimpleNamespace(name="Anna", lastname="Testowa"),
    )


_DEFAULT_TEMPLATE = SimpleNamespace(
    id=8,
    name="B2B default",
    contract_type="b2b",
    content_jinja="<p>template</p>",
    is_default=True,
)


class _ReadOnlyDb:
    """Sesja, na której podgląd nie może niczego zapisać."""

    def add(self, *_args, **_kwargs):
        raise AssertionError("Podgląd szkicu nie może dopisywać wierszy")

    async def flush(self):
        raise AssertionError("Podgląd szkicu nie może zapisywać")

    async def scalar(self, *_args, **_kwargs):
        raise AssertionError("Podgląd szkicu nie czyta autora zapisu")


class _RecordingDb:
    def __init__(self) -> None:
        self.added: list = []
        self.flushed = False

    def add(self, row) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        self.flushed = True

    async def scalar(self, *_args, **_kwargs):
        return "autor@example.com"


@pytest.fixture
def draft(monkeypatch):
    contract = _draft_contract()

    async def load_contract(*_args, **_kwargs):
        return contract

    async def list_templates(*_args, **_kwargs):
        return [_DEFAULT_TEMPLATE]

    monkeypatch.setattr(contracts, "_load_contract_with_relations", load_contract)
    monkeypatch.setattr(contracts, "_list_templates_for_contract_type", list_templates)
    monkeypatch.setattr(contracts, "_render_draft_body", lambda *_args: "<p>Szkic</p>")
    return contract


def _request(**state):
    return SimpleNamespace(state=SimpleNamespace(**state))


async def test_reader_gets_a_draft_preview_without_persisting(draft) -> None:
    """Sam podgląd kwot czyta szkic, ale go nie zakłada."""

    reader = _holder("amounts_view", role=TCM)

    response = await contracts.get_contract_draft(
        17, request=_request(), current_user=reader, db=_ReadOnlyDb()
    )

    assert response.content_html == "<p>Szkic</p>"
    assert response.template_id == 8
    assert response.rendered_from_default is True
    assert draft.draft_content_html is None
    assert draft.draft_template_id is None
    assert draft.draft_updated_by is None


@pytest.mark.parametrize("role", [FINANCE, LEAD])
async def test_contract_editor_initialises_the_draft(draft, monkeypatch, role) -> None:
    """Kto może edytować kontrakty, zakłada szkic przy pierwszym otwarciu."""

    monkeypatch.setattr(
        contracts, "resolve_delivery_lead_finance_client_ids", _portfolio(5)
    )
    db = _RecordingDb()

    response = await contracts.get_contract_draft(
        17, request=_request(), current_user=_user(role), db=db
    )

    assert response.rendered_from_default is True
    assert draft.draft_content_html == "<p>Szkic</p>"
    assert draft.draft_template_id == 8
    assert draft.draft_updated_by == 1
    assert db.flushed
    assert [row.action for row in db.added] == ["draft_initialized"]


async def test_impersonated_draft_preview_does_not_persist(draft, monkeypatch) -> None:
    """R9-N1-2: admin w „podglądzie jako” nie zapisuje szkicu za podglądanego."""

    monkeypatch.setattr(
        contracts, "resolve_delivery_lead_finance_client_ids", _portfolio(5)
    )

    response = await contracts.get_contract_draft(
        17,
        request=_request(impersonator_id=1),
        current_user=_user(LEAD),
        db=_ReadOnlyDb(),
    )

    assert response.content_html == "<p>Szkic</p>"
    assert response.rendered_from_default is True
    assert draft.draft_content_html is None
    assert draft.draft_updated_by is None


async def test_reader_prints_the_preview_of_an_empty_draft(draft) -> None:
    reader = _holder("amounts_view", role=TCM)

    response = await contracts.render_draft_for_print(17, reader, _ReadOnlyDb())

    assert response.status_code == 200
    assert b"Szkic" in response.body
    assert draft.draft_content_html is None
    assert draft.draft_updated_at is None


async def test_editor_prints_only_a_saved_draft(draft) -> None:
    """Edytor ma zapisany szkic z otwarcia edytora — pusty to 404, nie podgląd."""

    with pytest.raises(HTTPException) as missing:
        await contracts.render_draft_for_print(17, _user(FINANCE), _ReadOnlyDb())
    assert missing.value.status_code == 404

    draft.draft_content_html = "<p>Zapisany</p>"
    response = await contracts.render_draft_for_print(17, _user(FINANCE), _ReadOnlyDb())
    assert response.status_code == 200
    assert b"Zapisany" in response.body


# ── skutki dokumentów B2B w kontrakcie ───────────────────────────────────────


def test_every_document_kind_names_its_contract_permission() -> None:
    """Nowy typ dokumentu wymusza decyzję — słownik musi go wymienić."""

    assert {
        key: effects.contract_effect_permission(doc_type)
        for key, doc_type in TYPES.items()
    } == {
        "annex_party_data": COE,
        "annex_start_date": COE,
        "annex_subcontractor": COE,
        "annex_mandate": COE,
        # Aneks stawki ma własną bramkę kwot.
        "annex_rate_change": None,
        "termination_agreement": CS,
        "termination_agreement_mandate": CS,
        "termination_notice": CS,
        "notice_withdrawal": CS,
        # Umowa przedwstępna niczego w kontraktach nie zmienia.
        "preliminary_cez": None,
    }


def test_an_unknown_document_kind_defaults_to_contract_editing() -> None:
    future = SimpleNamespace(key="annex_from_the_future", family="annex")
    assert effects.contract_effect_permission(future) is COE


class _ContractDb:
    def __init__(self, contract) -> None:
        self._contract = contract

    async def get(self, _model, _contract_id):
        return self._contract


def _signed_document(contract_id: int | None = 7, **values):
    return SimpleNamespace(
        id=1,
        contract_id=contract_id,
        document_date=date(2026, 10, 1),
        render_payload={"values": values},
    )


def _live_contract():
    return SimpleNamespace(
        id=7,
        client_id=5,
        status=ContractStatus.active,
        end_date=None,
        terminated_at=None,
    )


async def _blockers(doc_key: str, user: User, *, contract_id: int | None = 7, **values):
    plan = await effects.describe(
        _ContractDb(_live_contract()),
        _signed_document(contract_id, **values),
        TYPES[doc_key],
        None,
        user=user,
    )
    return plan.blockers


@pytest.mark.parametrize(
    "doc_key",
    ["termination_agreement", "termination_notice", "notice_withdrawal"],
)
async def test_documents_ending_cooperation_need_the_status_permission(doc_key) -> None:
    values = {"termination_date": "2026-12-31"}
    blocker = effects.contract_effect_blocker(CS)
    assert "„Zakończenie współpracy, zmiana statusu kontraktu”" in blocker

    # TCM i Delivery Lead kończą współpracę — bez blokady.
    assert await _blockers(doc_key, _user(TCM), **values) == []
    assert await _blockers(doc_key, _user(LEAD), **values) == []
    # Samo oznaczanie podpisu (rola z włączonym przełącznikiem) nie wystarcza…
    signer = _holder("b2b_signature_confirmation")
    assert await _blockers(doc_key, signer, **values) == [blocker]
    # …ani edycja kontraktów bez zmiany statusu.
    editor = _holder("b2b_signature_confirmation", "contracts_orders_edit")
    assert await _blockers(doc_key, editor, **values) == [blocker]


@pytest.mark.parametrize(
    ("doc_key", "values"),
    [
        ("annex_start_date", {"new_start_date": "2026-11-01"}),
        ("annex_party_data", {"new_legal_name": "Firma Testowa", "new_nip": "1"}),
        ("annex_subcontractor", {"delegate_name": "Osoba Skierowana"}),
    ],
)
async def test_annexes_changing_the_contract_need_contract_editing(
    doc_key, values
) -> None:
    blocker = effects.contract_effect_blocker(COE)
    assert "„Kontrakty i zamówienia: tworzenie i edycja”" in blocker

    assert await _blockers(doc_key, _user(LEAD), **values) == []
    assert await _blockers(doc_key, _user(FINANCE), **values) == []
    # TCM kończy współpracę, ale danych kontraktu nie edytuje.
    assert await _blockers(doc_key, _user(TCM), **values) == [blocker]


def _limited_to_delivery_read(user: User) -> User:
    """Stary wyjątek sekcji osoby: uprawnienie zostaje, Delivery tylko do odczytu."""

    user.effective_section_access = {
        **(user.effective_section_access or {}),
        ProductSection.delivery.value: "read",
    }
    return user


@pytest.mark.parametrize(
    ("doc_key", "permission", "values"),
    [
        (
            "termination_agreement",
            "contract_status",
            {"termination_date": "2026-12-31"},
        ),
        ("notice_withdrawal", "contract_status", {}),
        ("annex_start_date", "contracts_orders_edit", {"new_start_date": "2026-11-01"}),
    ],
)
async def test_contract_effects_need_delivery_write(
    doc_key, permission, values
) -> None:
    """Uprawnienie nie omija sufitu sekcji: podpis dokumentu woła funkcje
    domeny wprost, więc bramka zapisu Delivery z tras Kontraktów go nie chroni."""

    holder = _holder("b2b_signature_confirmation", permission, role=TCM)
    assert await _blockers(doc_key, holder, **values) == []

    limited = _limited_to_delivery_read(
        _holder("b2b_signature_confirmation", permission, role=TCM)
    )
    assert await _blockers(doc_key, limited, **values) == [
        effects.DELIVERY_WRITE_BLOCKER
    ]


async def test_delivery_read_only_does_not_block_a_document_without_effects() -> None:
    limited = _limited_to_delivery_read(_holder("b2b_signature_confirmation"))
    assert await _blockers("preliminary_cez", limited) == []
    assert (
        await _blockers(
            "termination_agreement",
            limited,
            contract_id=None,
            termination_date="2026-12-31",
        )
        == []
    )


async def test_document_without_a_contract_changes_only_the_register() -> None:
    """Bez kontraktu w NEXUSIE nie ma czego pilnować uprawnieniem kontraktu."""

    signer = _holder("b2b_signature_confirmation")
    blockers = await _blockers(
        "termination_agreement",
        signer,
        contract_id=None,
        termination_date="2026-12-31",
    )
    assert blockers == []


async def test_rate_annex_is_confirmed_by_whoever_writes_order_amounts(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        access_scope, "resolve_delivery_lead_finance_client_ids", _portfolio(5)
    )
    confirm = effects.can_confirm_rate_annex

    # „Stawki i kwoty: zmiana” — u każdego klienta, także bez klienta.
    for role in (ADMIN, FINANCE):
        assert await confirm(None, _user(role), 6)
        assert await confirm(None, _user(role), None)

    # Delivery Lead: prowadzi kontrakty i widzi kwoty — u klienta z portfela.
    assert await confirm(None, _user(LEAD), 5)
    assert not await confirm(None, _user(LEAD), 6)
    assert not await confirm(None, _user(LEAD), None)
    assert await confirm(None, _user(HOR, LEAD), 5)
    assert not await confirm(None, _user(HOR, LEAD), 6)

    assert not await confirm(None, _user(TCM), 5)
    # Edycja kontraktów bez podglądu kwot nie wystarcza…
    assert not await confirm(None, _holder("contracts_orders_edit", role=TCM), 5)
    # …z podglądem kwot już tak, u każdego klienta (konto bez roli DL).
    editor = _holder("contracts_orders_edit", "amounts_view", role=TCM)
    assert await confirm(None, editor, 6)
    assert not await confirm(None, editor, None)


async def test_rate_annex_needs_delivery_write(monkeypatch) -> None:
    monkeypatch.setattr(
        access_scope, "resolve_delivery_lead_finance_client_ids", _portfolio(5)
    )
    confirm = effects.can_confirm_rate_annex

    for permissions in (("amounts_edit",), ("contracts_orders_edit", "amounts_view")):
        assert await confirm(None, _holder(*permissions, role=TCM), 6)
        limited = _limited_to_delivery_read(_holder(*permissions, role=TCM))
        assert not await confirm(None, limited, 6)


def test_rate_annex_blocker_names_the_permissions() -> None:
    for label in (
        "Stawki i kwoty: zmiana",
        "Kontrakty i zamówienia: tworzenie i edycja",
        "Stawki i kwoty: podgląd",
    ):
        assert f"„{label}”" in effects.RATE_ANNEX_CONFIRMER_BLOCKER


# ── podpis umowy B2B: zakres klienta ─────────────────────────────────────────


async def test_signature_scope_binds_only_the_delivery_lead_portfolio(
    monkeypatch,
) -> None:
    checked: list[tuple[int | None, bool, str]] = []

    async def client_check(_db, _user, client_id, *, write, purpose):
        checked.append((client_id, write, purpose))

    monkeypatch.setattr(
        b2b_contract_generator, "assert_contract_legal_client_access", client_check
    )
    scope = b2b_contract_generator._assert_signature_client_access

    # W całej organizacji: TCM (także z rolą DL), admin i każda rola, której
    # administrator włączył uprawnienie — rekruter, Finanse.
    for account in (
        _user(TCM),
        _user(LEAD, TCM),
        _user(ADMIN, LEAD),
        _user(RECRUITER),
        _user(FINANCE),
        _holder("b2b_signature_confirmation"),
    ):
        await scope(None, account, 5)
    assert checked == []

    # Konto rządzone portfelem Delivery Leada: klient z przypisania.
    for account in (_user(LEAD), _user(HOR, LEAD), _user(LEAD, RECRUITER)):
        await scope(None, account, 5)
    assert checked == [(5, True, "org")] * 3
