"""Kadry nie zmieniają sobie kartoteki ani puli urlopowej (decyzja Artura 19.10.2026).

Ten sam guard „nie sobie” co przy premiach, umowach i rozliczeniach: osoba
z uprawnieniem Kadry (albo Finanse przy formie umowy) nie zmienia własnej
puli, przełożonego, formy, statusu ani „składa raport godzin”. Zrobi to admin
albo inna osoba z Kadr. Testy bez bazy: odmowa pada przed pierwszym
zapytaniem (atrapa sesji nie ma żadnej metody).
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import hr_admin, hr_people, hr_structure
from app.api.hr_gates import SELF_EDIT_DETAIL
from app.models.user import User, UserRole
from app.services.hr import account_profiles

ME = 41


def _hr_person() -> User:
    # Finanse z Kadrami (stan produkcji 19.10.2026) — bez roli admina.
    return User(
        id=ME, email="kadry@example.com", role=UserRole.finance, roles=["finance"]
    )


def _admin() -> User:
    return User(id=ME, email="admin@example.com", role=UserRole.admin, roles=["admin"])


NO_DB = SimpleNamespace()


async def _refused(call) -> HTTPException:
    with pytest.raises(HTTPException) as exc:
        await call
    assert exc.value.status_code == 403
    assert exc.value.detail == SELF_EDIT_DETAIL
    return exc.value


@pytest.mark.asyncio
async def test_own_profile_update_is_refused():
    await _refused(
        hr_admin.update_profile(
            ME, hr_admin.ProfileFields(manager_user_id=7), _hr_person(), NO_DB
        )
    )


@pytest.mark.asyncio
async def test_own_profile_creation_is_refused():
    await _refused(
        hr_admin.create_profile(hr_admin.ProfileCreate(user_id=ME), _hr_person(), NO_DB)
    )


@pytest.mark.asyncio
async def test_own_entitlement_is_refused():
    await _refused(
        hr_admin.put_entitlement(
            ME,
            2026,
            hr_admin.EntitlementIn(entitlement_days=Decimal("30")),
            _hr_person(),
            NO_DB,
        )
    )


@pytest.mark.asyncio
async def test_bulk_timesheet_required_including_self_is_refused():
    await _refused(
        hr_admin.set_timesheet_required(
            hr_admin.TimesheetRequiredIn(user_ids=[3, ME], required=False),
            _hr_person(),
            NO_DB,
        )
    )


@pytest.mark.asyncio
async def test_reassigning_self_in_structure_is_refused():
    await _refused(
        hr_structure.reassign(
            hr_structure.ReassignIn(user_ids=[ME], manager_user_id=None),
            _hr_person(),
            NO_DB,
        )
    )


@pytest.mark.asyncio
async def test_own_division_is_refused():
    await _refused(
        hr_structure.set_division(
            hr_structure.DivisionIn(user_ids=[ME, 5], division="back_office"),
            _hr_person(),
            NO_DB,
        )
    )


@pytest.mark.asyncio
async def test_own_employment_type_is_refused():
    await _refused(
        hr_people.set_employment_type(
            ME,
            hr_people.EmploymentTypeIn(employment_type="uop"),
            _hr_person(),
            NO_DB,
        )
    )


@pytest.mark.asyncio
async def test_admin_may_edit_own_profile():
    # Admin przechodzi guard — dalej idzie do serwisu (tu: atrapa bez bazy).
    with pytest.raises(AttributeError):
        await hr_admin.update_profile(
            ME, hr_admin.ProfileFields(job_title="Zarząd"), _admin(), NO_DB
        )


@pytest.mark.asyncio
async def test_someone_else_is_not_refused():
    with pytest.raises(AttributeError):
        await hr_admin.update_profile(
            7, hr_admin.ProfileFields(job_title="Rekruterka"), _hr_person(), NO_DB
        )


# ── „Wyrównaj wg konta” (audyt 21.10.2026) ──────────────────────────────────


@pytest.mark.asyncio
async def test_aligning_self_with_the_account_is_refused():
    await _refused(
        hr_people.align_with_accounts(
            hr_people.AlignIn(user_ids=[3, ME]), _hr_person(), NO_DB
        )
    )


@pytest.mark.asyncio
async def test_admin_may_align_own_profile():
    # Admin przechodzi guard — dalej idzie do serwisu (tu: atrapa bez bazy).
    with pytest.raises(AttributeError):
        await hr_people.align_with_accounts(
            hr_people.AlignIn(user_ids=[ME]), _admin(), NO_DB
        )


class _AlignDb:
    """Atrapa sesji dla rozjazdów „missing”: ``get`` i ``flush``/``commit``."""

    async def get(self, _model, user_id):
        return SimpleNamespace(id=user_id)

    async def flush(self):
        return None

    async def commit(self):
        return None


def _missing(user_id: int) -> account_profiles.Mismatch:
    return account_profiles.Mismatch(
        user_id=user_id,
        name="Osoba Przykładowa",
        email=f"osoba{user_id}@example.com",
        account_active=True,
        employment_status=None,
        proposed_status="active",
        last_working_day=None,
        proposed_last_working_day=None,
        kind="missing",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("actor", "aligned"), [(_hr_person, [7]), (_admin, [7, ME])])
async def test_align_all_skips_own_profile_unless_admin(monkeypatch, actor, aligned):
    created: list[int] = []

    async def mismatches(_db):
        return [_missing(7), _missing(ME)]

    async def ensure_profile(_db, user, **_kwargs):
        created.append(user.id)
        return True

    monkeypatch.setattr(account_profiles, "mismatches", mismatches)
    monkeypatch.setattr(account_profiles, "ensure_profile", ensure_profile)

    result = await hr_people.align_with_accounts(
        hr_people.AlignIn(), actor(), _AlignDb()
    )

    assert created == aligned
    assert result == {"aligned": {"exit": 0, "return": 0, "missing": len(aligned)}}


# ── E-teczka i odejście (audyt 24.11.2026) ─────────────────────────────────
#
# Osoba z Kadrami wgrywała do własnej e-teczki oświadczenie studenta
# (``purpose=student_status``) i włączała sobie zwolnienie ze składek, choć
# PATCH profilu dawał jej 403. Tak samo cofała albo przesuwała własne odejście,
# a konto się nie wyłączało.

from app.api import hr_documents, hr_lifecycle  # noqa: E402


class _File:
    filename = "oswiadczenie.pdf"

    async def read(self, _size: int) -> bytes:
        return b"%PDF-1.4"


def _must_not_write(*_args, **_kwargs):
    raise AssertionError("zapis własnej e-teczki albo sprawy odejścia")


def _own_document(monkeypatch, *, user_id: int = ME) -> None:
    async def _get(_db, document_id):
        return SimpleNamespace(id=document_id, user_id=user_id)

    monkeypatch.setattr(hr_documents.documents, "get_document", _get)


def _own_case(monkeypatch, *, user_id: int = ME) -> None:
    async def _get(_db, case_id, *, lock=False):
        return SimpleNamespace(id=case_id, user_id=user_id)

    monkeypatch.setattr(hr_lifecycle, "_case_or_404", _get)


@pytest.mark.asyncio
async def test_upload_to_own_e_file_is_refused(monkeypatch):
    monkeypatch.setattr(hr_documents.documents, "upload", _must_not_write)
    await _refused(
        hr_documents.upload_document(
            ME,
            file=_File(),
            kind="statement",
            title="Oświadczenie studenta",
            valid_until=None,
            purpose="student_status",
            visible_to_person=None,
            visible_to_payroll=None,
            visible_to_equipment=None,
            current_user=_hr_person(),
            db=NO_DB,
        )
    )


@pytest.mark.asyncio
async def test_patch_of_own_document_is_refused(monkeypatch):
    _own_document(monkeypatch)
    monkeypatch.setattr(hr_documents.documents, "update", _must_not_write)
    await _refused(
        hr_documents.patch_document(
            5, hr_documents.DocumentPatchIn(title="Nowy"), _hr_person(), NO_DB
        )
    )


@pytest.mark.asyncio
async def test_removal_of_own_document_is_refused(monkeypatch):
    _own_document(monkeypatch)
    monkeypatch.setattr(hr_documents.documents, "remove", _must_not_write)
    await _refused(
        hr_documents.remove_document(
            5, hr_documents.RemoveIn(note="pomyłka"), _hr_person(), NO_DB
        )
    )


@pytest.mark.asyncio
async def test_admin_may_patch_own_document(monkeypatch):
    _own_document(monkeypatch)

    class _Reached(Exception):
        pass

    async def _update(*_args, **_kwargs):
        raise _Reached

    monkeypatch.setattr(hr_documents.documents, "update", _update)
    with pytest.raises(_Reached):
        await hr_documents.patch_document(
            5, hr_documents.DocumentPatchIn(title="Nowy"), _admin(), NO_DB
        )


@pytest.mark.asyncio
async def test_own_offboarding_cannot_be_created(monkeypatch):
    monkeypatch.setattr(hr_lifecycle.service, "create_offboarding", _must_not_write)
    await _refused(
        hr_lifecycle.create_offboarding(
            hr_lifecycle.OffboardingIn(user_id=ME, last_working_day="2026-12-31"),
            _hr_person(),
            NO_DB,
        )
    )


@pytest.mark.asyncio
async def test_own_onboarding_cannot_be_created(monkeypatch):
    monkeypatch.setattr(hr_lifecycle.service, "create_onboarding", _must_not_write)
    await _refused(
        hr_lifecycle.create_onboarding(
            hr_lifecycle.OnboardingIn(user_id=ME, start_date="2026-12-01"),
            _hr_person(),
            NO_DB,
        )
    )


@pytest.mark.asyncio
async def test_own_last_working_day_cannot_be_moved(monkeypatch):
    _own_case(monkeypatch)
    monkeypatch.setattr(hr_lifecycle.service, "update_case", _must_not_write)
    await _refused(
        hr_lifecycle.update_case(
            9,
            hr_lifecycle.CaseUpdateIn(last_working_day="2027-06-30"),
            _hr_person(),
            NO_DB,
        )
    )


@pytest.mark.parametrize(
    ("route", "service_name"),
    [
        (hr_lifecycle.start_case, "start_case"),
        (hr_lifecycle.cancel_case, "cancel_case"),
        (hr_lifecycle.complete_case, "complete_case"),
    ],
)
@pytest.mark.asyncio
async def test_own_case_transitions_are_refused(monkeypatch, route, service_name):
    _own_case(monkeypatch)
    monkeypatch.setattr(hr_lifecycle.service, service_name, _must_not_write)
    await _refused(route(9, _hr_person(), NO_DB))


@pytest.mark.asyncio
async def test_own_account_cannot_be_deactivated_now(monkeypatch):
    _own_case(monkeypatch)
    monkeypatch.setattr(hr_lifecycle.service, "deactivate_now", _must_not_write)
    await _refused(
        hr_lifecycle.deactivate_now(9, _hr_person(), despite_handover=False, db=NO_DB)
    )


@pytest.mark.asyncio
async def test_own_handovers_and_tasks_are_refused(monkeypatch):
    _own_case(monkeypatch)
    monkeypatch.setattr(hr_lifecycle.service, "set_receivers", _must_not_write)
    monkeypatch.setattr(hr_lifecycle.service, "add_task", _must_not_write)
    await _refused(
        hr_lifecycle.set_handovers(
            9, hr_lifecycle.HandoversIn(receivers={}), _hr_person(), NO_DB
        )
    )
    await _refused(
        hr_lifecycle.add_task(
            9, hr_lifecycle.TaskIn(title="Zwrot laptopa"), _hr_person(), NO_DB
        )
    )


@pytest.mark.asyncio
async def test_someone_elses_case_is_not_refused(monkeypatch):
    _own_case(monkeypatch, user_id=ME + 1)

    class _Reached(Exception):
        pass

    async def _cancel(*_args, **_kwargs):
        raise _Reached

    monkeypatch.setattr(hr_lifecycle.service, "cancel_case", _cancel)
    with pytest.raises(_Reached):
        await hr_lifecycle.cancel_case(9, _hr_person(), NO_DB)


@pytest.mark.asyncio
async def test_admin_may_cancel_own_case(monkeypatch):
    _own_case(monkeypatch)

    class _Reached(Exception):
        pass

    async def _cancel(*_args, **_kwargs):
        raise _Reached

    monkeypatch.setattr(hr_lifecycle.service, "cancel_case", _cancel)
    with pytest.raises(_Reached):
        await hr_lifecycle.cancel_case(9, _admin(), NO_DB)
