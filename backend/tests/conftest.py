"""
Test fixtures for Nexus ATS.

Two fixture families:
1. `client` + `auth_headers` — live-server fixtures (AsyncClient → localhost:8000).
   Used by the legacy integration tests in test_auth.py, test_candidates.py,
   test_contracts.py, test_dashboard.py, test_jobs.py, test_pipeline.py.
   These still require `uvicorn app.main:app` running on 8000.

2. `app_client` + `app_auth_headers` — in-process fixtures using
   httpx.ASGITransport(app=main.app). No network, runs in CI against the
   postgres service container. Used by Phase 7d+ integration tests.

Both share the DATABASE_URL env. In CI, alembic migrations run before pytest so
schema is ready.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


# ── Legacy user-fixture compatibility after the role cutover ────────────────


@pytest.fixture(scope="session", autouse=True)
def _normalise_legacy_user_fixtures():
    """Treat omitted rollout fields as an established test account.

    Production account creators explicitly set both ``roles`` and
    ``profile_completed``.  Older test factories predate those fields and
    intentionally model users who are already operating in NEXUS, so an
    omitted value must not silently turn every endpoint assertion into an
    onboarding assertion.

    Keep this compatibility at the test boundary: explicit ``False`` still
    exercises the fail-closed onboarding gate, and explicit role arrays still
    exercise malformed/exclusive-role cases.  The listener also mirrors the
    primary-role invariant for omitted arrays, including the retained legacy
    viewer used only by deny-path regression tests; it does not re-enable any
    production provisioning path for that role.
    """
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    from tests._user_fixture_compat import normalise_omitted_user_rollout_fields

    def _fill_omitted_rollout_fields(session, _flush_context, _instances) -> None:
        normalise_omitted_user_rollout_fields(session.new)

    event.listen(Session, "before_flush", _fill_omitted_rollout_fields)
    try:
        yield
    finally:
        event.remove(Session, "before_flush", _fill_omitted_rollout_fields)


# Share one event loop across the whole session so asyncpg connection pools
# don't see the loop closing between tests.
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


BASE_URL = "http://localhost:8000"
TEST_EMAIL = "artur@b2bnet.pl"
TEST_PASSWORD = "admin123"


# ── e-Zdrowie: bramka po ID kolidowała z serialem klientów ───────────────────


@pytest.fixture(autouse=True)
def _detach_ezdrowie_client_gate(monkeypatch):
    """Odsuń `EZDROWIE_CLIENT_ID` od zakresu, w który trafia `clients.id`.

    Bramka „części umowy" jest po ID (115) — świadomie, bo Traffit nadpisuje
    `Client.name`. W testach `clients.id` to zwykły serial, więc gdy któryś
    seed trafi akurat na 115, klient testowy STAJE SIĘ e-Zdrowiem i endpointy
    zaczynają wymagać części umowy. Objaw pojawia się w teście, który o
    e-Zdrowiu nic nie wie (`test_dl_portal` → 422 „Wybierz część umowy"), i
    zależy od tego, ile klientów utworzyły testy PRZED nim — czyli od podziału
    plików na shardy. Dopisanie nowego pliku testowego wystarczy, żeby czerwień
    przeskoczyła w zupełnie inne miejsce.

    Wartość ujemna jest nieosiągalna dla seriala, więc żaden seed jej nie
    trafi. Testy, które faktycznie badają e-Zdrowie, i tak ustawiają tę stałą
    na swojego świeżego klienta (`test_ezdrowie_project_part.py`) — ta fikstura
    im nie przeszkadza, bo ich `monkeypatch.setattr` wykonuje się później.

    Naprawia KLASĘ, nie objaw: żaden test tworzący klientów nie może już
    przypadkiem stać się e-Zdrowiem, niezależnie od kolejności plików.
    """
    monkeypatch.setattr("app.services.ezdrowie.EZDROWIE_CLIENT_ID", -1)


# ── Global skill-taxonomy isolation ─────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_skill_taxonomy():
    """Restore the process-global skill taxonomy after every test.

    `scoring_service.ALIAS_MAP` and the three `skill_normalize` containers are
    module-level caches hydrated once at app startup. Anything that calls
    `refresh_alias_map()` — the Cortex curation endpoints do, on every skill or
    alias edit — rewrites them for the rest of the process. That made the order
    of the CI file list load-bearing: `test_cortex_api.py` hydrates the taxonomy
    from the DB, and every later test that expects the unhydrated default
    (`test_scoring_service.py`, the CV bolding tests) then failed for a reason
    unrelated to itself.

    Restoring here fixes the class rather than the four symptoms: no test can
    leak taxonomy state into the next one, whichever order they run in. The
    snapshot is free in the common case — the containers are empty unless a
    test hydrated them.
    """
    from app.services import scoring_service as _ss
    from app.services import skill_normalize as _sn

    alias_map = dict(_ss.ALIAS_MAP)
    tech_canonicals = set(_sn.TECH_CANONICALS)
    alias_to_canonical = dict(_sn.ALIAS_TO_CANONICAL)
    canonical_to_aliases = {k: list(v) for k, v in _sn.CANONICAL_TO_ALIASES.items()}
    try:
        yield
    finally:
        # Only pay the rebuild (and the regex invalidation) when a test actually
        # moved the taxonomy.
        if _ss.ALIAS_MAP != alias_map:
            _ss.set_alias_map(alias_map)
        if (
            _sn.TECH_CANONICALS != tech_canonicals
            or _sn.ALIAS_TO_CANONICAL != alias_to_canonical
            or _sn.CANONICAL_TO_ALIASES != canonical_to_aliases
        ):
            _sn.set_tech_taxonomy(
                tech_canonicals=tech_canonicals,
                alias_to_canonical=alias_to_canonical,
                canonical_to_aliases=canonical_to_aliases,
            )


# ── Legacy live-server fixtures ─────────────────────────────────────────────


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(base_url=BASE_URL) as c:
        yield c


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    """Login and return auth headers (legacy live-server)."""
    resp = await client.post(
        "/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── In-process (Phase 7d) ────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def app_client() -> AsyncIterator[AsyncClient]:
    """In-process FastAPI client — no running server required.

    Also seeds a test admin on first use (same event loop as client).
    Combined in one fixture to avoid 'attached to a different loop' errors
    from pytest-asyncio running each fixture in its own task.

    Disables slowapi rate limiting for tests so the 5/min login cap doesn't
    interfere with suites that login multiple times.
    """
    from app.main import app
    from app.core.rate_limit import limiter as _limiter

    # Disable in-process rate limits for the test session
    _limiter.enabled = False

    # Seed admin user in the same loop
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole
    from sqlalchemy import select

    unique = uuid.uuid4().hex[:8]
    # Use .example.com — always reserved for testing per RFC 2606
    email = f"pytest-admin-{unique}@example.com"
    password = f"T3st_{unique}!PassX"

    async with AsyncSessionLocal() as db:
        existing = await db.scalar(select(User).where(User.email == email))
        if existing is None:
            u = User(
                email=email,
                password_hash=hash_password(password),
                name="Pytest Admin",
                role=UserRole.admin,
                is_active=True,
            )
            db.add(u)
            await db.commit()
            await db.refresh(u)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        # Expose credentials via extra headers attr for fixture consumers
        c.headers["X-Test-Admin-Email"] = email  # type: ignore[misc]
        c.headers["X-Test-Admin-Password"] = password  # type: ignore[misc]
        yield c


@pytest_asyncio.fixture
async def app_auth_headers(app_client: AsyncClient) -> dict[str, str]:
    """Log in the test admin via in-process client and return auth headers."""
    email = app_client.headers.get("X-Test-Admin-Email")
    password = app_client.headers.get("X-Test-Admin-Password")
    assert email and password, "admin_user was not seeded by app_client"

    resp = await app_client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# Skip live-server tests when RUN_LIVE_TESTS is not set
def _apply_ci_shard_filter(config, items) -> None:
    """CI-only podział kolekcji na shardy: całe PLIKI, round-robin po
    posortowanej liście ścieżek.

    Sterowane wyłącznie przez env (CI_SHARD_COUNT/CI_SHARD_INDEX ustawia
    matrix w ci.yml); bez nich twardy no-op, więc lokalny `pytest tests/`
    zachowuje się jak dotąd. Dzielimy po plikach, nie po testach — testy
    wewnątrz pliku bywają zależne od kolejności. Identyczna posortowana
    lista w każdym shardzie + modulo = partycja zupełna i rozłączna
    z konstrukcji, bez żadnej koordynacji między jobami.

    To NIE jest xdist (wdrożony i wycofany — patrz komentarz przy pytest
    w ci.yml): każdy shard to osobny runner z własnym postgresem
    i sekwencyjnym pytestem, więc klasa „równolegli workerzy na wspólnej
    bazie psują globalne agregaty" tu nie istnieje.
    """
    count = int(os.environ.get("CI_SHARD_COUNT", "1") or "1")
    if count <= 1:
        return
    index = int(os.environ.get("CI_SHARD_INDEX", "0") or "0")
    if not 0 <= index < count:
        raise pytest.UsageError(f"CI_SHARD_INDEX={index} poza zakresem 0..{count - 1}")
    ordered_files = sorted({str(item.path) for item in items})
    shard_of = {path: pos % count for pos, path in enumerate(ordered_files)}
    kept = [item for item in items if shard_of[str(item.path)] == index]
    if not kept:
        raise pytest.UsageError(
            f"Shard {index}/{count} nie dostał żadnego pliku — błędna konfiguracja"
        )
    deselected = [item for item in items if shard_of[str(item.path)] != index]
    if deselected:
        items[:] = kept
        config.hook.pytest_deselected(items=deselected)
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        kept_files = len({str(item.path) for item in kept})
        reporter.write_line(
            f"[ci-shard] shard {index}/{count}: "
            f"{kept_files}/{len(ordered_files)} plików, {len(kept)} testów"
        )


def pytest_collection_modifyitems(config, items):
    run_live = os.environ.get("RUN_LIVE_TESTS", "").lower() in ("1", "true", "yes")
    if not run_live:
        skip_live = pytest.mark.skip(
            reason="Live-server test; set RUN_LIVE_TESTS=1 to enable"
        )
        for item in items:
            # The legacy tests use `client` (not `app_client`)
            fixtures = getattr(item, "fixturenames", ())
            if "client" in fixtures and "app_client" not in fixtures:
                item.add_marker(skip_live)
    _apply_ci_shard_filter(config, items)
