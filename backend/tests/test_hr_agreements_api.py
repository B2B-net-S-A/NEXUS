"""Umowy z ludźmi (etap 5, E5) — trasy: bramki, wzory, szkice.

Ścieżki odmowy: wyłączony moduł (404 poza adminem), bez Kadr i Płac (403
z nazwą uprawnień), przełożony i sama osoba nic nie widzą, Płace tylko
czytają, nikt nie przygotowuje umowy ze sobą, wzór z polem spoza listy
(np. PESEL) albo sięgający poza dane umowy jest odrzucany, stawka zlecenia
poniżej minimum roku, zlecenie bez potwierdzania godzin, aneks nie od 1. dnia
miesiąca, druga umowa w toku. Dane fikcyjne.
"""

from __future__ import annotations

import io
import zipfile
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.hr_agreement import HrAgreement
from app.models.hr_ops import HrAuditEvent
from app.models.hr_payroll import EmployeeRate
from app.models.hr_profile import EmployeeProfile
from app.services.hr.agreements import SETTINGS_KEY
from tests.hr_agreements_seed import (
    BODY,
    PREFIX,
    agreements_on_fixture,  # noqa: F401  (fixture „agreements_on”)
    docx_text,
    first_of_next_month,
    make_docx,
    make_template,
)
from tests.hr_settlements_seed import headers, make_user, set_setting


@pytest.fixture(scope="module", autouse=True)
def agreements_routes():
    """Trasy modułu w aplikacji testowej, dopóki koordynator nie wepnie ich w ``main.py``."""

    from app.api import hr_agreements
    from app.main import app

    before = list(app.router.routes)
    added = False
    if f"{PREFIX}/settings" not in {getattr(route, "path", "") for route in before}:
        app.include_router(hr_agreements.router, prefix=PREFIX, tags=["hr"])
        added = True
    yield
    if added:
        app.router.routes[:] = before


def _upload(kind: str, name: str, content: bytes, filename: str = "wzor.docx"):
    return {
        "files": {"file": (filename, content, "application/octet-stream")},
        "data": {"kind": kind, "name": name},
    }


def _draft(template_id: int, **values) -> dict:
    body = {
        "template_id": template_id,
        "hourly_rate": "32.00",
        "currency": "PLN",
        "start_date": first_of_next_month().isoformat(),
        "hours_confirmation": True,
    }
    body.update(values)
    return body


# ── Bramki ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_module_switch_off_is_404_except_admin(app_client, agreements_on) -> None:
    team = agreements_on
    admin = await make_user("admin", profile=False)
    await set_setting(SETTINGS_KEY, {"enabled": False})
    url = f"{PREFIX}/people/{team.mandate.id}"
    assert (await app_client.get(url, headers=headers(team.hr))).status_code == 404
    assert (await app_client.get(url, headers=headers(admin))).status_code == 200
    # Stan przełącznika Kadry widzą, ale przełącza tylko admin.
    settings = await app_client.get(f"{PREFIX}/settings", headers=headers(team.hr))
    assert settings.status_code == 200 and settings.json()["enabled"] is False
    refused = await app_client.put(
        f"{PREFIX}/settings", json={"enabled": True}, headers=headers(team.hr)
    )
    assert refused.status_code == 403
    switched = await app_client.put(
        f"{PREFIX}/settings", json={"enabled": True}, headers=headers(admin)
    )
    assert switched.status_code == 200 and switched.json()["enabled"] is True
    assert (await app_client.get(url, headers=headers(team.hr))).status_code == 200


@pytest.mark.asyncio
async def test_only_people_admin_and_payroll_read_and_only_people_admin_writes(
    app_client, agreements_on
) -> None:
    team = agreements_on
    template_id = await make_template()
    url = f"{PREFIX}/people/{team.mandate.id}"
    # Przełożony, sama osoba i rekruter bez uprawnień — 403 z nazwą uprawnień.
    outsider = await make_user("recruiter", profile=False)
    for user in (team.boss, team.mandate, outsider):
        refused = await app_client.get(url, headers=headers(user))
        assert refused.status_code == 403
        assert refused.json()["detail"]["permissions"] == ["people_admin", "payroll"]
    # Płace czytają, ale nie przygotowują umów.
    seen = await app_client.get(url, headers=headers(team.payroll))
    assert seen.status_code == 200 and seen.json()["can_write"] is False
    refused = await app_client.post(
        url, json=_draft(template_id), headers=headers(team.payroll)
    )
    assert refused.status_code == 403
    assert refused.json()["detail"]["permission"] == "people_admin"
    assert (
        await app_client.get(f"{PREFIX}/templates", headers=headers(team.payroll))
    ).status_code == 403


@pytest.mark.asyncio
@pytest.mark.usefixtures("agreements_on")
async def test_nobody_prepares_own_agreement(app_client) -> None:
    template_id = await make_template()
    # Osoba z Kadr, która sama ma kartotekę, nie przygotowuje umowy ze sobą.
    hr_with_profile = await make_user(
        "recruiter", grants=("people_admin",), employment_type="zlecenie"
    )
    refused = await app_client.post(
        f"{PREFIX}/people/{hr_with_profile.id}",
        json=_draft(template_id),
        headers=headers(hr_with_profile),
    )
    assert refused.status_code == 403
    assert "ze sobą" in refused.json()["detail"]


# ── Wzory ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_template_upload_versions_and_sample(app_client, agreements_on) -> None:
    team = agreements_on
    created = await app_client.post(
        f"{PREFIX}/templates",
        headers=headers(team.hr),
        **_upload("zlecenie", "Zlecenie — recepcja", make_docx(*BODY)),
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]
    second = await app_client.post(
        f"{PREFIX}/templates/{template_id}/versions",
        headers=headers(team.hr),
        files={"file": ("wzor-v2.docx", make_docx(*BODY, "Wersja druga."), "x")},
    )
    assert second.status_code == 201, second.text
    assert second.json()["version"] == 2
    listing = (
        await app_client.get(f"{PREFIX}/templates", headers=headers(team.hr))
    ).json()
    item = next(row for row in listing["items"] if row["id"] == template_id)
    assert [v["version"] for v in item["versions"]] == [2, 1]
    assert "person_name" in {row["field"] for row in listing["fields"]}
    sample = await app_client.get(
        f"{PREFIX}/templates/versions/{item['versions'][0]['id']}/sample",
        headers=headers(team.hr),
    )
    assert sample.status_code == 200
    text = docx_text(sample.content)
    assert "Anna Przykładowa" in text and "32,00 PLN brutto" in text
    duplicate = await app_client.post(
        f"{PREFIX}/templates",
        headers=headers(team.hr),
        **_upload("zlecenie", "zlecenie — RECEPCJA", make_docx(*BODY)),
    )
    assert duplicate.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lines", "message"),
    [
        (
            ("{{ person_name }} {{ rate }} {{ start_date }} PESEL: {{ pesel }}",),
            "pesel",
        ),
        (("{{ person_name }} {{ rate }}",), "start_date"),
        (
            ("{{ person_name.__class__ }} {{ rate }} {{ start_date }}",),
            "poza dane umowy",
        ),
        (
            (
                "{% for x in person_name %}{{ x }}{% endfor %} {{ rate }} {{ start_date }}",
            ),
            "Pętla",
        ),
    ],
)
async def test_template_with_unknown_field_or_escape_is_refused(
    app_client, agreements_on, lines, message
) -> None:
    team = agreements_on
    refused = await app_client.post(
        f"{PREFIX}/templates",
        headers=headers(team.hr),
        **_upload("zlecenie", "Zły wzór", make_docx(*lines)),
    )
    assert refused.status_code == 422, refused.text
    assert message in refused.json()["detail"]


@pytest.mark.asyncio
async def test_template_with_macro_part_or_not_docx_is_refused(
    app_client, agreements_on
) -> None:
    team = agreements_on
    buffer = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(make_docx(*BODY))) as source,
        zipfile.ZipFile(buffer, "w") as target,
    ):
        for entry in source.infolist():
            target.writestr(entry, source.read(entry))
        target.writestr("word/vbaProject.bin", b"makro")
    macro = await app_client.post(
        f"{PREFIX}/templates",
        headers=headers(team.hr),
        **_upload("zlecenie", "Z makrem", buffer.getvalue()),
    )
    assert macro.status_code == 422 and "makr" in macro.json()["detail"]
    pdf = await app_client.post(
        f"{PREFIX}/templates",
        headers=headers(team.hr),
        **_upload("zlecenie", "PDF", b"%PDF-1.4", filename="wzor.pdf"),
    )
    assert pdf.status_code == 422


@pytest.mark.asyncio
async def test_retired_template_is_not_offered_for_new_agreements(
    app_client, agreements_on
) -> None:
    team = agreements_on
    template_id = await make_template()
    retired = await app_client.patch(
        f"{PREFIX}/templates/{template_id}",
        json={"is_active": False},
        headers=headers(team.hr),
    )
    assert retired.status_code == 200 and retired.json()["is_active"] is False
    refused = await app_client.post(
        f"{PREFIX}/people/{team.mandate.id}",
        json=_draft(template_id),
        headers=headers(team.hr),
    )
    assert refused.status_code == 422 and "wycofany" in refused.json()["detail"]


# ── Szkic ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_draft_with_defaults_and_audit(app_client, agreements_on) -> None:
    team = agreements_on
    template_id = await make_template()
    overview = (
        await app_client.get(
            f"{PREFIX}/people/{team.mandate.id}", headers=headers(team.hr)
        )
    ).json()
    assert overview["defaults"]["coordinator_user_id"] == team.boss.id
    assert overview["defaults"]["payout_day"] == 10
    created = await app_client.post(
        f"{PREFIX}/people/{team.mandate.id}",
        json=_draft(template_id),
        headers=headers(team.hr),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "draft" and body["kind"] == "agreement"
    assert body["employment_type"] == "zlecenie" and body["rate_basis"] == "brutto"
    assert body["coordinator_user_id"] == team.boss.id
    assert body["payout_day"] == 10 and body["warning"] is None
    assert body["actions"]["mark_signed"] is True and body["actions"]["send"] is False
    async with AsyncSessionLocal() as db:
        event = await db.scalar(
            select(HrAuditEvent).where(
                HrAuditEvent.entity_type == "hr_agreement",
                HrAuditEvent.entity_id == str(body["id"]),
                HrAuditEvent.action == "agreement_created",
            )
        )
    assert event is not None and event.sensitivity == "payroll"
    again = await app_client.post(
        f"{PREFIX}/people/{team.mandate.id}",
        json=_draft(template_id),
        headers=headers(team.hr),
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_mandate_minimum_rate_and_hours_confirmation(
    app_client, agreements_on
) -> None:
    team = agreements_on
    template_id = await make_template()
    url = f"{PREFIX}/people/{team.mandate.id}"
    low = await app_client.post(
        url, json=_draft(template_id, hourly_rate="31.39"), headers=headers(team.hr)
    )
    assert low.status_code == 422
    assert "Minimalna stawka na zleceniu" in low.json()["detail"]
    no_hours = await app_client.post(
        url,
        json=_draft(template_id, hours_confirmation=False),
        headers=headers(team.hr),
    )
    assert no_hours.status_code == 422 and "art. 8b" in no_hours.json()["detail"]
    # Minimum dotyczy zlecenia — B2B z tą samą stawką przechodzi.
    b2b_template = await make_template("b2b")
    ok = await app_client.post(
        f"{PREFIX}/people/{team.b2b.id}",
        json=_draft(b2b_template, hourly_rate="20.00", hours_confirmation=False),
        headers=headers(team.hr),
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["rate_basis"] == "netto" and ok.json()["payout_day"] is None


@pytest.mark.asyncio
async def test_annex_starts_on_first_of_month_and_mid_month_rate_conflict(
    app_client, agreements_on
) -> None:
    team = agreements_on
    annex_template = await make_template("annex")
    start = first_of_next_month()
    mid = await app_client.post(
        f"{PREFIX}/people/{team.mandate.id}",
        json=_draft(
            annex_template, start_date=(start + timedelta(days=14)).isoformat()
        ),
        headers=headers(team.hr),
    )
    assert mid.status_code == 422 and "1. dnia miesiąca" in mid.json()["detail"]
    # Umowa od połowy miesiąca, gdy osoba ma już inną stawkę na ten miesiąc.
    async with AsyncSessionLocal() as db:
        db.add(
            EmployeeRate(
                user_id=team.mandate.id,
                hourly_rate=Decimal("35.00"),
                currency="PLN",
                effective_from=start,
            )
        )
        await db.commit()
    template_id = await make_template()
    conflict = await app_client.post(
        f"{PREFIX}/people/{team.mandate.id}",
        json=_draft(template_id, start_date=(start + timedelta(days=14)).isoformat()),
        headers=headers(team.hr),
    )
    assert conflict.status_code == 422
    assert "od 1. dnia miesiąca" in conflict.json()["detail"]
    # Ta sama stawka co obowiązująca — umowa od połowy miesiąca przechodzi.
    same = await app_client.post(
        f"{PREFIX}/people/{team.mandate.id}",
        json=_draft(
            template_id,
            hourly_rate="35.00",
            start_date=(start + timedelta(days=14)).isoformat(),
        ),
        headers=headers(team.hr),
    )
    assert same.status_code == 201, same.text


@pytest.mark.asyncio
async def test_person_without_profile_or_exited_gets_no_agreement(
    app_client, agreements_on
) -> None:
    team = agreements_on
    template_id = await make_template()
    stranger = await make_user("recruiter", profile=False)
    missing = await app_client.post(
        f"{PREFIX}/people/{stranger.id}",
        json=_draft(template_id),
        headers=headers(team.hr),
    )
    assert missing.status_code == 404
    async with AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == team.mandate.id)
        )
        profile.employment_status = "exited"
        await db.commit()
    exited = await app_client.post(
        f"{PREFIX}/people/{team.mandate.id}",
        json=_draft(template_id),
        headers=headers(team.hr),
    )
    assert exited.status_code == 409


@pytest.mark.asyncio
async def test_update_draft_and_download_filled_docx(app_client, agreements_on) -> None:
    team = agreements_on
    template_id = await make_template()
    created = (
        await app_client.post(
            f"{PREFIX}/people/{team.mandate.id}",
            json=_draft(template_id),
            headers=headers(team.hr),
        )
    ).json()
    end = first_of_next_month(7) - timedelta(days=1)
    updated = await app_client.patch(
        f"{PREFIX}/{created['id']}",
        json={"hourly_rate": "33,50", "end_date": end.isoformat()},
        headers=headers(team.hr),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["hourly_rate"] == "33.50"
    filled = await app_client.get(
        f"{PREFIX}/{created['id']}/docx", headers=headers(team.hr)
    )
    assert filled.status_code == 200
    text = docx_text(filled.content)
    assert "Celina Testowa" in text and "33,50 PLN brutto" in text
    assert "trzydzieści trzy złote 50/100" in text
    assert f"do {end:%d.%m.%Y}" in text and "Marta Przełożona" in text
    pdf = await app_client.get(
        f"{PREFIX}/{created['id']}/pdf", headers=headers(team.payroll)
    )
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    # Płace oglądają, ale nie zmieniają szkicu.
    refused = await app_client.patch(
        f"{PREFIX}/{created['id']}",
        json={"hourly_rate": "40.00"},
        headers=headers(team.payroll),
    )
    assert refused.status_code == 403


@pytest.mark.asyncio
async def test_end_before_start_and_bad_rate_are_refused(
    app_client, agreements_on
) -> None:
    team = agreements_on
    template_id = await make_template()
    start = first_of_next_month()
    url = f"{PREFIX}/people/{team.mandate.id}"
    for values in (
        {"end_date": (start - timedelta(days=1)).isoformat()},
        {"hourly_rate": "abc"},
        {"hourly_rate": "0"},
        {"hourly_rate": "32.001"},
        {"currency": "GBP"},
        {
            "start_date": (
                business_today().replace(day=1) - timedelta(days=500)
            ).isoformat()
        },
    ):
        refused = await app_client.post(
            url, json=_draft(template_id, **values), headers=headers(team.hr)
        )
        assert refused.status_code == 422, (values, refused.text)
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(HrAgreement.id).where(HrAgreement.user_id == team.mandate.id)
            )
            is None
        )


def test_every_route_has_named_hr_gate() -> None:
    """Każda trasa modułu ma bramkę ``require_hr_*`` (kontrakt tras jak w strażniku)."""

    from app.api import hr_agreements

    def gates(route) -> list[str]:
        stack, names = [route.dependant], []
        while stack:
            node = stack.pop()
            call = getattr(node, "call", None)
            if call is not None:
                names.append(getattr(call, "__qualname__", ""))
            stack.extend(node.dependencies)
        return [name for name in names if "require_hr_" in name]

    routes = [
        route for route in hr_agreements.router.routes if hasattr(route, "dependant")
    ]
    assert len(routes) >= 19
    for route in routes:
        assert gates(route), (
            f"{sorted(route.methods)} {route.path} bez bramki require_hr_*"
        )
