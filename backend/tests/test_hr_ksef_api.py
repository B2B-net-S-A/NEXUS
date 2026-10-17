"""Trasy „Faktury z KSeF” (``/api/hr/ksef``, M5): bramki, lista, PDF spoza KSeF, przypisanie.

Router wpina w ``app/main.py`` koordynator; do czasu wpięcia test dokłada go
do aplikacji na czas testu. Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.hr_ops import HrAuditEvent
from app.models.hr_payroll import PayrollPeriod
from app.models.hr_profile import EmployeeProfile
from app.models.hr_settlement import (
    EmployeeBillingDetails,
    PayrollInvoice,
    PayrollSettlement,
)
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services import storage_service
from app.services.hr.ksef import sync
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING
from tests._ksef_fake import ANNA_NIP, OLA_INVOICE, OLA_NIP

BASE = "/api/hr/ksef"
PDF = b"%PDF-1.4\n% fikcyjna faktura do testu\n%%EOF\n"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _set_setting(key: str, value) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, key)
        if value is None:
            if row is not None:
                await db.delete(row)
        elif row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
        await db.commit()


async def _user(db, role: str, *, profile: bool = True, payroll: bool = False) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"ksef-api-{marker}@example.com",
        name=f"Osoba Przykładowa {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    if profile:
        db.add(EmployeeProfile(user_id=user.id, employment_type="b2b"))
    if payroll:
        db.add(UserActionOverride(user_id=user.id, action="payroll", access="manage"))
    await db.flush()
    return user


class Ctx:
    payroll: User
    stranger: User
    admin: User
    ola: User
    anna: User
    created: list[int]


@pytest.fixture
def ksef_routes():
    from app.api import hr_ksef
    from app.main import app

    before = list(app.router.routes)
    if not any(getattr(route, "path", "").startswith(BASE) for route in before):
        app.include_router(hr_ksef.router, prefix=BASE)
    yield
    app.router.routes[:] = before


@pytest_asyncio.fixture
async def ctx(ksef_routes, monkeypatch, tmp_path):
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _set_setting(HR_MODULES_SETTING, {key: True for key in HR_MODULE_KEYS})
    context = Ctx()
    async with AsyncSessionLocal() as db:
        context.payroll = await _user(db, "employee", payroll=True)
        context.stranger = await _user(db, "employee")
        context.admin = await _user(db, "admin", profile=False)
        context.ola = await _user(db, "employee")
        context.anna = await _user(db, "employee")
        db.add(EmployeeBillingDetails(user_id=context.ola.id, nip=OLA_NIP))
        await db.commit()
    context.created = [
        context.payroll.id,
        context.stranger.id,
        context.admin.id,
        context.ola.id,
        context.anna.id,
    ]
    yield context
    async with AsyncSessionLocal() as db:
        ids = context.created
        await db.execute(
            delete(PayrollInvoice).where(
                PayrollInvoice.seller_nip.in_((OLA_NIP, ANNA_NIP))
            )
        )
        await db.execute(
            delete(PayrollSettlement).where(PayrollSettlement.user_id.in_(ids))
        )
        await db.execute(
            delete(HrAuditEvent).where(HrAuditEvent.subject_user_id.in_(ids))
        )
        await db.execute(
            delete(EmployeeBillingDetails).where(
                EmployeeBillingDetails.user_id.in_(ids)
            )
        )
        await db.execute(
            delete(UserActionOverride).where(UserActionOverride.user_id.in_(ids))
        )
        await db.execute(
            delete(EmployeeProfile).where(EmployeeProfile.user_id.in_(ids))
        )
        await db.execute(
            delete(HrAuditEvent).where(HrAuditEvent.actor_user_id.in_(ids))
        )
        await db.execute(delete(User).where(User.id.in_(ids)))
        await db.execute(delete(AppSetting).where(AppSetting.key == sync.STATE_KEY))
        await db.commit()
    await _set_setting(
        HR_MODULES_SETTING, previous or {key: False for key in HR_MODULE_KEYS}
    )


async def _invoice(**values) -> PayrollInvoice:
    defaults = dict(
        source="ksef",
        ksef_number=OLA_INVOICE,
        seller_nip=OLA_NIP,
        invoice_number="FV 9/2026",
        issue_date=date(2026, 10, 3),
        currency="PLN",
        net_amount=Decimal("16400.00"),
        vat_amount=Decimal("3772.00"),
        gross_amount=Decimal("20172.00"),
        items=[],
        xml_sha256="a" * 64,
        match_status="unmatched",
    )
    defaults.update(values)
    async with AsyncSessionLocal() as db:
        invoice = PayrollInvoice(**defaults)
        db.add(invoice)
        await db.commit()
        return invoice


def _form(ctx: Ctx, **overrides) -> dict[str, str]:
    data = {
        "user_id": str(ctx.ola.id),
        "invoice_number": "R/1/10/2026",
        "issue_date": "2026-10-05",
        "period_year": "2026",
        "period_month": "9",
        "currency": "PLN",
        "net_amount": "2400,00",
        "vat_amount": "0",
        "gross_amount": "2400.00",
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


# ── Bramki ───────────────────────────────────────────────────────────────────


async def test_bez_uprawnienia_place_403(app_client, ctx):
    headers = _headers(ctx.stranger)
    for method, path in (
        ("GET", "/status"),
        ("GET", "/invoices"),
        ("POST", "/fetch"),
        ("POST", "/invoices/1/ignore"),
    ):
        response = await app_client.request(
            method, BASE + path, headers=headers, json={"ignored": True, "reason": "x"}
        )
        assert response.status_code == 403, (method, path, response.text)


async def test_modul_wylaczony_404_admin_przechodzi(app_client, ctx):
    await _set_setting(
        HR_MODULES_SETTING, {key: key != "settlements" for key in HR_MODULE_KEYS}
    )
    response = await app_client.get(f"{BASE}/status", headers=_headers(ctx.payroll))
    assert response.status_code == 404
    response = await app_client.get(f"{BASE}/status", headers=_headers(ctx.admin))
    assert response.status_code == 200


# ── Stan i pobieranie ────────────────────────────────────────────────────────


async def test_karta_stanu_tryb_wylaczony(app_client, ctx):
    response = await app_client.get(f"{BASE}/status", headers=_headers(ctx.payroll))
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "off"
    assert body["enabled"] is False
    assert body["health"] == "disabled"
    assert body["disabled_text"].startswith("Pobieranie z KSeF jest wyłączone")
    assert body["token_configured"] is False
    assert body["white_list"]["mode"] == "off"
    assert "token" not in {k for k in body if k != "token_configured"}


async def test_pobierz_teraz_przy_wylaczonym_trybie_409(app_client, ctx):
    response = await app_client.post(f"{BASE}/fetch", headers=_headers(ctx.payroll))
    assert response.status_code == 409
    assert response.json()["detail"] == sync.DISABLED_DETAIL


async def test_pobierz_ponownie_dla_osoby_bez_nipu_422(app_client, ctx):
    response = await app_client.post(
        f"{BASE}/refetch",
        headers=_headers(ctx.payroll),
        json={"year": 2026, "month": 9, "user_id": ctx.anna.id},
    )
    assert response.status_code == 422
    assert "NIP" in response.json()["detail"]


# ── Lista ────────────────────────────────────────────────────────────────────


async def test_lista_faktur_miesiaca(app_client, ctx):
    in_month = await _invoice(user_id=ctx.ola.id, period_year=2026, period_month=9)
    candidate = await _invoice(
        ksef_number=None,
        source="manual_pdf",
        pdf_storage_key="payroll_invoices/aa/x.pdf",
        invoice_number="bez okresu",
        issue_date=date(2026, 10, 2),
        xml_sha256=None,
    )
    other = await _invoice(
        ksef_number=None,
        source="manual_pdf",
        pdf_storage_key="payroll_invoices/aa/y.pdf",
        invoice_number="sierpień",
        period_year=2026,
        period_month=8,
        xml_sha256=None,
    )
    response = await app_client.get(
        f"{BASE}/invoices",
        params={"year": 2026, "month": 9},
        headers=_headers(ctx.payroll),
    )
    assert response.status_code == 200
    body = response.json()
    ids = [row["id"] for row in body["invoices"]]
    assert in_month.id in ids and candidate.id in ids and other.id not in ids
    row = next(row for row in body["invoices"] if row["id"] == in_month.id)
    assert row["period"] == "2026-09"
    assert row["net_amount"] == "16400.00"
    assert row["user"]["id"] == ctx.ola.id
    assert row["match_status"] == "unmatched"
    assert body["counts"]["unmatched"] == 2

    half = await app_client.get(
        f"{BASE}/invoices", params={"year": 2026}, headers=_headers(ctx.payroll)
    )
    assert half.status_code == 422


# ── PDF spoza KSeF ───────────────────────────────────────────────────────────


async def test_reczny_pdf_zapis_i_pobranie(app_client, ctx):
    response = await app_client.post(
        f"{BASE}/invoices/manual",
        headers=_headers(ctx.payroll),
        data=_form(ctx),
        files={"file": ("faktura.pdf", PDF, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"] == "manual_pdf"
    assert body["seller_nip"] == OLA_NIP
    assert body["net_amount"] == "2400.00"
    assert body["has_pdf"] is True
    assert body["period"] == "2026-09"

    pdf = await app_client.get(
        f"{BASE}/invoices/{body['id']}/pdf", headers=_headers(ctx.payroll)
    )
    assert pdf.status_code == 200
    assert pdf.content == PDF
    assert pdf.headers["content-type"] == "application/pdf"

    again = await app_client.post(
        f"{BASE}/invoices/manual",
        headers=_headers(ctx.payroll),
        data=_form(ctx, invoice_number="r/1/10/2026"),
        files={"file": ("inna.pdf", PDF + b" ", "application/pdf")},
    )
    assert again.status_code == 409

    async with AsyncSessionLocal() as db:
        events = list(
            await db.scalars(
                select(HrAuditEvent).where(
                    HrAuditEvent.entity_type == "payroll_invoice",
                    HrAuditEvent.entity_id == str(body["id"]),
                )
            )
        )
    assert [event.action for event in events] == ["payroll_invoice_added"]
    assert events[0].sensitivity == "payroll"


@pytest.mark.parametrize(
    ("overrides", "content", "status", "fragment"),
    [
        ({"gross_amount": "2400.01"}, PDF, 422, "Netto + VAT"),
        ({"net_amount": "12,345"}, PDF, 422, "dwoma miejscami"),
        ({}, b"to nie jest pdf", 422, "PDF"),
        ({"seller_nip": ANNA_NIP}, PDF, 409, "inny NIP"),
        ({"issue_date": "2099-01-01"}, PDF, 422, "przyszłości"),
        ({"currency": "GBP"}, PDF, 422, "Waluta"),
    ],
)
async def test_reczny_pdf_odmowy(app_client, ctx, overrides, content, status, fragment):
    response = await app_client.post(
        f"{BASE}/invoices/manual",
        headers=_headers(ctx.payroll),
        data=_form(ctx, **overrides),
        files={"file": ("faktura.pdf", content, "application/pdf")},
    )
    assert response.status_code == status, response.text
    assert fragment in response.json()["detail"]


async def test_reczny_pdf_uzupelnia_nip_osoby(app_client, ctx):
    response = await app_client.post(
        f"{BASE}/invoices/manual",
        headers=_headers(ctx.payroll),
        data=_form(ctx, user_id=str(ctx.anna.id), seller_nip="777-777-77-77"),
        files={"file": ("faktura.pdf", PDF, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    async with AsyncSessionLocal() as db:
        details = await db.scalar(
            select(EmployeeBillingDetails).where(
                EmployeeBillingDetails.user_id == ctx.anna.id
            )
        )
    assert details is not None and details.nip == ANNA_NIP

    missing = await app_client.post(
        f"{BASE}/invoices/manual",
        headers=_headers(ctx.payroll),
        data=_form(ctx, user_id=str(ctx.stranger.id), invoice_number="X/2"),
        files={"file": ("faktura.pdf", PDF + b"2", "application/pdf")},
    )
    assert missing.status_code == 422
    assert "NIP" in missing.json()["detail"]


async def test_pdf_faktury_z_ksef_to_404(app_client, ctx):
    invoice = await _invoice(user_id=ctx.ola.id)
    response = await app_client.get(
        f"{BASE}/invoices/{invoice.id}/pdf", headers=_headers(ctx.payroll)
    )
    assert response.status_code == 404


# ── Przypisanie i pominięcie ─────────────────────────────────────────────────


async def test_przypisz_do_miesiaca(app_client, ctx):
    invoice = await _invoice(user_id=ctx.ola.id)
    response = await app_client.post(
        f"{BASE}/invoices/{invoice.id}/period",
        headers=_headers(ctx.payroll),
        json={"year": 2026, "month": 9},
    )
    assert response.status_code == 200, response.text
    assert response.json()["period"] == "2026-09"

    wrong_person = await app_client.post(
        f"{BASE}/invoices/{invoice.id}/period",
        headers=_headers(ctx.payroll),
        json={"year": 2026, "month": 9, "user_id": ctx.anna.id},
    )
    assert wrong_person.status_code == 422

    async with AsyncSessionLocal() as db:
        row = await db.get(PayrollInvoice, invoice.id)
        period = await db.scalar(
            select(PayrollPeriod).where(
                PayrollPeriod.year == 2026, PayrollPeriod.month == 9
            )
        )
        created = period is None
        if created:
            period = PayrollPeriod(
                year=2026, month=9, status="closed", closed_at=_now()
            )
            db.add(period)
            await db.flush()
        period_id = period.id
        settlement = PayrollSettlement(
            period_id=period.id,
            user_id=ctx.ola.id,
            employment_type="b2b",
            currency="PLN",
            expected_amount=Decimal("1.00"),
            amount_basis="net",
            status="awaiting_document",
        )
        db.add(settlement)
        await db.flush()
        row.settlement_id = settlement.id
        row.match_status = "matched"
        await db.commit()
    try:
        # Dopasowaną do rozliczenia opłaconego nie da się przenieść.
        async with AsyncSessionLocal() as db:
            paid = await db.get(PayrollSettlement, settlement.id)
            paid.status = "paid"
            paid.paid_at = _now()
            paid.paid_source = "statement"
            await db.commit()
        matched = await app_client.post(
            f"{BASE}/invoices/{invoice.id}/period",
            headers=_headers(ctx.payroll),
            json={"year": 2026, "month": 10},
        )
        assert matched.status_code == 409
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(PayrollInvoice).where(PayrollInvoice.id == invoice.id)
            )
            await db.execute(
                delete(PayrollSettlement).where(PayrollSettlement.user_id == ctx.ola.id)
            )
            if created:
                await db.execute(
                    delete(PayrollPeriod).where(PayrollPeriod.id == period_id)
                )
            await db.commit()


async def test_pomin_i_przywroc(app_client, ctx):
    invoice = await _invoice(user_id=ctx.ola.id)
    url = f"{BASE}/invoices/{invoice.id}/ignore"
    headers = _headers(ctx.payroll)
    no_reason = await app_client.post(url, headers=headers, json={"ignored": True})
    assert no_reason.status_code == 422

    ignored = await app_client.post(
        url,
        headers=headers,
        json={"ignored": True, "reason": "Faktura za sprzęt, nie za usługi"},
    )
    assert ignored.status_code == 200
    assert ignored.json()["match_status"] == "ignored"

    restored = await app_client.post(url, headers=headers, json={"ignored": False})
    assert restored.status_code == 200
    assert restored.json()["match_status"] == "unmatched"
    again = await app_client.post(url, headers=headers, json={"ignored": False})
    assert again.status_code == 409

    missing = await app_client.post(
        f"{BASE}/invoices/999999999/ignore", headers=headers, json={"ignored": False}
    )
    assert missing.status_code == 404


# ── Po przeglądzie (17/18.10): VAT w ręcznym PDF-ie ──────────────────────────


async def test_reczny_pdf_vat_ponad_23_procent_netto_422(app_client, ctx):
    response = await app_client.post(
        f"{BASE}/invoices/manual",
        headers=_headers(ctx.payroll),
        data=_form(ctx, vat_amount="600,00", gross_amount="3000.00"),
        files={"file": ("faktura.pdf", PDF, "application/pdf")},
    )
    assert response.status_code == 422, response.text
    assert "23%" in response.json()["detail"]


async def test_reczny_pdf_z_vat_u_osoby_zwolnionej_422(app_client, ctx):
    async with AsyncSessionLocal() as db:
        details = await db.scalar(
            select(EmployeeBillingDetails).where(
                EmployeeBillingDetails.user_id == ctx.ola.id
            )
        )
        details.vat_status = "exempt"
        await db.commit()
    refused = await app_client.post(
        f"{BASE}/invoices/manual",
        headers=_headers(ctx.payroll),
        data=_form(ctx, vat_amount="552,00", gross_amount="2952.00"),
        files={"file": ("faktura.pdf", PDF, "application/pdf")},
    )
    assert refused.status_code == 422, refused.text
    assert "zwolnion" in refused.json()["detail"]
    allowed = await app_client.post(
        f"{BASE}/invoices/manual",
        headers=_headers(ctx.payroll),
        data=_form(ctx),
        files={"file": ("faktura.pdf", PDF, "application/pdf")},
    )
    assert allowed.status_code == 201, allowed.text


# ── Po przeglądzie (17/18.10): odpięcie dopasowanej, nieopłaconej faktury ────


async def _matched_invoice(ctx, *, status: str = "ready"):
    async with AsyncSessionLocal() as db:
        period = await db.scalar(
            select(PayrollPeriod).where(
                PayrollPeriod.year == 2026, PayrollPeriod.month == 9
            )
        )
        created = period is None
        if created:
            period = PayrollPeriod(
                year=2026, month=9, status="closed", closed_at=_now()
            )
            db.add(period)
            await db.flush()
        settlement = PayrollSettlement(
            period_id=period.id,
            user_id=ctx.ola.id,
            employment_type="b2b",
            currency="PLN",
            expected_amount=Decimal("16400.00"),
            amount_basis="net",
            status=status,
            discrepancy_amount=Decimal("0.00"),
            due_on=date(2026, 10, 17),
        )
        if status == "approved":
            settlement.approved_by = ctx.payroll.id
            settlement.approved_at = _now()
        if status == "paid":
            settlement.paid_at = _now()
            settlement.paid_source = "statement"
        db.add(settlement)
        await db.flush()
        invoice = PayrollInvoice(
            source="ksef",
            ksef_number=OLA_INVOICE,
            seller_nip=OLA_NIP,
            user_id=ctx.ola.id,
            invoice_number="FV 9/2026",
            issue_date=date(2026, 10, 3),
            period_year=2026,
            period_month=9,
            currency="PLN",
            net_amount=Decimal("16400.00"),
            vat_amount=Decimal("3772.00"),
            gross_amount=Decimal("20172.00"),
            items=[],
            xml_sha256="a" * 64,
            settlement_id=settlement.id,
            match_status="matched",
        )
        db.add(invoice)
        await db.commit()
        return invoice.id, settlement.id, (period.id if created else None)


async def _cleanup(period_id) -> None:
    if period_id is None:
        return
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(PayrollInvoice).where(PayrollInvoice.seller_nip == OLA_NIP)
        )
        await db.execute(
            delete(PayrollSettlement).where(PayrollSettlement.period_id == period_id)
        )
        await db.execute(delete(PayrollPeriod).where(PayrollPeriod.id == period_id))
        await db.commit()


async def test_pominiecie_dopasowanej_faktury_przelicza_rozliczenie(app_client, ctx):
    invoice_id, settlement_id, period_id = await _matched_invoice(
        ctx, status="approved"
    )
    try:
        response = await app_client.post(
            f"{BASE}/invoices/{invoice_id}/ignore",
            headers=_headers(ctx.payroll),
            json={"ignored": True, "reason": "Ta sama faktura przyszła dwa razy"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["match_status"] == "ignored"
        async with AsyncSessionLocal() as db:
            settlement = await db.get(PayrollSettlement, settlement_id)
            invoice = await db.get(PayrollInvoice, invoice_id)
        assert invoice.settlement_id is None
        # Bez faktury rozliczenie znów czeka na dokument, zatwierdzenie cofnięte.
        assert settlement.status == "awaiting_document"
        assert settlement.approved_by is None and settlement.discrepancy_amount is None
    finally:
        await _cleanup(period_id)


async def test_przeniesienie_dopasowanej_faktury_do_innego_miesiaca(app_client, ctx):
    invoice_id, settlement_id, period_id = await _matched_invoice(ctx)
    try:
        moved = await app_client.post(
            f"{BASE}/invoices/{invoice_id}/period",
            headers=_headers(ctx.payroll),
            json={"year": 2026, "month": 8},
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["period"] == "2026-08"
        async with AsyncSessionLocal() as db:
            settlement = await db.get(PayrollSettlement, settlement_id)
        assert settlement.status == "awaiting_document"
    finally:
        await _cleanup(period_id)


async def test_faktury_przy_oplaconym_rozliczeniu_nie_da_sie_pominac(app_client, ctx):
    invoice_id, settlement_id, period_id = await _matched_invoice(ctx, status="paid")
    try:
        response = await app_client.post(
            f"{BASE}/invoices/{invoice_id}/ignore",
            headers=_headers(ctx.payroll),
            json={"ignored": True, "reason": "Pomyłka"},
        )
        assert response.status_code == 409
        async with AsyncSessionLocal() as db:
            invoice = await db.get(PayrollInvoice, invoice_id)
        assert invoice.match_status == "matched"
    finally:
        await _cleanup(period_id)
