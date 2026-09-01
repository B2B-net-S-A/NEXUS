"""Plakietki ostrzeżeń przy osobie — kontrakt, którego złamanie jest defektem.

Wiersz w `user_performance_flags` to imienna OCENA PRACOWNIKA widoczna całemu
zespołowi. Testy pilnują pięciu reguł, z których każda chroni przed konkretną
szkodą, a nie przed „brzydkim kodem":

1. **Zapis tylko admin, odczyt każda rola.** Ocena, którą może postawić
   dowolna zalogowana osoba, jest bronią; ocena, której nie widzi połowa
   zespołu, jest plotką.
2. **Wygaszenie ZACHOWUJE wiersz** razem z autorem, datą postawienia i datą
   zdjęcia. Skasowany wiersz odpowiada „nikt nigdy tego nie postawił", i to
   jest odpowiedź nieprawdziwa.
3. **Wygaszonej flagi nie da się wskrzesić.** Wskrzeszenie musiałoby wyczyścić
   `cleared_at`/`cleared_by` — czyli skasować dokładnie tę część historii, dla
   której wiersz zostaje w bazie.
4. **`note` jest opcjonalny**, a pusty tekst to BRAK notatki (nie notatka
   pusta, która renderuje się jako ucięta linijka).
5. **Nieznany `flag_type` odpada na wejściu** (422), a nie odbija się od
   CHECK-a w bazie jako surowy IntegrityError.

Szósty test pilnuje, żeby katalog typów w kodzie i CHECK w migracji 0258 nie
rozjechały się cicho — rozjazd oznacza typ, który przechodzi walidację API
i wywala się dopiero przy INSERT.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole
from app.models.user_performance_flag import (
    PERFORMANCE_FLAG_TYPES,
    UserPerformanceFlag,
)

_BACKEND = Path(__file__).resolve().parents[1]
_MIGRATION = _BACKEND / "alembic" / "versions" / "0258_user_performance_flags.py"

# ── Katalog typów: kod vs CHECK w migracji ─────────────────────────────────


def test_migration_check_matches_code_catalogue():
    """CHECK w bazie musi znać DOKŁADNIE te typy, co enum w kodzie."""
    text = _MIGRATION.read_text(encoding="utf-8")
    match = re.search(r"flag_type IN \(([^)]*)\)", text)
    assert match, "Nie znalazłem CHECK-a `flag_type IN (...)` w migracji 0258"
    in_migration = set(re.findall(r"'([a-z_]+)'", match.group(1)))
    assert in_migration == set(PERFORMANCE_FLAG_TYPES)


# ── Fixtures ───────────────────────────────────────────────────────────────
#
# Router montujemy na WŁASNEJ instancji FastAPI, nie na `app.main.app`.
#
# Dwa powody, oba twarde. Po pierwsze, `main.py` jest w tej zmianie
# zablokowany — montaż należy do integratora (patrz raport). Po drugie,
# `include_router` na współdzielonym `app.main.app` z poziomu fikstury
# zmienia GLOBALNY inwentarz tras na resztę sesji pytest, więc
# `test_route_authz_contract.py` zobaczyłby trasę, której nie ma jeszcze
# w `_BARE_BASELINE`, i wywalił się w pliku, który o tej zmianie nic nie wie.
# Czerwień wędrowałaby wtedy razem z podziałem na shardy.
#
# Prefiks jest tu jedyną kopią kontraktu z integratorem — musi być identyczny
# z tym w `main.py`.

_BASE = "/api/insights/performance-flags"


def _build_app():
    from fastapi import FastAPI

    from app.api import insights_performance_flags

    test_app = FastAPI()
    test_app.include_router(insights_performance_flags.router, prefix=_BASE)
    return test_app


async def _seed_user(role: UserRole, *, is_active: bool = True) -> User:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"pflag-{role.value}-{unique}@example.com",
            name=f"Pflag {role.value} {unique}",
            password_hash=hash_password(f"T3st_{unique}!Pflag"),
            role=role,
            is_active=is_active,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        # Odczep obiekt od sesji, żeby atrybuty dało się czytać po jej zamknięciu.
        db.expunge(user)
        return user


def _headers(user: User) -> dict[str, str]:
    """Token mintujemy wprost — logowanie żyje w routerze, którego tu nie ma."""
    token = create_access_token(
        subject=user.id,
        role=user.role.value,
        roles=list(user.roles or []),
        authorization_version=user.authorization_version,
    )
    return {"Authorization": f"Bearer {token}"}


async def _seed_headers(role: UserRole, *, is_active: bool = True) -> dict[str, str]:
    return _headers(await _seed_user(role, is_active=is_active))


@pytest_asyncio.fixture
async def pflag_client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=_build_app(), raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest_asyncio.fixture
async def admin_headers() -> dict[str, str]:
    return await _seed_headers(UserRole.admin)


# ── 1. Kto może czytać, kto może pisać ─────────────────────────────────────


@pytest.mark.parametrize(
    "role", [UserRole.sourcer, UserRole.recruiter, UserRole.finance, UserRole.admin]
)
@pytest.mark.asyncio
async def test_every_role_can_read_active_flags(
    pflag_client: AsyncClient, role: UserRole
):
    """Plakietka jest widoczna zespołowi z definicji — o to w niej chodzi."""
    headers = await _seed_headers(role)

    resp = await pflag_client.get(_BASE, headers=headers)
    assert resp.status_code == 200, f"{role.value}: {resp.text}"
    body = resp.json()
    assert isinstance(body["flags_by_user"], dict)
    # Katalog typów jedzie razem z listą — front nie ma zgadywać brzmienia.
    assert {t["value"] for t in body["types"]} == set(PERFORMANCE_FLAG_TYPES)


@pytest.mark.asyncio
async def test_non_admin_cannot_raise_a_flag(pflag_client: AsyncClient):
    target_id = (await _seed_user(UserRole.sourcer)).id
    headers = await _seed_headers(UserRole.recruiter)

    resp = await pflag_client.post(
        _BASE,
        headers=headers,
        json={"user_id": target_id, "flag_type": "weak_results"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_non_admin_cannot_clear_a_flag(
    pflag_client: AsyncClient, admin_headers: dict[str, str]
):
    target_id = (await _seed_user(UserRole.sourcer)).id
    created = await pflag_client.post(
        _BASE,
        headers=admin_headers,
        json={"user_id": target_id, "flag_type": "procedures"},
    )
    assert created.status_code == 201, created.text
    flag_id = created.json()["id"]

    headers = await _seed_headers(UserRole.recruiter)
    resp = await pflag_client.patch(
        f"{_BASE}/{flag_id}", headers=headers, json={"is_active": False}
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_history_is_admin_only(pflag_client: AsyncClient):
    """Wygaszona ocena sprzed roku nie ma powodu wisieć przed całym zespołem."""
    target_id = (await _seed_user(UserRole.sourcer)).id
    headers = await _seed_headers(UserRole.recruiter)

    resp = await pflag_client.get(f"{_BASE}/history/{target_id}", headers=headers)
    assert resp.status_code == 403, resp.text


# ── 2. Wygaszenie zachowuje wiersz ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_clearing_keeps_the_row_with_full_authorship(
    pflag_client: AsyncClient, admin_headers: dict[str, str]
):
    target_id = (await _seed_user(UserRole.sourcer)).id
    created = await pflag_client.post(
        _BASE,
        headers=admin_headers,
        json={
            "user_id": target_id,
            "flag_type": "weak_results",
            "note": "Skonsultuj się z managerem. Za mała ilość weryfikacji.",
        },
    )
    assert created.status_code == 201, created.text
    flag = created.json()
    flag_id = flag["id"]
    # Autor jedzie z oceną — anonimowo nie da się jej postawić.
    assert flag["created_by_id"] is not None
    assert flag["created_by_name"]
    assert flag["label"] == "Słabe wyniki"
    assert flag["description"] == "Bardzo słabe wyniki, wymagana nagła poprawa"

    listed = await pflag_client.get(_BASE, headers=admin_headers)
    assert flag_id in [
        f["id"] for f in listed.json()["flags_by_user"].get(str(target_id), [])
    ]

    cleared = await pflag_client.patch(
        f"{_BASE}/{flag_id}", headers=admin_headers, json={"is_active": False}
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["is_active"] is False
    assert cleared.json()["cleared_at"] is not None
    assert cleared.json()["cleared_by_name"]

    # Zniknęła z listy aktywnych…
    listed_after = await pflag_client.get(_BASE, headers=admin_headers)
    assert flag_id not in [
        f["id"] for f in listed_after.json()["flags_by_user"].get(str(target_id), [])
    ]

    # …ale wiersz ŻYJE, razem z notatką i obiema atrybucjami.
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(UserPerformanceFlag).where(UserPerformanceFlag.id == flag_id)
            )
        ).scalar_one()
        assert row.is_active is False
        assert row.cleared_at is not None
        assert row.cleared_by is not None
        assert row.created_by is not None
        assert row.note == "Skonsultuj się z managerem. Za mała ilość weryfikacji."

    # …i jest do odczytania w historii.
    history = await pflag_client.get(
        f"{_BASE}/history/{target_id}", headers=admin_headers
    )
    assert history.status_code == 200, history.text
    assert flag_id in [f["id"] for f in history.json()["flags"]]


@pytest.mark.asyncio
async def test_cleared_flag_cannot_be_revived(
    pflag_client: AsyncClient, admin_headers: dict[str, str]
):
    target_id = (await _seed_user(UserRole.sourcer)).id
    flag_id = (
        await pflag_client.post(
            _BASE,
            headers=admin_headers,
            json={"user_id": target_id, "flag_type": "procedures"},
        )
    ).json()["id"]
    await pflag_client.patch(
        f"{_BASE}/{flag_id}", headers=admin_headers, json={"is_active": False}
    )

    revived = await pflag_client.patch(
        f"{_BASE}/{flag_id}", headers=admin_headers, json={"is_active": True}
    )
    assert revived.status_code == 409, revived.text

    edited = await pflag_client.patch(
        f"{_BASE}/{flag_id}", headers=admin_headers, json={"note": "przepisana ocena"}
    )
    assert edited.status_code == 409, edited.text


@pytest.mark.asyncio
async def test_second_active_flag_of_same_type_is_refused(
    pflag_client: AsyncClient, admin_headers: dict[str, str]
):
    """Dwie takie same plakietki to ta sama ocena narysowana dwa razy."""
    target_id = (await _seed_user(UserRole.sourcer)).id
    first = await pflag_client.post(
        _BASE,
        headers=admin_headers,
        json={"user_id": target_id, "flag_type": "weak_results"},
    )
    assert first.status_code == 201, first.text

    second = await pflag_client.post(
        _BASE,
        headers=admin_headers,
        json={"user_id": target_id, "flag_type": "weak_results"},
    )
    assert second.status_code == 409, second.text

    # Inny typ przy tej samej osobie jest w porządku — DynaReporter pokazuje
    # obie plakietki naraz (Zuzanna Gruszczyńska).
    other = await pflag_client.post(
        _BASE,
        headers=admin_headers,
        json={"user_id": target_id, "flag_type": "procedures"},
    )
    assert other.status_code == 201, other.text
    assert (
        len(
            (await pflag_client.get(_BASE, headers=admin_headers)).json()[
                "flags_by_user"
            ][str(target_id)]
        )
        == 2
    )


# ── 3/4. `note` i walidacja wejścia ────────────────────────────────────────


@pytest.mark.asyncio
async def test_note_is_optional_and_blank_means_absent(
    pflag_client: AsyncClient, admin_headers: dict[str, str]
):
    without_note_target = (await _seed_user(UserRole.sourcer)).id
    resp = await pflag_client.post(
        _BASE,
        headers=admin_headers,
        json={"user_id": without_note_target, "flag_type": "weak_results"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["note"] is None

    blank_target = (await _seed_user(UserRole.sourcer)).id
    blank = await pflag_client.post(
        _BASE,
        headers=admin_headers,
        json={"user_id": blank_target, "flag_type": "procedures", "note": "   "},
    )
    assert blank.status_code == 201, blank.text
    # Pusty komentarz to BRAK komentarza — inaczej front rysuje pustą linijkę.
    assert blank.json()["note"] is None


@pytest.mark.asyncio
async def test_unknown_flag_type_is_rejected(
    pflag_client: AsyncClient, admin_headers: dict[str, str]
):
    target_id = (await _seed_user(UserRole.sourcer)).id
    resp = await pflag_client.post(
        _BASE,
        headers=admin_headers,
        json={"user_id": target_id, "flag_type": "spoznienia"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_empty_patch_is_rejected(
    pflag_client: AsyncClient, admin_headers: dict[str, str]
):
    """Pusty zapis zwracający 200 wygląda dla admina jak wykonany."""
    target_id = (await _seed_user(UserRole.sourcer)).id
    flag_id = (
        await pflag_client.post(
            _BASE,
            headers=admin_headers,
            json={"user_id": target_id, "flag_type": "weak_results"},
        )
    ).json()["id"]

    resp = await pflag_client.patch(
        f"{_BASE}/{flag_id}", headers=admin_headers, json={}
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_note_edit_does_not_clear_the_flag(
    pflag_client: AsyncClient, admin_headers: dict[str, str]
):
    """Zapis częściowy: poprawka komentarza nie może zdjąć ostrzeżenia."""
    target_id = (await _seed_user(UserRole.sourcer)).id
    flag_id = (
        await pflag_client.post(
            _BASE,
            headers=admin_headers,
            json={
                "user_id": target_id,
                "flag_type": "procedures",
                "note": "Brak weryfikacji stawki kandydatów.",
            },
        )
    ).json()["id"]

    patched = await pflag_client.patch(
        f"{_BASE}/{flag_id}",
        headers=admin_headers,
        json={"note": "Ciągłe problemy z postami na Linkedin."},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["is_active"] is True
    assert patched.json()["note"] == "Ciągłe problemy z postami na Linkedin."


@pytest.mark.asyncio
async def test_flag_on_former_employee_is_allowed(
    pflag_client: AsyncClient, admin_headers: dict[str, str]
):
    """„Były pracownik" to nie flaga i nie blokuje oceny.

    DynaReporter pokazuje plakietki także przy osobach, które odeszły — chip
    stoi OBOK ostrzeżenia, nie zamiast niego.
    """
    target_id = (await _seed_user(UserRole.sourcer, is_active=False)).id
    resp = await pflag_client.post(
        _BASE,
        headers=admin_headers,
        json={"user_id": target_id, "flag_type": "weak_results"},
    )
    assert resp.status_code == 201, resp.text

    history = await pflag_client.get(
        f"{_BASE}/history/{target_id}", headers=admin_headers
    )
    assert history.status_code == 200, history.text
    assert history.json()["is_former_employee"] is True


@pytest.mark.asyncio
async def test_flag_for_unknown_user_is_404(
    pflag_client: AsyncClient, admin_headers: dict[str, str]
):
    resp = await pflag_client.post(
        _BASE,
        headers=admin_headers,
        json={"user_id": 2_000_000_000, "flag_type": "weak_results"},
    )
    assert resp.status_code == 404, resp.text
