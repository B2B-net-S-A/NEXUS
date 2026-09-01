"""Ścieżka rozwoju (D6) — poziom seniority liczony z placementów.

Pod ochroną są dokładnie te własności, których złamanie nie rzuca wyjątkiem
i nie widać go na ekranie — czyli takie, które bez testu wracają cicho:

1. **Junior przy zerze.** Osoba bez ani jednego placementu ma być juniorem
   z licznikiem 0, a nie zniknąć z listy. Poprzednik (`dr_user_seniority`)
   chował każdego bez zaseedowanego wiersza i podawał podzbiór zespołu jako
   całość.
2. **Awans DOKŁADNIE na progu.** Próg-1 to nadal poziom niższy. Błąd o jeden
   w drugą stronę awansowałby ludzi wcześniej, niż mówi im reguła na ekranie.
3. **Nieaktywni WYKLUCZENI** — regresja na „ghost promotion": import Traffita
   zakłada niedopasowanych operatorów jako `is_active=False`
   (`app/services/traffit/importer.py:1427`) i przypisuje im historyczny ruch.
   To był bloker decyzji D6.
4. **Placement liczony RAZ** mimo dwóch wierszy `hired` dla tej samej pary
   (kandydat, oferta) — import dopisuje wiersz na każde zdarzenie.
5. **Brak degradacji.** Poziom osiągnięty w oknie, które już minęło, zostaje.
6. **Każda rola czyta endpoint** (decyzja D7).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.cache import cache_invalidate
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.insights_seniority import (
    CONFIG_KEY_EXPERT_PLACEMENTS,
    CONFIG_KEY_EXPERT_WINDOW,
    CONFIG_KEY_SENIOR_PLACEMENTS,
    CONFIG_KEY_SENIOR_WINDOW,
    DEFAULT_THRESHOLDS,
    SeniorityThresholds,
    compute_seniority,
)

# Progi testowe świadomie NIŻSZE niż produkcyjne — 3 placementy zamiast 6.
# Test ma sprawdzać ARYTMETYKĘ okna, nie wysokość progu; przy produkcyjnych
# wartościach każdy przypadek wymagałby dwukrotnie więcej seedu, a zmiana
# progu przez admina wywracałaby zielony test bez żadnej regresji w kodzie.
TEST_THRESHOLDS = SeniorityThresholds(
    senior_placements=3,
    senior_window_months=6,
    expert_placements=5,
    expert_window_months=12,
)

# Rok, w którym seedujemy. Musi być ROKIEM NIEUŻYWANYM PRZEZ ŻADEN INNY TEST
# — baza jest wspólna dla całego przebiegu, a wiersze zasiane tutaj mają
# `moved_by`, więc wchodzą też do imiennych raportów sąsiadów. Pierwsza wersja
# stała na 2015 i wywracała
# `test_insights_recruitment_funnel.py::test_time_to_hire_measures_from_the_real_process_start`:
# tamten test liczy medianę w oknie 2015-06 i sprawdza, że wynosi >= 90 dni,
# a zatrudnienia zasiane tutaj nie mają wcześniejszego etapu, więc wnosiły
# medianę 0 i ścinały maksimum. Zanim zmienisz ten rok, sprawdź:
#   grep -rhoE "datetime\(20[0-9]{2}|\"20[0-9]{2}-" backend/tests/ | sort -u
SEED_YEAR = 2007
AS_OF = date(SEED_YEAR, 12, 31)


async def _seed_user(role: UserRole, label: str, *, is_active: bool = True) -> int:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"snr-{label}-{unique}@example.com",
            name=f"Seniority {label} {unique}",
            password_hash=hash_password(f"T3st_{unique}!Snr"),
            role=role,
            is_active=is_active,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id


async def _login_headers(client: AsyncClient, role: UserRole) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"snr-login-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Snr"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                name=f"Seniority login {unique}",
                password_hash=hash_password(password),
                role=role,
                is_active=True,
            )
        )
        await db.commit()
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_placements(
    user_id: int, months: list[int], *, duplicate_rows: int = 1
) -> None:
    """Jeden placement (para kandydat × oferta) na każdy podany miesiąc.

    ``duplicate_rows`` > 1 wstawia tyle wierszy `hired` dla TEJ SAMEJ pary —
    tak wygląda ponowne wejście na etap po imporcie z Traffita. Widok
    `analytics_first_milestones` ma je zredukować do jednego.
    """
    async with AsyncSessionLocal() as db:
        client_row = Client(name=f"SnrCli-{uuid.uuid4().hex[:6]}")
        db.add(client_row)
        await db.commit()
        await db.refresh(client_row)

        for month in months:
            job = Job(
                title=f"Snr {uuid.uuid4().hex[:6]}",
                location="Warszawa",
                status=JobStatus.published,
                remote_policy=RemotePolicy.hybrid,
                client_id=client_row.id,
            )
            candidate = Candidate(
                name=f"Snr-{uuid.uuid4().hex[:4]}",
                lastname=f"Path-{uuid.uuid4().hex[:4]}",
                email=f"snr-{uuid.uuid4().hex[:8]}@example.com",
            )
            db.add_all([job, candidate])
            await db.commit()
            await db.refresh(job)
            await db.refresh(candidate)

            # Południe UTC w połowie miesiąca — żaden przelicznik na
            # Europe/Warsaw nie przerzuci tego do sąsiedniego kubełka.
            base = datetime(SEED_YEAR, month, 15, 12, 0, tzinfo=timezone.utc)
            for i in range(duplicate_rows):
                db.add(
                    CandidateStage(
                        candidate_id=candidate.id,
                        job_id=job.id,
                        stage=PipelineStage.hired,
                        moved_at=base + timedelta(days=i),
                        moved_by=user_id,
                    )
                )
        await db.commit()


async def _row_for(user_id: int, *, as_of: date = AS_OF):
    async with AsyncSessionLocal() as db:
        result = await compute_seniority(db, as_of=as_of, thresholds=TEST_THRESHOLDS)
    return result, next((r for r in result.rows if r.user_id == user_id), None)


@pytest_asyncio.fixture
async def fx_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


# ── 1. Junior przy zerze ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_person_without_any_placement_is_junior_and_still_listed():
    """Zero placementów to junior z licznikiem 0 — NIE zniknięcie z listy."""
    user_id = await _seed_user(UserRole.recruiter, "zero")

    _, row = await _row_for(user_id)

    assert row is not None, "osoba bez placementów wypadła z listy"
    assert row.level == "junior"
    assert row.total_placements == 0
    assert row.placements_in_senior_window == 0
    assert row.placements_in_expert_window == 0
    assert row.placements_to_next_level == TEST_THRESHOLDS.senior_placements
    assert row.progress_pct == 0.0
    # Wiersz osoby bez ani jednej przypisanej historii musi dać się odróżnić
    # od wiersza osoby zatrudnionej wczoraj — inaczej UI nie ma czego pokazać
    # zamiast paska „0/3", który czyta się jako ocena.
    assert row.first_placement_month is None


# ── 2. Awans dokładnie na progu ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_promotion_happens_exactly_at_threshold_not_one_early():
    """Próg-1 to nadal junior; próg to senior. Błąd o jeden w obie strony."""
    below_id = await _seed_user(UserRole.sourcer, "below")
    at_id = await _seed_user(UserRole.tac, "at")

    # Oba komplety w JEDNYM oknie 6 miesięcy (lipiec–grudzień).
    await _seed_placements(below_id, [7, 8])  # 2 z wymaganych 3
    await _seed_placements(at_id, [7, 8, 9])  # dokładnie 3

    _, below = await _row_for(below_id)
    _, at_threshold = await _row_for(at_id)

    assert below is not None and at_threshold is not None
    assert below.level == "junior", "awans o jeden placement za wcześnie"
    assert below.placements_to_next_level == 1
    assert at_threshold.level == "senior", "próg spełniony, a awansu nie ma"


@pytest.mark.asyncio
async def test_placements_spread_beyond_the_window_do_not_add_up():
    """Trzy placementy w DZIEWIĘCIU miesiącach to nie trzy w sześciu.

    Bez tego okno byłoby dekoracją: liczyłoby się wyłącznie „ile kiedykolwiek",
    czyli każdy z wystarczającym stażem awansowałby sam z siebie.
    """
    user_id = await _seed_user(UserRole.recruiter, "spread")
    await _seed_placements(user_id, [2, 8, 12])  # rozstrzał 11 miesięcy

    _, row = await _row_for(user_id)

    assert row is not None
    assert row.total_placements == 3
    assert row.level == "junior"


# ── 3. Nieaktywni wykluczeni (regresja: ghost promotion) ─────────────────────


@pytest.mark.asyncio
async def test_inactive_accounts_are_excluded_and_counted_separately():
    """Konto-widmo z importu NIE awansuje i NIE znika bez śladu.

    `importer.py:1427` zakłada niedopasowanego operatora Traffita jako
    `is_active=False` i przypisuje mu historyczny ruch. Gdyby taki wiersz
    wszedł do puli, reguła „N placementów w oknie" wypisałaby z imienia
    i nazwiska konto, za którym nie stoi żaden pracownik.
    """
    ghost_id = await _seed_user(UserRole.recruiter, "ghost", is_active=False)
    await _seed_placements(ghost_id, [7, 8, 9, 10])

    result, row = await _row_for(ghost_id)

    assert row is None, "konto nieaktywne trafiło do rankingu ścieżki rozwoju"
    # Ale jego dorobek NIE znika po cichu — inaczej suma tabeli nie zgadza się
    # z lejkiem i wygląda to na błąd, a nie na świadome wykluczenie.
    assert result.outside_pool_placements >= 4


@pytest.mark.asyncio
async def test_roles_outside_the_path_are_not_listed():
    """Pula to sourcer / TAC / rekruter — `delivery_lead` prowadzi co innego."""
    dl_id = await _seed_user(UserRole.delivery_lead, "dl")
    await _seed_placements(dl_id, [7, 8, 9])

    result, row = await _row_for(dl_id)

    assert row is None
    assert result.outside_pool_placements >= 3


# ── 4. Dedup pary ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_two_hired_rows_for_the_same_pair_count_as_one_placement():
    """Ponowne wejście na `hired` to nadal JEDEN placement (definicja D2).

    Bez tego osoba z jednym kandydatem, którego proces odbił się dwa razy,
    dostawałaby awans za tę samą osobę policzoną dwukrotnie.
    """
    user_id = await _seed_user(UserRole.recruiter, "dup")
    await _seed_placements(user_id, [7, 8], duplicate_rows=3)

    _, row = await _row_for(user_id)

    assert row is not None
    assert row.total_placements == 2, "surowe wiersze `hired` policzone zamiast par"
    assert row.level == "junior"


# ── 5. Brak degradacji ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_level_is_a_ratchet_and_survives_an_empty_current_window():
    """Poziom osiągnięty w oknie, które minęło, ZOSTAJE.

    Degradacja samym upływem czasu — bez żadnego zdarzenia po stronie osoby —
    jest nie do wytłumaczenia komuś, kogo dotyczy. Sygnał „przestał dowozić"
    ma nieść licznik bieżącego okna, a nie poziom.
    """
    user_id = await _seed_user(UserRole.recruiter, "ratchet")
    await _seed_placements(user_id, [1, 2, 3])

    # Trzy lata później — bieżące okno jest puste.
    _, row = await _row_for(user_id, as_of=date(SEED_YEAR + 3, 6, 30))

    assert row is not None
    assert row.level == "senior", "poziom cofnął się od samego upływu czasu"
    assert row.placements_in_senior_window == 0
    assert row.total_placements == 3


@pytest.mark.asyncio
async def test_as_of_cuts_off_later_placements():
    """`as_of` odcina przyszłość — inaczej odpowiedź nie daje się odtworzyć."""
    user_id = await _seed_user(UserRole.recruiter, "asof")
    await _seed_placements(user_id, [3, 4, 11])

    _, row = await _row_for(user_id, as_of=date(SEED_YEAR, 6, 30))

    assert row is not None
    assert row.total_placements == 2
    assert row.first_placement_month == f"{SEED_YEAR}-03"


# ── Progi zerowe i procenty ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_zero_threshold_yields_null_progress_and_promotes_nobody():
    """Próg 0 to konfiguracja BEZ reguły, nie reguła spełniona przez każdego.

    Gdyby `>= 0` traktować jako spełnione, pusty wiersz konfiguracji awansowałby
    cały zespół na eksperta — łącznie z osobami bez ani jednego placementu.
    """
    user_id = await _seed_user(UserRole.recruiter, "zerothr")

    async with AsyncSessionLocal() as db:
        result = await compute_seniority(
            db,
            as_of=AS_OF,
            thresholds=SeniorityThresholds(
                senior_placements=0,
                senior_window_months=6,
                expert_placements=0,
                expert_window_months=12,
            ),
        )
    row = next((r for r in result.rows if r.user_id == user_id), None)

    assert row is not None
    assert row.level == "junior"
    assert row.progress_pct is None, "0.0 przy braku progu udaje policzony wynik"
    assert row.placements_to_next_level is None


@pytest.mark.asyncio
async def test_progress_is_not_clipped_at_one_hundred_percent():
    """Przekroczenie progu ma być widoczne, nie schowane pod 100%."""
    user_id = await _seed_user(UserRole.recruiter, "over")
    await _seed_placements(user_id, [8, 9, 10, 11])  # 4 przy progu eksperta 5

    _, row = await _row_for(user_id)

    assert row is not None
    assert row.level == "senior"
    # 4/5 do eksperta — a senior został osiągnięty z zapasem (4 > 3).
    assert row.placements_to_next_level == 1
    assert row.progress_pct == 80.0


@pytest.mark.asyncio
async def test_expert_row_has_no_next_level():
    """Expert nie ma dokąd awansować — 0 czytałoby się jako „tuż-tuż"."""
    user_id = await _seed_user(UserRole.recruiter, "expert")
    await _seed_placements(user_id, [4, 5, 6, 7, 8])  # 5 = próg eksperta

    _, row = await _row_for(user_id)

    assert row is not None
    assert row.level == "expert"
    assert row.placements_to_next_level is None
    assert row.progress_pct is None


# ── Anty-dryf domyślnych progów ──────────────────────────────────────────────


def test_defaults_mirror_the_scoring_config_source_of_truth():
    """Dwa komplety domyślnych progów = dwa różne poziomy tym samym ludziom.

    `insights_scoring_config` jest jedynym źródłem wartości domyślnych. Ten
    moduł trzyma własną kopię wyłącznie jako zabezpieczenie przed brakiem
    klucza — ale kopia, która się rozjedzie, jest gorsza niż jej brak.
    """
    from app.services.insights_scoring_config import SCORING_DEFAULTS

    for key in (
        CONFIG_KEY_SENIOR_PLACEMENTS,
        CONFIG_KEY_SENIOR_WINDOW,
        CONFIG_KEY_EXPERT_PLACEMENTS,
        CONFIG_KEY_EXPERT_WINDOW,
    ):
        assert DEFAULT_THRESHOLDS[key] == SCORING_DEFAULTS[key], key


# ── 6. Endpoint: D7 i kształt koperty ────────────────────────────────────────


@pytest.mark.asyncio
async def test_seniority_endpoint_is_reachable_for_every_logged_in_role(
    fx_client: AsyncClient,
):
    """Decyzja D7: /insights widzi KAŻDA zalogowana rola."""
    for role in (
        UserRole.admin,
        UserRole.head_of_recruitment,
        UserRole.delivery_lead,
        UserRole.finance,
        UserRole.tac,
        UserRole.recruiter,
        UserRole.sourcer,
    ):
        headers = await _login_headers(fx_client, role)
        resp = await fx_client.get(
            "/api/insights/recruitment/seniority", headers=headers
        )
        assert resp.status_code == 200, f"{role.value}: {resp.text}"


@pytest.mark.asyncio
async def test_seniority_endpoint_requires_authentication(fx_client: AsyncClient):
    """„Wszyscy" znaczy „każdy ZALOGOWANY", nie „każdy z internetu"."""
    resp = await fx_client.get("/api/insights/recruitment/seniority")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_envelope_carries_the_rule_so_the_ui_can_write_it_out(
    fx_client: AsyncClient,
):
    """Progi i okno wychodzą na zewnątrz — pasek postępu nie mówi, ile trzeba."""
    await cache_invalidate("insights:recruitment:seniority:")
    headers = await _login_headers(fx_client, UserRole.admin)

    resp = await fx_client.get(
        "/api/insights/recruitment/seniority",
        headers=headers,
        params={"as_of": AS_OF.isoformat()},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["as_of"] == AS_OF.isoformat()
    for key in (
        "senior_placements",
        "senior_window_months",
        "expert_placements",
        "expert_window_months",
    ):
        assert isinstance(body["thresholds"][key], int), key

    senior_window = body["window"]["senior"]
    assert senior_window["end_month"] == f"{SEED_YEAR}-12"
    assert senior_window["months"] == body["thresholds"]["senior_window_months"]
    # Okno kończy się w miesiącu `as_of`, a zaczyna `months-1` miesięcy wcześniej.
    assert senior_window["start_month"] < senior_window["end_month"]

    assert body["totals"]["users"] == len(body["entries"])
    assert set(body["totals"]["levels"]) == {"junior", "senior", "expert"}
    # Placementy spoza tabeli muszą wyjść w kopercie — bez nich suma kolumny
    # nie zgadza się z lejkiem (decyzja D1).
    assert "unattributed_placements" in body["coverage"]
    assert "outside_pool_placements" in body["coverage"]
