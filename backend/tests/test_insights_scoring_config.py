"""Konfigurowalna punktacja Ligi i progi seniority (decyzja D3/D6).

Domyślne wartości żyją w TRZECH kopiach: `SCORING_DEFAULTS` w kodzie, seed
w migracjach (`0256` zakłada tabelę, `0260` dosiewa alternatywne progi
i poprawia okno Eksperta) i lustro DDL w `entrypoint.sh`. Migracje nie mogą importować
kodu aplikacji (uruchamiają się też na starym obrazie), więc duplikat jest
konieczny — ale rozjazd między nimi zmieniłby formułę rozdzielającą nagrody
5000/3000/2000 PLN, i to bez żadnego błędu. Ten plik jest strażnikiem, na
którego powołuje się komentarz w migracji.
"""

from __future__ import annotations

import ast
import re
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.services.insights_scoring_config import SCORING_DEFAULTS

_BACKEND = Path(__file__).resolve().parents[1]
_VERSIONS = _BACKEND / "alembic" / "versions"
_MIGRATION = _VERSIONS / "0256_insights_scoring_config.py"
_MIGRATION_ALT = _VERSIONS / "0260_seniority_alternative_thresholds.py"
_ENTRYPOINT = _BACKEND / "entrypoint.sh"


# ── Trzy kopie domyślnych muszą się zgadzać ────────────────────────────────


def _literal(path: Path, target: str) -> object:
    """Wartość stałej modułowej z pliku migracji, bez importowania go."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        # `_DEFAULTS: list[tuple[str, int]] = [...]` to AnnAssign, nie Assign —
        # obsługujemy oba, żeby test nie pękł przy zdjęciu adnotacji.
        if isinstance(node, ast.AnnAssign):
            name = getattr(node.target, "id", None)
            node_value = node.value
        elif isinstance(node, ast.Assign):
            name = getattr(node.targets[0], "id", None)
            node_value = node.value
        else:
            continue
        if name != target or node_value is None:
            continue
        return ast.literal_eval(node_value)
    raise AssertionError(f"Nie znalazłem `{target}` w {path.name}")


def _as_mapping(value: object) -> dict[str, int]:
    if isinstance(value, dict):
        return {str(k): int(v) for k, v in value.items()}
    return {str(k): int(v) for k, v in value}  # type: ignore[union-attr]


def _defaults_from_migration() -> dict[str, int]:
    """Stan, w jakim migracje zostawiają świeżą bazę.

    Seed jest rozłożony na DWA pliki, bo 0256 jest już na produkcji: 0260
    dosiewa alternatywne progi i poprawia okno Eksperta. Czytanie samego 0256
    dawałoby strażnika, który przestał pilnować połowy kluczy — i to bez
    czerwieni, bo brakujący klucz wygląda jak „obowiązuje domyślna".
    """
    seeded = _as_mapping(_literal(_MIGRATION, "_DEFAULTS"))
    seeded.update(_as_mapping(_literal(_MIGRATION_ALT, "_NEW_DEFAULTS")))
    seeded[str(_literal(_MIGRATION_ALT, "_EXPERT_WINDOW_KEY"))] = int(
        _literal(_MIGRATION_ALT, "_EXPERT_WINDOW_NEW")  # type: ignore[arg-type]
    )
    return seeded


def test_migration_seed_matches_code_defaults():
    """Seed migracji == `SCORING_DEFAULTS`, co do klucza i co do wartości."""
    assert _defaults_from_migration() == SCORING_DEFAULTS


def test_entrypoint_mirror_seeds_every_key():
    """Lustro DDL w entrypoint.sh musi znać KAŻDY klucz.

    Prod alembic bywa orphaned, więc to entrypoint faktycznie dowozi tabelę.
    Klucz, którego tam nie ma, po prostu nie powstanie — a jego brak wygląda
    jak „obowiązuje domyślna", więc nikt się nie zorientuje.
    """
    text = _ENTRYPOINT.read_text(encoding="utf-8")
    missing = [key for key in SCORING_DEFAULTS if key not in text]
    assert not missing, f"entrypoint.sh nie seeduje kluczy: {missing}"


def test_entrypoint_mirror_values_match_code_defaults():
    """Wartości w entrypoint.sh też muszą się zgadzać, nie tylko klucze."""
    text = _ENTRYPOINT.read_text(encoding="utf-8")
    mismatched: list[str] = []
    for key, expected in SCORING_DEFAULTS.items():
        # Seed ma postać ('klucz', 123) — dopuszczamy dowolne białe znaki.
        pattern = rf"'{re.escape(key)}'\s*,\s*(\d+)"
        found = re.search(pattern, text)
        if not found or int(found.group(1)) != expected:
            mismatched.append(
                f"{key}: entrypoint={found.group(1) if found else None} kod={expected}"
            )
    assert not mismatched, "Rozjazd wartości: " + "; ".join(mismatched)


# ── Endpoint ───────────────────────────────────────────────────────────────


async def _seed_user(role: UserRole) -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"scfg-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Scfg"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                name=f"Scfg {role.value} {unique}",
                password_hash=hash_password(password),
                role=role,
                is_active=True,
            )
        )
        await db.commit()
    return email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def scfg_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.mark.parametrize(
    "role", [UserRole.sourcer, UserRole.recruiter, UserRole.finance, UserRole.admin]
)
@pytest.mark.asyncio
async def test_every_role_can_read_the_rules(scfg_client: AsyncClient, role: UserRole):
    """Zasady gry widzi każdy.

    Ranking widoczny dla wszystkich, ale formuła tylko dla admina, byłby
    wyrocznią — ludzie widzą wynik i nie mogą sprawdzić, skąd się wziął.
    """
    email, password = await _seed_user(role)
    headers = await _login(scfg_client, email, password)
    resp = await scfg_client.get("/api/insights/scoring-config", headers=headers)
    assert resp.status_code == 200, f"{role.value}: {resp.text}"
    body = resp.json()
    values = body.get("values", body)
    for key in SCORING_DEFAULTS:
        assert key in values, f"brak klucza {key} w odpowiedzi"


@pytest.mark.asyncio
async def test_non_admin_cannot_change_the_rules(scfg_client: AsyncClient):
    """Zmiana wag przesuwa podium, a podium ma kwoty."""
    email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(scfg_client, email, password)
    resp = await scfg_client.patch(
        "/api/insights/scoring-config",
        headers=headers,
        json={"values": {"league_points_placement": 999}},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_admin_change_is_persisted_and_readable(scfg_client: AsyncClient):
    email, password = await _seed_user(UserRole.admin)
    headers = await _login(scfg_client, email, password)

    original = (
        await scfg_client.get("/api/insights/scoring-config", headers=headers)
    ).json()
    original_values = original.get("values", original)
    before = int(original_values["league_points_placement"])

    try:
        patched = await scfg_client.patch(
            "/api/insights/scoring-config",
            headers=headers,
            json={"values": {"league_points_placement": before + 7}},
        )
        assert patched.status_code == 200, patched.text

        again = (
            await scfg_client.get("/api/insights/scoring-config", headers=headers)
        ).json()
        again_values = again.get("values", again)
        assert int(again_values["league_points_placement"]) == before + 7
    finally:
        await scfg_client.patch(
            "/api/insights/scoring-config",
            headers=headers,
            json={"values": {"league_points_placement": before}},
        )


@pytest.mark.asyncio
async def test_out_of_range_value_is_rejected_whole(scfg_client: AsyncClient):
    """Odrzucamy CAŁE żądanie, nie zapisujemy części.

    Zapis częściowy dałby punktację, której nikt nie zażądał: admin wysyła trzy
    wagi, dostaje błąd i dwie zmienione wagi.
    """
    email, password = await _seed_user(UserRole.admin)
    headers = await _login(scfg_client, email, password)

    before = (
        await scfg_client.get("/api/insights/scoring-config", headers=headers)
    ).json()
    before_values = before.get("values", before)

    resp = await scfg_client.patch(
        "/api/insights/scoring-config",
        headers=headers,
        json={
            "values": {
                "league_points_recommendation": 7,
                "league_points_placement": 10_000_000,
            }
        },
    )
    assert resp.status_code in (400, 422), resp.text

    after = (
        await scfg_client.get("/api/insights/scoring-config", headers=headers)
    ).json()
    after_values = after.get("values", after)
    assert (
        after_values["league_points_recommendation"]
        == (before_values["league_points_recommendation"])
    )


@pytest.mark.asyncio
async def test_unknown_key_is_rejected(scfg_client: AsyncClient):
    email, password = await _seed_user(UserRole.admin)
    headers = await _login(scfg_client, email, password)
    resp = await scfg_client.patch(
        "/api/insights/scoring-config",
        headers=headers,
        json={"values": {"league_points_teleportation": 5}},
    )
    assert resp.status_code in (400, 422), resp.text


def test_league_weights_are_pinned_because_they_pay_out():
    """Wagi Ligi niosą pieniądze — zmiana ma być decyzją, nie skutkiem ubocznym.

    Zmierzone na produkcji Q3 2026 przy tych wartościach: u zwycięzcy 2 040
    z 3 080 punktów (66%) pochodziło ze składnika `interview`, a osoba z 4
    placementami wygrała 5 000 zł z osobą, która miała 6 (3 000 zł). Właściciel
    świadomie zostawił wagi bez zmian (2026-09-03).

    Ten test nie broni konkretnych liczb jako „słusznych" — wymusza, żeby ich
    zmiana przeszła przez świadomą edycję testu, a nie wjechała przy okazji
    refaktoru albo zmiany mapowania Traffita, które przesuwa składnik
    `interview`.
    """
    from app.services.insights_scoring_config import SCORING_DEFAULTS

    assert SCORING_DEFAULTS["league_points_placement"] == 150
    assert SCORING_DEFAULTS["league_points_interview"] == 15
    assert SCORING_DEFAULTS["league_points_recommendation"] == 5
