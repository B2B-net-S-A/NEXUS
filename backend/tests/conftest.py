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
import importlib
import json
import os
import statistics
import uuid
from datetime import date, datetime, time
from pathlib import Path
from typing import AsyncIterator
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
import time_machine
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.scheduling import DEFAULT_TZ, business_today


# ── Zegar: doba nie może zmienić się w środku biegu ─────────────────────────
# 16.09.2026 shard CI padł na `test_order_line_roster.py`, choć PR nie dotykał
# zamówień. Mechanizm: moduły testowe liczą `_TODAY = business_today()` RAZ,
# przy imporcie, a kod produkcyjny woła `business_today()` przy każdym
# wywołaniu. Shard trwał 14m56s i przekroczył północ warszawską, więc wpis
# z końcem „dziś" stał się wpisem z końcem „wczoraj" i wypadł z aktywnej obsady.
#
# Poprawianie tego plik po pliku nie jest naprawą: `grep` znajduje 28 modułów
# liczących datę z zegara przy imporcie, a każdy kolejny dopisany test wnosi ten
# sam błąd od nowa. Dlatego zegar jest przypinany TUTAJ, dla całej sesji.
#
# Fixture jest no-opem przez ~23 godziny na dobę: przypięcie włącza się dopiero
# wtedy, gdy zegar faktycznie przeskoczył na inny dzień niż ten, który widziały
# importy. Bieg rozpoczęty i skończony tego samego dnia nie odczuwa go wcale.
#
# 23:59, czyli tuż przed północą: baza ma własny zegar (`now()` Postgresa),
# którego przypiąć się nie da, więc każda minuta cofnięcia to minuta rozjazdu
# między czasem Pythona a znacznikami wierszy. Kod liczący okna („to samo
# zdarzenie w ciągu 10 minut") łamie się na tym rozjeździe — zmierzone na
# `test_client_deletion`: cofnięcie o godzinę wywraca dedup, cofnięcie o minuty
# nie. Im bliżej północy, tym mniejszy rozjazd; dalej niż do 23:59 cofać się nie
# opłaca, bo cały zysk to i tak pozostanie w tym samym dniu.
_SESSION_DAY = business_today()
_PINNED_HOUR = 23
_PINNED_MINUTE = 59


@pytest.fixture
def routine_notification_email_enabled(monkeypatch):
    """Explicit opt-in for existing delivery/retry tests; production defaults OFF."""
    from app.services import notification_delivery as delivery
    from datetime import timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    policy = delivery.DeliveryPolicy.from_value(
        {
            "enabled": True,
            "send_not_before": cutoff,
            "types": {
                kind: {"email_enabled": True, "send_not_before": cutoff}
                for kind in delivery.ROUTINE_KINDS
            },
        }
    )

    async def enabled_policy(_db):
        return policy

    consumers = (
        "app.tasks.chat_email_fallback",
        "app.tasks.job_deadline_alerts",
        "app.tasks.app_mail_monitor",
        "app.services.stage_notification_emitter",
        "app.services.mention_dispatch",
    )
    # Import konsumentów PRZED podmianą: moduł importowany pierwszy raz w trakcie
    # podmiany wiąże `from … import load_policy` z włączoną polityką, a
    # monkeypatch zapamiętuje ją jako „oryginał" i przywraca po teście —
    # polityka zostawała włączona na stałe dla kolejnych plików.
    for module in consumers:
        importlib.import_module(module)
    monkeypatch.setattr(delivery, "load_policy", enabled_policy)
    monkeypatch.setattr(delivery, "load_policy_sync", lambda: policy)
    for module in consumers:
        monkeypatch.setattr(f"{module}.load_policy", enabled_policy, raising=False)
    return policy


def pinned_moment(session_day: date, current_day: date) -> datetime | None:
    """Moment, na który przypiąć zegar, albo ``None`` gdy nie ma czego naprawiać.

    Wydzielone z fixture'a, żeby dało się to sprawdzić testem bez udawania
    północy w prawdziwym zegarze procesu.
    """
    if current_day == session_day:
        return None
    return datetime.combine(
        session_day, time(_PINNED_HOUR, _PINNED_MINUTE), tzinfo=ZoneInfo(DEFAULT_TZ)
    )


@pytest.fixture(autouse=True)
def _pin_business_day():
    """Trzymaj „dzisiaj" na dniu, z którego pochodzą stałe modułów testowych."""
    pinned = pinned_moment(_SESSION_DAY, business_today())
    if pinned is None:
        yield _SESSION_DAY
        return
    # tick=False, bo przy 23:59 płynący zegar przekroczyłby północ po minucie —
    # czyli dokładnie to, przed czym to przypięcie broni. Zamrożenie zmierzono na
    # 394 testach (próba kontrolna: zegar ruszony, data ta sama): zero padów, więc
    # nic w tej suicie nie zależy od upływu czasu po stronie Pythona.
    with time_machine.travel(pinned, tick=False):
        yield _SESSION_DAY


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


# ── Lotte Wedel: bramka po ID koliduje z serialem klientów ──────────────────


@pytest.fixture(autouse=True)
def _detach_lotte_wedel_client_gate(monkeypatch):
    """Nie pozwól, by 155. testowy klient przypadkiem dostał polityki Lotte.

    Baza jest współdzielona przez testy w shardzie, a ``clients.id`` rośnie
    między nimi. Testy Lotte ustawiają stałą na własnego świeżego klienta już
    po tej autouse fixture; pozostałe dostają nieosiągalne ID.
    """

    monkeypatch.setattr("app.services.lotte_wedel_orders.LOTTE_WEDEL_CLIENT_ID", -2)


# ── Zamówienia z maila: okno godzin recheku ─────────────────────────────────


@pytest.fixture(autouse=True)
def _open_the_order_mail_recheck_window(monkeypatch):
    """Automatyczny recheck ma w testach chodzić niezależnie od pory dnia.

    Produkcyjnie `run_recheck(trigger="scheduled")` rusza tylko w godzinach
    8:00–18:00 (Europe/Warsaw). W testach zegar jest prawdziwy przez ~23 h na
    dobę (`_pin_business_day` jest no-opem, dopóki doba się nie zmieni), więc
    bez tego bramka zamieniłaby KAŻDY test recheku w test „czy jest teraz
    dzień" — zielony po południu, czerwony wieczorem i na nocnym CI.

    Wyrównane godziny = okno wyłączone. Testy samego okna ustawiają je jawnie
    i podmieniają zegar (`time_machine`), więc ta fixture ich nie dotyczy.
    """

    monkeypatch.setattr(settings, "ORDER_MAIL_RECHECK_START_HOUR_LOCAL", 0)
    monkeypatch.setattr(settings, "ORDER_MAIL_RECHECK_END_HOUR_LOCAL", 0)


# ── Auto-CV po ruchu na „Zweryfikowany" ─────────────────────────────────────


@pytest.fixture(autouse=True)
def _no_background_cv_generation_after_moves(monkeypatch):
    """Dziesiątki testów przesuwają kartę na „Zweryfikowany".

    Produkcyjnie taki ruch odpala w tle auto-generację CV (własna sesja bazy,
    `asyncio.create_task`). W testach zadanie przeżywałoby test, który je
    odpalił: pisałoby do wspólnej bazy po jego asercjach i kończyło się już po
    zamknięciu pętli zdarzeń. Testy samego automatu
    (`test_cv_auto_generate.py`) włączają go jawnie.
    """

    monkeypatch.setattr(settings, "CV_AUTO_GENERATE_ON_VERIFIED", False)


# ── QC CV — bramka przed „CV wysłane”/Cpro (Rekrutacja v5, 0361) ────────────


@pytest.fixture(autouse=True)
def _cv_qc_gate_off_by_default(monkeypatch):
    """Dziesiątki testów przesuwają kartę na „CV wysłane” bez CV firmowego.

    Bramka QC odmówiłaby każdemu z nich 409 — testują co innego (stawkę DL,
    Cpro, przepięcia). Testy bramki (`test_cv_qc.py`) włączają ją jawnie.
    """

    monkeypatch.setattr(settings, "CV_QC_GATE_ENABLED", False)


# ── Polkomtel: klientowa normalizacja numerów Finansów ─────────────────────


@pytest.fixture(autouse=True)
def _detach_polkomtel_finance_matching_gate(monkeypatch):
    """A serial test client must not accidentally become Polkomtel (id 15)."""

    monkeypatch.setattr("app.services.finance_order_matching.POLKOMTEL_CLIENT_ID", -3)


# ── Ticket 29.08: stałe ID polityki typów zamówień vs sekwencja testowa ─────


@pytest.fixture(autouse=True)
def _detach_canonical_order_type_policy(monkeypatch):
    """Testowe seriale 12/15/18/155 nie mogą udawać klientów produkcyjnych.

    Regresje samej interpretacji ustawiają mapę jawnie w swoim teście.
    Pozostałe fabryki klientów czytają historyczny ``NULL`` jako okresowe
    niezależnie od kolejności plików w shardzie CI.
    """

    monkeypatch.setattr("app.services.order_types._LEGACY_NULL_ORDER_TYPES", {})


@pytest.fixture(autouse=True)
def _detach_bik_canonical_client(monkeypatch):
    """18. testowy klient nie może stać się BIK-iem (odczyt PDF + koniec po MD).

    Polityka BIK ma kanoniczne ID produkcyjne 18. Bez tej fikstury klient
    testowy, który trafi na ten serial, dostawałby regułę odczytu BIK i —
    groźniej — automatyczne kończenie zamówień po wyczerpaniu limitów MD,
    czyli czerwień w teście, który o BIK-u nic nie wie. Testy BIK włączają
    politykę przez ``BIK_ORDER_CLIENT_IDS`` na własnym kliencie.
    """
    from dataclasses import replace

    from app.services.order_policies import registry

    # To samo dotyczy Polkomtela (kanoniczne ID 15 — piętnasty klient testowy)
    # i Cyfrowego Polsatu: ich testy włączają polityki przez env na własnym
    # kliencie.
    keys = ("bik", "polkomtel", "cyfrowy_polsat")
    detached = {
        key: replace(registry.policy_by_key(key), canonical_client_ids=frozenset())
        for key in keys
    }
    monkeypatch.setattr(
        registry,
        "POLICIES",
        tuple(detached.get(p.key, p) for p in registry.POLICIES),
    )
    for key, policy in detached.items():
        monkeypatch.setitem(registry._BY_KEY, key, policy)


# ── Synchronizacja kontrakt ↔ zamówienia (0304) ─────────────────────────────


@pytest.fixture(autouse=True)
def _enable_contract_order_sync(monkeypatch):
    """Na produkcji synchronizacja rusza po markerze jednorazowej korekty.

    Świeża baza testowa go nie ma, a większość testów opisuje zachowanie PO
    wdrożeniu. Zachowanie bez markera sprawdzają testy biorące fixture
    ``contract_order_sync_mode`` (niżej); przebieg dobowy sprawdza marker sam.
    """

    async def _enabled(_db) -> bool:
        return True

    monkeypatch.setattr("app.services.contract_order_sync.sync_enabled", _enabled)


@pytest.fixture(params=("enabled", "disabled"), ids=("sync-enabled", "sync-disabled"))
def contract_order_sync_mode(request, monkeypatch) -> str:
    """Macierz bramki synchronizacji kontrakt ↔ zamówienia (QA-07).

    Autouse ``_enable_contract_order_sync`` przypina stan PO korekcie (marker
    jest), więc bez tego fixture'u suite nigdy nie widzi zachowania sprzed
    markera — a tak stoi każda baza, na której blok w ``entrypoint.sh`` padł.
    Test, który bierze ten fixture, biegnie dwa razy: ``enabled`` (marker
    jest, synchronizacja działa) i ``disabled`` (markera brak — zapis
    zamówienia przechodzi, a kontrakt zostaje nietknięty: bez okresu
    zamówienia, bez kroku stawki przychodowej). Nadpisuje autouse przez ten
    sam ``monkeypatch`` (autouse biegnie pierwszy). Prawdziwy odczyt markera
    z ``AppSetting`` sprawdza przebieg dobowy w ``test_contract_order_sync.py``.
    """

    enabled = request.param == "enabled"

    async def _gate(_db) -> bool:
        return enabled

    monkeypatch.setattr("app.services.contract_order_sync.sync_enabled", _gate)
    return request.param


# ── CV generator: existing suite covers the rebuilt pipeline, strictly ──────


@pytest.fixture(autouse=True)
def _pin_cv_generator_rebuilt_pipeline(monkeypatch):
    """Production defaults to the 2bc6b14f flow with advisory source evidence
    (``legacy_v7``). The existing CV tests were written for the rebuilt (v10)
    pipeline with strict evidence, and that code stays selectable, so pin it
    here. Tests of the production defaults delete both variables themselves
    (``test_cv_generator_legacy_v7.py``)."""

    monkeypatch.setenv("CV_GENERATION_PIPELINE", "v10")
    monkeypatch.setenv("CV_SOURCE_EVIDENCE_ENFORCED", "true")
    # Niezależna kontrola AI (0326) jest na produkcji domyślnie WŁĄCZONA, ale
    # dla reszty suite'u trzymamy ją zgaszoną: te testy pisano zanim istniała,
    # więc nie stubują recenzenta i każde wywołanie poszłoby do dostawcy.
    # Ścieżkę doradczą pokrywa `test_cv_final_review_advisory.py`, który
    # włącza flagę u siebie.
    monkeypatch.setenv("CV_FINAL_REVIEW_ENABLED", "false")


@pytest.fixture(params=("legacy", "v10"), ids=("pipeline-legacy", "pipeline-v10"))
def pipeline_mode(request, monkeypatch) -> str:
    """Macierz flag generatora CV (QA-07).

    Test, który bierze ten fixture, biegnie dwa razy: w domyślnym przepływie
    produkcyjnym (``legacy_v7`` + dowody doradcze — tak, jak stoi Coolify) i w
    przebudowanym (``v10`` + ścisłe dowody — tak, jak przypina resztę suite'u
    ``_pin_cv_generator_rebuilt_pipeline``). Nadpisuje tamten pin, bo oba
    fixture'y dzielą jeden ``monkeypatch``, a autouse biegnie pierwszy.
    Wchodzą tu WYŁĄCZNIE kontrakty sensowne w obu trybach. Gdzie tryby
    legalnie się różnią, test rozgałęzia się jawnie i ma asercję dla KAŻDEGO
    trybu — nigdy nie luzuje asercji tak, żeby przeszła w obu. Testy maszynerii
    istniejącej tylko w v10 (ekstrakcja faktów źródłowych, płatna kontrola
    treści w kolejce) zostają na pinie z komentarzem dlaczego. Pełne różnice
    trybów opisuje ``test_cv_generator_legacy_v7.py`` (strażnik domyślnego).
    """

    if request.param == "legacy":
        monkeypatch.delenv("CV_GENERATION_PIPELINE", raising=False)
        monkeypatch.delenv("CV_SOURCE_EVIDENCE_ENFORCED", raising=False)
    else:
        monkeypatch.setenv("CV_GENERATION_PIPELINE", "v10")
        monkeypatch.setenv("CV_SOURCE_EVIDENCE_ENFORCED", "true")
    # Oba tryby bez niezależnej kontroli AI — jak w pinie wyżej.
    monkeypatch.setenv("CV_FINAL_REVIEW_ENABLED", "false")
    return request.param


# ── Global skill-taxonomy isolation ─────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_skill_taxonomy():
    """Restore the process-global skill taxonomy after every test.

    `scoring_service.ALIAS_MAP` and the three `skill_normalize` containers are
    module-level caches hydrated once at app startup. Anything that calls
    `refresh_alias_map()` — the skill-dictionary curation endpoints
    (`/api/skills-admin`, dawniej Cortex) do, on every skill or alias edit —
    rewrites them for the rest of the process. That made the order of the CI
    file list load-bearing: the curation API test hydrated the taxonomy
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
_CI_DURATIONS_FILE = Path(__file__).with_name("ci_test_durations.json")


def _ci_file_durations() -> dict[str, float]:
    """Zmierzony czas każdego pliku testowego z CI (sekundy, klucz ``tests/…``).

    Brak albo zepsuty plik to NIE błąd: podział wraca wtedy do równych wag
    i dalej jest partycją zupełną — gorzej wyważoną, nigdy dziurawą.
    """
    try:
        raw = json.loads(_CI_DURATIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {
        str(name): float(seconds)
        for name, seconds in raw.items()
        if isinstance(seconds, (int, float)) and seconds >= 0
    }


def ci_shard_assignment(
    files: list[str], count: int, durations: dict[str, float]
) -> dict[str, int]:
    """Przypisuje pliki do shardów tak, żeby każdy shard trwał podobnie długo.

    Zachłanny podział LPT: pliki od najdłuższego, każdy do shardu z najmniejszą
    sumą. Deterministyczny (remisy po nazwie pliku i numerze shardu), więc każdy
    shard, licząc niezależnie na tej samej liście, dostaje TĘ SAMĄ partycję —
    zupełną i rozłączną bez żadnej koordynacji między jobami. Plik bez pomiaru
    (nowy) waży medianę zmierzonych.
    """
    known = [durations[f] for f in files if f in durations]
    fallback = statistics.median(known) if known else 1.0
    loads = [0.0] * count
    assignment: dict[str, int] = {}
    for name in sorted(files, key=lambda f: (-durations.get(f, fallback), f)):
        target = min(range(count), key=lambda i: (loads[i], i))
        assignment[name] = target
        loads[target] += durations.get(name, fallback)
    return assignment


def _apply_ci_shard_filter(config, items) -> None:
    """CI-only podział kolekcji na shardy: całe PLIKI, wyważone zmierzonym czasem.

    Sterowane wyłącznie przez env (CI_SHARD_COUNT/CI_SHARD_INDEX ustawia
    matrix w ci.yml); bez nich twardy no-op, więc lokalny `pytest tests/`
    zachowuje się jak dotąd. Dzielimy po plikach, nie po testach — testy
    wewnątrz pliku bywają zależne od kolejności.

    Do 09.2026 podział był round-robin po posortowanej liście: shardy trwały
    od 5,6 do 9,8 min, a całość czekała na najwolniejszy. Teraz wagi idą
    z ``ci_test_durations.json`` (odświeżanie: `.github/scripts/
    build_test_durations.py`). Nieaktualna mapa pogarsza tylko równowagę.

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
    backend_root = Path(__file__).resolve().parent.parent
    key_of = {
        str(item.path): Path(item.path).resolve().relative_to(backend_root).as_posix()
        for item in items
    }
    shard_of = ci_shard_assignment(
        sorted(set(key_of.values())), count, _ci_file_durations()
    )
    kept = [item for item in items if shard_of[key_of[str(item.path)]] == index]
    if not kept:
        raise pytest.UsageError(
            f"Shard {index}/{count} nie dostał żadnego pliku — błędna konfiguracja"
        )
    deselected = [item for item in items if shard_of[key_of[str(item.path)]] != index]
    if deselected:
        items[:] = kept
        config.hook.pytest_deselected(items=deselected)
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        kept_files = len({str(item.path) for item in kept})
        reporter.write_line(
            f"[ci-shard] shard {index}/{count}: "
            f"{kept_files}/{len(shard_of)} plików, {len(kept)} testów"
        )


def _client_fixture_is_live_server(item) -> bool:
    """Czy `client` w TYM teście to live-serverowy fixture z conftestu?

    Reguła skipowania dopasowywała się po samej NAZWIE fixture'a, a nazwa nie
    mówi, gdzie fixture został zdefiniowany. Plik testowy, który lokalnie
    nadpisuje `client` transportem ASGI (in-process, żaden serwer nie jest
    potrzebny), nadal wnosi nazwę `client` do ``item.fixturenames`` — i był
    cicho skipowany razem z legacy testami wymagającymi uvicorna na :8000.
    Tak zniknął z CI cały ``test_dynareporter_readonly.py`` (6 testów, w tym
    ten enumerujący KAŻDĄ mutującą trasę /api/dynareporter), a kontrakt
    pokrycia tego nie widział, bo audytuje wyłącznie listę ``--ignore``.

    Pytamy więc o miejsce definicji: ``FixtureDef.baseid`` to id węzła, do
    którego fixture jest przypięty — dla fixture'a z conftestu jest to KATALOG
    ("tests"), dla lokalnego override'u ŚCIEŻKA PLIKU ("tests/test_x.py").
    Skipujemy tylko ten pierwszy przypadek.

    Gdy introspekcja się nie uda (inna wersja pytest, zmiana API), wracamy do
    poprzedniego zachowania — czyli skipujemy. Fałszywy skip jest cichy, ale
    fałszywe URUCHOMIENIE 31 live-serverowych testów bez serwera zamieniłoby
    CI w czerwień na wszystkich PR-ach.
    """
    fixtures = getattr(item, "fixturenames", ())
    if "client" not in fixtures or "app_client" in fixtures:
        return False

    info = getattr(item, "_fixtureinfo", None)
    defs = (getattr(info, "name2fixturedefs", None) or {}).get("client")
    if not defs:
        return True  # nie wiemy — zachowaj dotychczasowe zachowanie
    # pytest trzyma definicje od najbardziej ogólnej; wygrywa ostatnia (najbliższa).
    baseid = getattr(defs[-1], "baseid", None)
    if baseid is None:
        return True
    return not str(baseid).endswith(".py")


def pytest_collection_modifyitems(config, items):
    run_live = os.environ.get("RUN_LIVE_TESTS", "").lower() in ("1", "true", "yes")
    if not run_live:
        skip_live = pytest.mark.skip(
            reason="Live-server test; set RUN_LIVE_TESTS=1 to enable"
        )
        for item in items:
            # The legacy tests use `client` (not `app_client`) — ale tylko wtedy,
            # gdy `client` rozwiązuje się do fixture'a z tego conftestu.
            if _client_fixture_is_live_server(item):
                item.add_marker(skip_live)
    _apply_ci_shard_filter(config, items)


def db_without_client_merges():
    """Sesja-atrapa dla testów „Przelicz plan" bez prawdziwej bazy.

    ``refresh_review_plan`` pyta bazę, czy rekord klienta nie został scalony
    w inny (``_follow_client_merge``) — to JEDYNE zapytanie na tej ścieżce, gdy
    ``current_proposal`` / ``_plan_and_gate`` są podstawione. Gołe ``AsyncMock``
    oddaje na nie korutynę zamiast wierszy, więc test wywracał się na atrapie,
    a nie na logice. Ta sesja odpowiada uczciwie: „brak takiego wiersza", czyli
    klient nie jest scalony i dokument zostaje tam, gdzie był.
    """
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(all=lambda: [], scalars=lambda: [])
    return db
