"""Regresja: /api/reports/power-calling NIE ocenia ludzi zmyślonym mianownikiem.

Do 2026-08-31 endpoint dzielił tygodniową liczbę weryfikacji przez stałą
`POWER_CALLING_WORKDAYS = 5` i publikował imienną listę „poniżej progu".
Tydzień urlopu dawał zero i wyglądał identycznie jak tydzień lenistwa, więc
osoba na urlopie trafiała na listę pod nazwiskiem. NEXUS nie zna nieobecności
(`days_worked` istnieje wyłącznie w martwym `dr_kpi_body_leasing`), więc
dziennego mianownika NIE MA i raport nie wolno mu udawać, że ma.

Test broni tego kontraktu: dopóki nie ma danych o dniach roboczych, każdy
wiersz jest `not_assessable`, a pola oceny są `None` — nie `0` i nie `False`.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole


async def _seed_user(role: UserRole, label: str) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"pc-{label}-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!PowerCall"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            name=f"PC {label} {unique}",
            password_hash=hash_password(password),
            role=role,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id, email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def pc_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_power_calling_reports_no_daily_denominator(pc_client: AsyncClient):
    """Koperta nie niesie stałej liczby dni roboczych ani liczby „spełnili próg"."""
    _, email, password = await _seed_user(UserRole.admin, "envelope")
    headers = await _login(pc_client, email, password)

    resp = await pc_client.get("/api/reports/power-calling", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Mianownika nie znamy — i mówimy to wprost, zamiast podstawiać liczbę.
    assert body["workdays"] is None
    assert body["workdays_source"] == "unavailable"
    assert body["meets_target_count"] is None

    # Nikt nie jest oceniony, więc obie listy ocen są puste.
    assert body["below_target"] == []
    assert body["met_target"] == []
    assert body["not_assessable_count"] == len(body["entries"])

    # Próg zostaje, ale jako TYGODNIOWY (3/dzień x 5 dni) — jedyna uczciwa
    # miara bez danych o nieobecnościach.
    assert body["weekly_target"] == body["target_per_day"] * 5
    assert "dzień roboczy" not in body["requirement_text"]
    assert "nieobecnoś" in body["requirement_text"]


@pytest.mark.asyncio
async def test_power_calling_entries_are_not_assessable(pc_client: AsyncClient):
    """Wiersz osoby bez weryfikacji nie jest „poniżej progu" — jest nieoceniony.

    To jest ta regresja: `meets_target` musi być `None`, bo `False` znaczy
    „sprawdziliśmy i nie spełnia", a my nie sprawdziliśmy niczego.
    """
    _, email, password = await _seed_user(UserRole.admin, "entries")
    headers = await _login(pc_client, email, password)

    resp = await pc_client.get("/api/reports/power-calling", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["entries"] is body["not_assessable"] or (
        body["entries"] == body["not_assessable"]
    )
    for entry in body["entries"]:
        assert entry["per_day"] is None, entry
        assert entry["workdays"] is None, entry
        assert entry["progress_pct"] is None, entry
        assert entry["meets_target"] is None, entry
        assert entry["workdays_source"] == "unavailable", entry
        assert entry["reason"] == "no_workday_data", entry
        # Sama liczba weryfikacji zostaje — jest prawdziwa i policzalna.
        assert isinstance(entry["verifications_week"], int), entry


@pytest.mark.asyncio
async def test_power_calling_module_has_no_fabricated_workday_constant():
    """Strażnik: nikt nie przywraca stałego mianownika pod inną nazwą.

    Podmiana „5" na „21" albo na „kalendarzowe dni robocze" to ten sam defekt
    z większą liczbą — dopóki nie znamy nieobecności, każdy stały dzielnik
    imiennie oskarża osobę na urlopie.
    """
    import inspect

    from app.api import reports

    assert not hasattr(reports, "POWER_CALLING_WORKDAYS")

    src = inspect.getsource(reports.report_power_calling)
    assert "/ 5" not in src
    assert "/ 21" not in src
