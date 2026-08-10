"""Tests dla /api/help-materials — biblioteka linków do dokumentów firmowych.

Pokrywa:
- RBAC: admin pełne CRUD, non-admin read-only (403 na modyfikacje)
- published_only: non-admin widzi tylko opublikowane, nawet z published_only=false
- Slug: unikalny + sufiks przy kolizji
- Search: ILIKE po title, category i description
- Update PATCH-semantyka częściowa (model_fields_set)
- Walidacja URL: tylko http(s); javascript:/data:/file:/względne → 422
- Sortowanie: sort_order ASC, potem title ASC
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole


# ── Helper: seed user + login (wzorzec z test_procedures.py) ────────────────


async def _seed_user(role: UserRole, label: str = "") -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    suffix = f"-{label}" if label else ""
    email = f"helpmat{suffix}-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Mat"

    async with AsyncSessionLocal() as db:
        existing = await db.scalar(select(User).where(User.email == email))
        if existing is None:
            u = User(
                email=email,
                password_hash=hash_password(password),
                name=f"Mat Test {role.value}",
                role=role,
                is_active=True,
            )
            db.add(u)
            await db.commit()
            await db.refresh(u)
    return email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, f"login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def mat_client() -> AsyncClient:
    from app.main import app
    from app.core.rate_limit import limiter as _limiter

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest_asyncio.fixture
async def admin_headers(mat_client: AsyncClient) -> dict[str, str]:
    email, password = await _seed_user(UserRole.admin, "admin")
    return await _login(mat_client, email, password)


@pytest_asyncio.fixture
async def recruiter_headers(mat_client: AsyncClient) -> dict[str, str]:
    email, password = await _seed_user(UserRole.recruiter, "rek")
    return await _login(mat_client, email, password)


_VALID_URL = "https://example.sharepoint.com/:w:/g/personal/doc.docx?e=AbCd12"


# ── RBAC ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recruiter_cannot_create(mat_client, recruiter_headers):
    resp = await mat_client.post(
        "/api/help-materials",
        headers=recruiter_headers,
        json={
            "category": "Szablony i wzory",
            "title": "Nie powinno przejść",
            "url": _VALID_URL,
        },
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_recruiter_cannot_update(mat_client, admin_headers, recruiter_headers):
    created = await mat_client.post(
        "/api/help-materials",
        headers=admin_headers,
        json={
            "category": "Szablony i wzory",
            "title": f"Baza startowa {uuid.uuid4().hex[:6]}",
            "url": _VALID_URL,
        },
    )
    assert created.status_code == 201
    mid = created.json()["id"]

    resp = await mat_client.put(
        f"/api/help-materials/{mid}",
        headers=recruiter_headers,
        json={"title": "Inny tytuł"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_recruiter_cannot_delete(mat_client, admin_headers, recruiter_headers):
    created = await mat_client.post(
        "/api/help-materials",
        headers=admin_headers,
        json={
            "category": "Szablony i wzory",
            "title": f"Do usunięcia {uuid.uuid4().hex[:6]}",
            "url": _VALID_URL,
        },
    )
    mid = created.json()["id"]

    resp = await mat_client.delete(
        f"/api/help-materials/{mid}", headers=recruiter_headers
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_request_is_rejected(mat_client):
    resp = await mat_client.get("/api/help-materials")
    assert resp.status_code in (401, 403)


# ── Happy path ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_full_crud(mat_client, admin_headers):
    title = f"Szablon do umowy {uuid.uuid4().hex[:6]}"

    create = await mat_client.post(
        "/api/help-materials",
        headers=admin_headers,
        json={
            "category": "Szablony i wzory",
            "title": title,
            "url": _VALID_URL,
            "description": "Wzór umowy B2B",
            "is_editable_template": True,
            "sort_order": 10,
        },
    )
    assert create.status_code == 201, create.text
    created = create.json()
    assert created["title"] == title
    assert created["slug"].startswith("szablon-do-umowy")
    assert created["url"] == _VALID_URL
    assert created["is_editable_template"] is True
    assert created["is_published"] is True
    mid = created["id"]

    # List
    listing = await mat_client.get("/api/help-materials", headers=admin_headers)
    assert listing.status_code == 200
    assert created["slug"] in [m["slug"] for m in listing.json()]

    # Update
    new_url = "https://example.sharepoint.com/:w:/g/personal/inny.docx?e=ZzZz99"
    upd = await mat_client.put(
        f"/api/help-materials/{mid}",
        headers=admin_headers,
        json={"url": new_url, "sort_order": 99},
    )
    assert upd.status_code == 200
    assert upd.json()["url"] == new_url
    assert upd.json()["sort_order"] == 99

    # Delete
    delete = await mat_client.delete(
        f"/api/help-materials/{mid}", headers=admin_headers
    )
    assert delete.status_code == 204

    after = await mat_client.get("/api/help-materials", headers=admin_headers)
    assert created["slug"] not in [m["slug"] for m in after.json()]

    # Powtórny DELETE → 404
    again = await mat_client.delete(f"/api/help-materials/{mid}", headers=admin_headers)
    assert again.status_code == 404


# ── published_only ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_admin_sees_only_published(
    mat_client, admin_headers, recruiter_headers
):
    draft = await mat_client.post(
        "/api/help-materials",
        headers=admin_headers,
        json={
            "category": "Szablony i wzory",
            "title": f"Szkic {uuid.uuid4().hex[:6]}",
            "url": _VALID_URL,
            "is_published": False,
        },
    )
    assert draft.status_code == 201
    slug = draft.json()["slug"]

    # Obok szkicu MUSI istnieć wpis opublikowany — inaczej asercja negatywna
    # niżej („szkicu nie ma na liście") przechodzi także wtedy, gdy rekruter nie
    # widzi NICZEGO. Pusta zakładka czyta się jak utrata danych, więc widoczność
    # asertujemy wprost (wzorzec `rbac-containment-403-reads-as-data-loss`).
    published = await mat_client.post(
        "/api/help-materials",
        headers=admin_headers,
        json={
            "category": "Szablony i wzory",
            "title": f"Opublikowany {uuid.uuid4().hex[:6]}",
            "url": _VALID_URL,
            "is_published": True,
        },
    )
    assert published.status_code == 201
    published_slug = published.json()["slug"]

    # Admin widzi szkic przy published_only=false
    admin_list = await mat_client.get(
        "/api/help-materials",
        headers=admin_headers,
        params={"published_only": "false"},
    )
    assert slug in [m["slug"] for m in admin_list.json()]

    # Recruiter NIE widzi szkicu nawet gdy jawnie poda published_only=false
    rek_list = await mat_client.get(
        "/api/help-materials",
        headers=recruiter_headers,
        params={"published_only": "false"},
    )
    assert rek_list.status_code == 200
    rek_slugs = [m["slug"] for m in rek_list.json()]
    assert slug not in rek_slugs
    assert published_slug in rek_slugs, (
        "rekruter nie widzi opublikowanego materiału — pusta lista to nie to samo "
        "co poprawne odcięcie szkiców"
    )


# ── Slug uniqueness ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_duplicate_title_yields_unique_slug(mat_client, admin_headers):
    title = f"Duplikat {uuid.uuid4().hex[:6]}"
    first = await mat_client.post(
        "/api/help-materials",
        headers=admin_headers,
        json={"category": "Onboarding", "title": title, "url": _VALID_URL},
    )
    second = await mat_client.post(
        "/api/help-materials",
        headers=admin_headers,
        json={"category": "Onboarding", "title": title, "url": _VALID_URL},
    )
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["slug"] != second.json()["slug"]
    assert second.json()["slug"].startswith(first.json()["slug"])


@pytest.mark.asyncio
async def test_slug_transliterates_polish_diacritics(mat_client, admin_headers):
    """„ł" nie rozkłada się przez NFKD — bez mapy ASCII-fold KASUJE tę literę.

    Regresja: „Zupełnie" dawało slug „zupenie", a „współpracy" → „wspopracy".
    Cały UI jest po polsku, więc to nie jest przypadek brzegowy. Pozostałe
    diakrytyki (ą, ć, ę, ń, ó, ś, ź, ż) rozkładają się poprawnie same i ten
    test pilnuje, żeby mapa ich nie zepsuła.
    """
    unique = uuid.uuid4().hex[:6]
    resp = await mat_client.post(
        "/api/help-materials",
        headers=admin_headers,
        json={
            "category": "Szablony i wzory",
            "title": f"Zażółć gęślą jaźń wzór współpracy {unique}",
            "url": _VALID_URL,
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["slug"] == f"zazolc-gesla-jazn-wzor-wspolpracy-{unique}"


# ── Search ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_matches_title_category_and_description(mat_client, admin_headers):
    unique = uuid.uuid4().hex[:6]

    a = await mat_client.post(
        "/api/help-materials",
        headers=admin_headers,
        json={
            "category": f"Onboarding NORDEA {unique}",
            "title": f"Formularz zgłoszeniowy {unique}",
            "url": _VALID_URL,
            "description": "dokument klienta",
        },
    )
    b = await mat_client.post(
        "/api/help-materials",
        headers=admin_headers,
        json={
            "category": "Szablony i wzory",
            "title": f"Profil Championa {unique}",
            "url": _VALID_URL,
            "description": f"opisowe-slowo-{unique} w środku",
        },
    )
    assert a.status_code == 201 and b.status_code == 201

    # match po tytule
    by_title = await mat_client.get(
        "/api/help-materials",
        headers=admin_headers,
        params={"q": f"formularz zgłoszeniowy {unique}"},
    )
    assert by_title.status_code == 200
    titles = [m["title"] for m in by_title.json()]
    assert any(f"Formularz zgłoszeniowy {unique}" in t for t in titles)
    assert not any(f"Profil Championa {unique}" in t for t in titles)

    # match po kategorii
    by_category = await mat_client.get(
        "/api/help-materials",
        headers=admin_headers,
        params={"q": f"NORDEA {unique}"},
    )
    assert by_category.status_code == 200
    assert any(
        f"Formularz zgłoszeniowy {unique}" in m["title"] for m in by_category.json()
    )

    # match po opisie
    by_description = await mat_client.get(
        "/api/help-materials",
        headers=admin_headers,
        params={"q": f"opisowe-slowo-{unique}"},
    )
    assert by_description.status_code == 200
    assert any(
        f"Profil Championa {unique}" in m["title"] for m in by_description.json()
    )


@pytest.mark.asyncio
async def test_search_treats_wildcards_as_literal_characters(mat_client, admin_headers):
    """`%` i `_` z pola wyszukiwania to ZNAKI, nie operatory ILIKE.

    Bez escapowania wpisanie `%` zwracało całą bibliotekę zamiast komunikatu
    o braku wyników, a `BNP_CARDIF` trafiało w „BNP CARDIF".
    """
    unique = uuid.uuid4().hex[:6]

    async def _create(title: str) -> str:
        resp = await mat_client.post(
            "/api/help-materials",
            headers=admin_headers,
            json={
                "category": "Szablony i wzory",
                "title": title,
                "url": _VALID_URL,
            },
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["slug"]

    percent_slug = await _create(f"Rabat 100% {unique}")
    plain_slug = await _create(f"Rabat 100 {unique}")
    underscore_slug = await _create(f"BNP_CARDIF {unique}")
    space_slug = await _create(f"BNP CARDIF {unique}")

    async def _slugs(q: str) -> list[str]:
        resp = await mat_client.get(
            "/api/help-materials", headers=admin_headers, params={"q": q}
        )
        assert resp.status_code == 200
        return [m["slug"] for m in resp.json()]

    # `%` w środku frazy nie może „przeskoczyć" brakującego znaku
    hits = await _slugs(f"100% {unique}")
    assert percent_slug in hits
    assert plain_slug not in hits

    # `_` dopasowuje wyłącznie samo podkreślenie, nie dowolny znak
    hits = await _slugs(f"BNP_CARDIF {unique}")
    assert underscore_slug in hits
    assert space_slug not in hits

    # samo `%` nie zwraca całej biblioteki
    hits = await _slugs("%")
    assert plain_slug not in hits
    assert space_slug not in hits


# ── Długość slugu (VARCHAR(255) odrzuca, nie obcina) ────────────────────────


@pytest.mark.asyncio
async def test_long_title_and_collision_do_not_overflow_slug(mat_client, admin_headers):
    """Tytuł na granicy 255 znaków + sufiks kolizji musi się zmieścić w kolumnie."""
    unique = uuid.uuid4().hex[:8]
    title = (unique + "a" * 255)[:255]

    slugs = []
    for _ in range(2):
        resp = await mat_client.post(
            "/api/help-materials",
            headers=admin_headers,
            json={
                "category": "Szablony i wzory",
                "title": title,
                "url": _VALID_URL,
            },
        )
        assert resp.status_code == 201, resp.text
        slug = resp.json()["slug"]
        assert len(slug) <= 255
        slugs.append(slug)

    assert slugs[0] != slugs[1], "kolizja musi dać osobny slug, nie duplikat"


@pytest.mark.asyncio
async def test_expanding_transliteration_does_not_overflow_slug(
    mat_client, admin_headers
):
    """`ß`→`ss` i NFKD ligatur POTRAFIĄ wydłużyć slug ponad długość tytułu."""
    for filler in ("ß", "ﬄ", "Ⅷ"):
        resp = await mat_client.post(
            "/api/help-materials",
            headers=admin_headers,
            json={
                "category": "Szablony i wzory",
                "title": filler * 255,
                "url": _VALID_URL,
            },
        )
        assert resp.status_code == 201, f"{filler!r}: {resp.text}"
        assert len(resp.json()["slug"]) <= 255


# ── sort_order poza zakresem INT4 ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_sort_order_out_of_int32_range_is_rejected_with_422(
    mat_client, admin_headers
):
    """Poza zakresem INTEGER-a ma być 422 z nazwą pola, nie 500 z bazy."""
    base = {
        "category": "Szablony i wzory",
        "title": f"Zakres {uuid.uuid4().hex[:6]}",
        "url": _VALID_URL,
    }

    too_big = await mat_client.post(
        "/api/help-materials",
        headers=admin_headers,
        json={**base, "sort_order": 3_000_000_000},
    )
    assert too_big.status_code == 422, too_big.text

    too_small = await mat_client.post(
        "/api/help-materials",
        headers=admin_headers,
        json={**base, "sort_order": -3_000_000_000},
    )
    assert too_small.status_code == 422, too_small.text

    created = await mat_client.post(
        "/api/help-materials", headers=admin_headers, json={**base, "sort_order": 42}
    )
    assert created.status_code == 201, created.text

    updated = await mat_client.put(
        f"/api/help-materials/{created.json()['id']}",
        headers=admin_headers,
        json={"sort_order": 10**20},
    )
    assert updated.status_code == 422, updated.text


# ── Update: PATCH-semantyka częściowa ───────────────────────────────────────


@pytest.mark.asyncio
async def test_partial_update_preserves_omitted_fields(mat_client, admin_headers):
    """Zmiana samego sort_order NIE może wyzerować url/description/title."""
    created = await mat_client.post(
        "/api/help-materials",
        headers=admin_headers,
        json={
            "category": "Szablony i wzory",
            "title": f"Notatka po screeningu {uuid.uuid4().hex[:6]}",
            "url": _VALID_URL,
            "description": "Wzór notatki",
            "is_editable_template": True,
            "sort_order": 5,
        },
    )
    assert created.status_code == 201
    before = created.json()
    mid = before["id"]

    upd = await mat_client.put(
        f"/api/help-materials/{mid}",
        headers=admin_headers,
        json={"sort_order": 42},
    )
    assert upd.status_code == 200
    after = upd.json()

    assert after["sort_order"] == 42
    assert after["url"] == before["url"]
    assert after["description"] == before["description"]
    assert after["title"] == before["title"]
    assert after["category"] == before["category"]
    assert after["is_editable_template"] is True
    assert after["is_published"] is True
    assert after["slug"] == before["slug"]


@pytest.mark.asyncio
async def test_update_can_clear_description_explicitly(mat_client, admin_headers):
    """Jawne null czyści opis — inaczej niż pominięcie pola."""
    created = await mat_client.post(
        "/api/help-materials",
        headers=admin_headers,
        json={
            "category": "Onboarding",
            "title": f"Z opisem {uuid.uuid4().hex[:6]}",
            "url": _VALID_URL,
            "description": "do skasowania",
        },
    )
    mid = created.json()["id"]

    upd = await mat_client.put(
        f"/api/help-materials/{mid}",
        headers=admin_headers,
        json={"description": None},
    )
    assert upd.status_code == 200
    assert upd.json()["description"] is None


@pytest.mark.asyncio
async def test_update_title_regenerates_slug(mat_client, admin_headers):
    created = await mat_client.post(
        "/api/help-materials",
        headers=admin_headers,
        json={
            "category": "Onboarding",
            "title": "Pierwotny tytuł materiału",
            "url": _VALID_URL,
        },
    )
    mid = created.json()["id"]
    old_slug = created.json()["slug"]

    upd = await mat_client.put(
        f"/api/help-materials/{mid}",
        headers=admin_headers,
        json={"title": "Zupełnie nowy tytuł materiału"},
    )
    assert upd.status_code == 200
    new_slug = upd.json()["slug"]
    assert new_slug != old_slug
    assert "zupelnie" in new_slug


# ── Walidacja URL (stored-XSS) ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_url",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "  javascript:alert(1)  ",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
        "/wzgledny/adres.docx",
        "example.sharepoint.com/doc.docx",
        "ftp://example.com/doc.docx",
        "https://",
        "",
        "   ",
        "java\nscript:alert(1)",
    ],
)
@pytest.mark.asyncio
async def test_create_rejects_non_http_urls(mat_client, admin_headers, bad_url):
    resp = await mat_client.post(
        "/api/help-materials",
        headers=admin_headers,
        json={
            "category": "Szablony i wzory",
            "title": f"Złośliwy {uuid.uuid4().hex[:6]}",
            "url": bad_url,
        },
    )
    assert resp.status_code == 422, f"{bad_url!r} przeszedł walidację: {resp.text}"


@pytest.mark.asyncio
async def test_update_rejects_non_http_url(mat_client, admin_headers):
    created = await mat_client.post(
        "/api/help-materials",
        headers=admin_headers,
        json={
            "category": "Onboarding",
            "title": f"Poprawny {uuid.uuid4().hex[:6]}",
            "url": _VALID_URL,
        },
    )
    mid = created.json()["id"]

    resp = await mat_client.put(
        f"/api/help-materials/{mid}",
        headers=admin_headers,
        json={"url": "javascript:alert(1)"},
    )
    assert resp.status_code == 422

    # URL w bazie pozostał nietknięty
    listing = await mat_client.get("/api/help-materials", headers=admin_headers)
    row = next(m for m in listing.json() if m["id"] == mid)
    assert row["url"] == _VALID_URL


@pytest.mark.asyncio
async def test_accepts_plain_http_and_https(mat_client, admin_headers):
    for url in (
        "http://intranet.local/dokument.docx",
        "https://example.sharepoint.com/:x:/g/plik.xlsx?e=Q1w2E3",
    ):
        resp = await mat_client.post(
            "/api/help-materials",
            headers=admin_headers,
            json={
                "category": "Onboarding",
                "title": f"OK {uuid.uuid4().hex[:6]}",
                "url": url,
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["url"] == url


# ── Sortowanie ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_sorted_by_sort_order_then_title(mat_client, admin_headers):
    unique = uuid.uuid4().hex[:6]
    category = f"Sortowanie {unique}"

    # Wstawiamy w kolejności celowo odwrotnej do oczekiwanej.
    for title, sort_order in (
        (f"C {unique}", 20),
        (f"B {unique}", 10),
        (f"A {unique}", 10),
    ):
        resp = await mat_client.post(
            "/api/help-materials",
            headers=admin_headers,
            json={
                "category": category,
                "title": title,
                "url": _VALID_URL,
                "sort_order": sort_order,
            },
        )
        assert resp.status_code == 201

    listing = await mat_client.get(
        "/api/help-materials", headers=admin_headers, params={"q": category}
    )
    assert listing.status_code == 200
    titles = [m["title"] for m in listing.json()]
    assert titles == [f"A {unique}", f"B {unique}", f"C {unique}"]
