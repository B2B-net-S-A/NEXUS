"""#130 — naprawa danych po znalezisku #32 (zatruty cache dopasowań).

Zatruty wiersz ma BIEŻĄCĄ wersję algorytmu i ``stale=False``, więc poprawiony
predykat świeżości też uzna go za świeży: nic go nie przeliczy, a zaniżony
wynik jest trwały. Naprawa musi go odnaleźć — i musi zostawić w spokoju wiersz,
który mówi to samo („0 punktów, brak embeddingu") ZGODNIE Z PRAWDĄ, bo jego
przeliczenie da dokładnie ten sam wynik i będzie płatnym no-opem.

Rozstrzyga o tym Qdrant, nie ``candidates.embedding_id``. Kolumna kłamie w obie
strony (kwarantanna kasuje wektor i kolumny nie czyści; ``reembed_collections``
pisze wektor i kolumny nie ustawia), więc każdy test ustawia ją NIEZALEŻNIE od
tego, co „wie" kolekcja — po to, żeby jej ewentualny powrót do predykatu wywalił
testy, a nie cicho zmienił liczby.

Warstwa SQL idzie przez PRAWDZIWEGO Postgresa i przez HTTP: predykat jest
wyrażeniem JSONB nad kolumną ``breakdown``, a zamockowany nie dowodzi niczego
poza tym, że mock zwraca to, co mu kazano. Zamockowany jest wyłącznie Qdrant —
bo jego rolą w tym predykacie jest ODPOWIEDŹ (zna / nie zna / milczy), a każdą
z tych trzech trzeba umieć wywołać na żądanie.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, tuple_, update

from app.api.admin_match_score_repair import (
    MAX_REPAIR_LIMIT,
    NO_EMBEDDING_REASON,
    _UPDATE_CHUNK,
    _would_be_served_as_fresh,
    suspect_row_conditions,
)
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.match_score import CandidateJobMatchScore
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.services.match_score_cache import _upsert_breakdown
from app.services.scoring_service import (
    LayerResult,
    ScoreBreakdown,
    score_semantic,
    scoring_algorithm_version,
)

PREVIEW = "/api/admin/match-score-repair/preview"
REPAIR = "/api/admin/match-score-repair/repair"
FULL = {"dry_run": False, "limit": 50_000}
_PROFILE_ID = 0  # wbudowany DEFAULT_PROFILE

pytestmark = pytest.mark.asyncio


# ── Kontrakt z warstwą scoringu i z definicją świeżości ──────────────────────


def test_reason_literal_still_matches_scoring_service() -> None:
    """Napis w predykacie musi być tym samym, który zapisuje scoring.

    Predykat trzyma LITERAŁ, bo naprawiamy wiersze zapisane historycznie.
    Cichy rozjazd z kodem oznaczałby zero trafień, a zero trafień wygląda
    dokładnie jak „czysto" — dlatego rozjazd ma wywalić test, nie raport.
    """
    assert score_semantic(None).reason == NO_EMBEDDING_REASON


def test_freshness_half_is_derived_not_copied() -> None:
    """Predykat bierze świeżość z ``fresh_score_conditions``, nie przepisuje jej.

    #32 powstało z kopii tej reguły, która w dniu powstania była wierna.
    Sprawdzamy więc nie treść, tylko że po odrzuceniu warunków ZAKRESU zostają
    dokładnie obie połowy świeżości — gdyby definicja urosła o trzecią, ten
    predykat dostanie ją bez zmiany kodu tutaj.
    """
    sql = _compile(_would_be_served_as_fresh())
    assert "stale IS false" in sql
    assert scoring_algorithm_version() in sql
    # Zakres wywołującego NIE może przeciec do naprawy — inaczej narzędzie
    # ruszałoby jedną ofertę zamiast całej tabeli.
    assert "job_id" not in sql and "profile_id" not in sql


def test_embedding_id_is_not_part_of_the_sql_predicate() -> None:
    """``candidates.embedding_id`` ma NIE wracać do kroku 1.

    Ta kolumna kłamie w obie strony i oba kłamstwa kosztują: na TAK dawała
    wiersze wracające po każdej naprawie w nieskończoność, na NIE — trwałe
    pominięcie ~2,6 tys. kandydatów, którym ``reembed_collections`` zapisał
    wektor bez ustawienia kolumny. Powrót do niej byłby cichy (liczby by się
    zmieniły, nic by nie wybuchło), więc pilnuje go asercja.
    """
    assert "embedding_id" not in _compile(suspect_row_conditions())


def _compile(conditions: list) -> str:
    return " ".join(
        str(c.compile(compile_kwargs={"literal_binds": True})) for c in conditions
    )


# ── Zamockowany Qdrant ───────────────────────────────────────────────────────


class _QdrantStub:
    """Trzy odpowiedzi kolekcji: zna / nie zna / milczy.

    Odwzorowuje kontrakt ``indexed_candidate_ids``: pusty wejściowy zbiór jest
    rozstrzygany bez pytania kolekcji, a awaria zwraca ``None`` — NIE pusty
    zbiór, bo to jest cała różnica między „nikt nie ma wektora" a „nie wiem".
    """

    def __init__(self) -> None:
        self.known: set[int] = set()
        self.calls: list[list[int]] = []
        self.down = False

    async def __call__(self, candidate_ids) -> Optional[set[int]]:
        ids = [int(c) for c in candidate_ids]
        self.calls.append(ids)
        if not ids:
            return set()
        if self.down:
            return None
        return set(ids) & self.known


@pytest.fixture(autouse=True)
def qdrant(monkeypatch) -> _QdrantStub:
    """Każdy test dostaje WŁASNĄ kolekcję, pustą na starcie.

    Baza testowa jest współdzielona i zostają w niej zatrute wiersze z innych
    testów. Dzięki temu, że kolekcja startuje pusta, tamte wiersze są dla tego
    testu „uczciwymi zerami" i nie zaburzają ``matched`` — asercje na liczbach
    mierzą wyłącznie to, co ten test zasiał.
    """
    stub = _QdrantStub()
    monkeypatch.setattr("app.api.admin_match_score_repair.indexed_candidate_ids", stub)
    return stub


# ── Pomocnicze ───────────────────────────────────────────────────────────────


def _breakdown(reason: str, points: float) -> dict[str, Any]:
    """Minimalny dokument o kształcie ``ScoreBreakdown.as_dict`` — istotny jest
    klucz ``semantic`` NAJWYŻSZEGO poziomu, bo po nim idzie predykat."""
    return {
        "total": 26.2,
        "semantic": {"points": points, "max": 60.0, "reason": reason},
        "skills": {"points": 10.0, "max": 15.0, "reason": "test"},
    }


async def _seed_candidate(qdrant: _QdrantStub, *, indexed: bool, column: bool) -> int:
    """Kandydat o niezależnie ustawianych: wektorze w kolekcji i KOLUMNIE.

    Rozdzielenie tych dwóch rzeczy jest sednem #130 — na produkcji rozjeżdżają
    się w obie strony, więc test, który ustawiałby je razem, nie odróżniłby
    predykatu opartego na kolumnie od predykatu opartego na kolekcji.
    """
    u = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Repair", lastname=f"Case-{u}", embedding_id=(u if column else None)
        )
        db.add(cand)
        await db.commit()
        if indexed:
            qdrant.known.add(cand.id)
        return cand.id


async def _seed_score(
    candidate_id: int, *, reason: str, version: str, points: float = 0.0
) -> tuple[int, int]:
    """Jeden wiersz cache (wraz z własną ofertą). Zwraca klucz wiersza."""
    u = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Repair Client {u}")
        db.add(client)
        await db.flush()
        job = Job(title=f"Repair Job {u}", client_id=client.id)
        db.add(job)
        await db.flush()
        db.add(
            CandidateJobMatchScore(
                candidate_id=candidate_id,
                job_id=job.id,
                profile_id=_PROFILE_ID,
                total_score=26.2,
                breakdown=_breakdown(reason, points),
                scoring_algorithm_version=version,
                stale=False,
            )
        )
        await db.commit()
        return candidate_id, job.id


async def _seed(
    qdrant: _QdrantStub,
    *,
    indexed: bool,
    column: bool = True,
    reason: str = NO_EMBEDDING_REASON,
    version: Optional[str] = None,
    points: float = 0.0,
) -> tuple[int, int]:
    cand = await _seed_candidate(qdrant, indexed=indexed, column=column)
    return await _seed_score(
        cand,
        reason=reason,
        version=version or scoring_algorithm_version(),
        points=points,
    )


async def _stale_of(candidate_id: int, job_id: int) -> bool:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CandidateJobMatchScore.stale).where(
                CandidateJobMatchScore.candidate_id == candidate_id,
                CandidateJobMatchScore.job_id == job_id,
                CandidateJobMatchScore.profile_id == _PROFILE_ID,
            )
        )


async def _recompute(candidate_id: int, job_id: int, semantic: LayerResult) -> None:
    """Leniwe przeliczenie DOKŁADNIE tą funkcją, której używa żywy scoring.

    Testowanie zbieżności przez ręczny ``UPDATE`` dowodziłoby tylko, że UPDATE
    działa. Interesuje nas to, co robi ``_upsert_breakdown`` — bo to ono zdejmuje
    ``stale`` i to ono wskrzeszało wiersze w poprzedniej wersji narzędzia.
    """
    neutral = LayerResult(points=0.0, max_points=10.0, reason="test")
    async with AsyncSessionLocal() as db:
        start = await db.scalar(select(func.now()))
        await _upsert_breakdown(
            db,
            ScoreBreakdown(
                candidate_id=candidate_id,
                job_id=job_id,
                total=26.2,
                semantic=semantic,
                skills=neutral,
                salary=neutral,
                location=neutral,
                availability=neutral,
            ),
            profile_id=_PROFILE_ID,
            compute_start=start,
        )
        await db.commit()


# ── Autoryzacja ──────────────────────────────────────────────────────────────


async def test_requires_admin(app_client: AsyncClient) -> None:
    """Bez tokenu ani podgląd, ani naprawa nie odpowiadają danymi."""
    assert (await app_client.get(PREVIEW)).status_code in (401, 403)
    assert (await app_client.post(REPAIR)).status_code in (401, 403)


async def test_authenticated_non_admin_is_still_refused(
    app_client: AsyncClient,
) -> None:
    """Zalogowany rekruter to NIE jest admin — 403 na obu endpointach.

    Brak tokenu odsiewa anonima i tyle; domyślną regułą tego repo jest
    „uwierzytelniony znaczy uprawniony" (patrz ``test_route_authz_contract``),
    więc dopiero ta asercja odróżnia bramkę ROLI od samego loginu. Stawka jest
    konkretna: ``repair`` ustawia ``stale=True`` masowo, czyli wyzwala falę
    przeliczeń płatnych wywołaniami Voyage'a — to nie jest przycisk, który
    wolno mieć każdemu zalogowanemu.
    """
    u = uuid.uuid4().hex[:8]
    email, password = f"repair-nonadmin-{u}@example.com", f"T3st_{u}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="Repair NonAdmin",
                role=UserRole.recruiter,
                is_active=True,
                email_verified=True,
                profile_completed=True,
            )
        )
        await db.commit()

    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert (await app_client.get(PREVIEW, headers=headers)).status_code == 403
    assert (
        await app_client.post(REPAIR, params=FULL, headers=headers)
    ).status_code == 403


# ── Obie strony predykatu — rozstrzyga kolekcja, nie kolumna ─────────────────


async def test_preview_asks_qdrant_not_the_column(
    app_client: AsyncClient, app_auth_headers: dict[str, str], qdrant: _QdrantStub
) -> None:
    """Trzy wiersze z tym samym objawem, trzy różne werdykty.

    Dwa pierwsze to obie klasy zatrucia — łącznie z tą, którą stary predykat
    pomijał TRWALE (wektor jest, kolumny nie ma; ``reembed_collections``).
    Trzeci to kandydat po kwarantannie: kolumna ustawiona, wektora nie ma, więc
    jego zero jest prawdziwe i przeliczanie go byłoby płatnym no-opem.
    """
    before = (await app_client.get(PREVIEW, headers=app_auth_headers)).json()

    with_column = await _seed(qdrant, indexed=True, column=True)
    without_column = await _seed(qdrant, indexed=True, column=False)
    await _seed(qdrant, indexed=False, column=True)  # po kwarantannie

    body = (await app_client.get(PREVIEW, headers=app_auth_headers)).json()

    assert body["matched"] == 2
    assert body["skipped_honest_zeros"] == before["skipped_honest_zeros"] + 1
    assert body["distinct_candidates"] == 2
    assert body["distinct_jobs"] == 2
    assert body["algorithm_version"] == scoring_algorithm_version()
    assert body["scan_truncated"] is False
    # Rozkład i próbka są tym, po czym operator ocenia skalę — muszą opisywać
    # te same wiersze, które naprawa ruszy.
    assert body["total_score"]["max"] == pytest.approx(26.2, abs=0.05)
    assert sorted((s["candidate_id"], s["job_id"]) for s in body["sample"]) == sorted(
        [with_column, without_column]
    )
    assert sum(b["rows"] for b in body["total_score_histogram"]) == 2


async def test_preview_and_repair_see_the_same_set(
    app_client: AsyncClient, app_auth_headers: dict[str, str], qdrant: _QdrantStub
) -> None:
    """Podgląd i naprawa muszą liczyć TEN SAM zbiór.

    Gdyby podgląd zatrzymał się na SQL-u, a dopiero naprawa pytała Qdranta,
    operator klikałby „napraw" na podstawie liczby opisującej co innego.
    """
    await _seed(qdrant, indexed=True)
    await _seed(qdrant, indexed=False)

    preview = (await app_client.get(PREVIEW, headers=app_auth_headers)).json()
    dry = (await app_client.post(REPAIR, headers=app_auth_headers)).json()

    assert preview["matched"] == dry["matched"] == 1


async def test_dry_run_changes_nothing(
    app_client: AsyncClient, app_auth_headers: dict[str, str], qdrant: _QdrantStub
) -> None:
    """``dry_run`` jest domyślny i nie dotyka ani jednego wiersza."""
    poisoned = await _seed(qdrant, indexed=True)

    # Bez parametru — domyślka MUSI być bezpieczna.
    r = await app_client.post(REPAIR, headers=app_auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "dry_run"
    assert body["updated"] == 0
    assert body["matched"] == 1
    assert body["would_update"] == 1
    assert body["remaining"] == 1

    assert await _stale_of(*poisoned) is False


async def test_repair_invalidates_only_poisoned_rows(
    app_client: AsyncClient, app_auth_headers: dict[str, str], qdrant: _QdrantStub
) -> None:
    """Pięć wierszy, jeden werdykt każdy — i tylko dwa do naprawy."""
    version = scoring_algorithm_version()

    # (1) Zatruty klasycznie: kolumna i wektor.
    poisoned = await _seed(qdrant, indexed=True, column=True)
    # (2) Zatruty i dotąd NIEWIDOCZNY: wektor jest, kolumny nie ma.
    reembedded = await _seed(qdrant, indexed=True, column=False)
    # (3) Po kwarantannie: kolumna została, wektora nie ma — zero jest prawdą.
    quarantined = await _seed(qdrant, indexed=False, column=True)
    # (4) Zdrowa semantyka — nie ma tu nic do naprawiania.
    healthy = await _seed(qdrant, indexed=True, reason="sim 0.42", points=35.7)
    # (5) Stara wersja algorytmu — i tak wypadnie z cache przez predykat
    #     świeżości, więc unieważnianie go byłoby czystym kosztem.
    outdated = await _seed(qdrant, indexed=True, version="score-v0-ancient")
    assert version != "score-v0-ancient"

    r = await app_client.post(REPAIR, params=FULL, headers=app_auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "repaired"
    assert body["matched"] == 2
    assert body["updated"] == 2
    assert body["remaining"] == 0

    assert await _stale_of(*poisoned) is True
    assert await _stale_of(*reembedded) is True
    assert await _stale_of(*quarantined) is False
    assert await _stale_of(*healthy) is False
    assert await _stale_of(*outdated) is False


async def test_second_repair_is_a_noop(
    app_client: AsyncClient, app_auth_headers: dict[str, str], qdrant: _QdrantStub
) -> None:
    """Powtórka na tym samym zbiorze nie robi nic — naprawiony wiersz ma
    ``stale=True``, więc WYPADA z predykatu."""
    await _seed(qdrant, indexed=True)

    first = (
        await app_client.post(REPAIR, params=FULL, headers=app_auth_headers)
    ).json()
    second = (
        await app_client.post(REPAIR, params=FULL, headers=app_auth_headers)
    ).json()

    assert first["updated"] == 1
    assert second["matched"] == 0
    assert second["updated"] == 0
    assert second["remaining"] == 0


async def test_limit_caps_the_batch_and_reports_the_rest(
    app_client: AsyncClient, app_auth_headers: dict[str, str], qdrant: _QdrantStub
) -> None:
    """Bieg jest wznawialny: limit tnie partię, a ``remaining`` mówi, ile
    zostało do następnego wywołania."""
    first_row = await _seed(qdrant, indexed=True)
    second_row = await _seed(qdrant, indexed=True)
    # Kolejność jest deterministyczna (candidate_id, job_id, profile_id), więc
    # wiadomo, który wiersz wejdzie do partii jako pierwszy.
    earlier, later = sorted([first_row, second_row])

    body = (
        await app_client.post(
            REPAIR, params={"dry_run": False, "limit": 1}, headers=app_auth_headers
        )
    ).json()
    assert body["matched"] == 2
    assert body["updated"] == 1
    assert body["remaining"] == 1
    assert await _stale_of(*earlier) is True
    assert await _stale_of(*later) is False

    rest = (
        await app_client.post(
            REPAIR, params={"dry_run": False, "limit": 1}, headers=app_auth_headers
        )
    ).json()
    assert rest["updated"] == 1
    assert rest["remaining"] == 0
    assert await _stale_of(*later) is True


# ── Awaria Qdranta ───────────────────────────────────────────────────────────


async def test_qdrant_outage_aborts_the_run(
    app_client: AsyncClient, app_auth_headers: dict[str, str], qdrant: _QdrantStub
) -> None:
    """Milczący Qdrant przerywa bieg — nie udaje „nikt nie ma wektora".

    Potraktowanie ``None`` jak pustego zbioru dałoby przy podglądzie fałszywe
    „czysto", a przy naprawie — unieważnienie CAŁEGO zbioru podejrzanych pod
    hasłem, że żaden kandydat nie jest zaindeksowany. Awaria musi wyglądać jak
    awaria i nie może ruszyć ani jednego wiersza.
    """
    poisoned = await _seed(qdrant, indexed=True)
    qdrant.down = True

    assert (await app_client.get(PREVIEW, headers=app_auth_headers)).status_code == 503
    assert (
        await app_client.post(REPAIR, params=FULL, headers=app_auth_headers)
    ).status_code == 503
    assert await _stale_of(*poisoned) is False

    # Po powrocie kolekcji ten sam wiersz jest normalnie naprawiany — awaria
    # niczego trwale nie zepsuła.
    qdrant.down = False
    body = (await app_client.post(REPAIR, params=FULL, headers=app_auth_headers)).json()
    assert body["updated"] == 1
    assert await _stale_of(*poisoned) is True


async def test_qdrant_is_asked_once_per_run_about_distinct_candidates(
    app_client: AsyncClient, app_auth_headers: dict[str, str], qdrant: _QdrantStub
) -> None:
    """Jeden kandydat = jedno pytanie, niezależnie od liczby jego wierszy.

    Kandydat ma na produkcji wiele wierszy cache (po jednym na ofertę), więc
    pytanie per wiersz mnożyłoby ruch do Qdranta przez współczynnik rzędu
    dziesiątek — za odpowiedź, którą już się zna.
    """
    cand = await _seed_candidate(qdrant, indexed=True, column=False)
    version = scoring_algorithm_version()
    for _ in range(3):
        await _seed_score(cand, reason=NO_EMBEDDING_REASON, version=version)

    body = (await app_client.get(PREVIEW, headers=app_auth_headers)).json()
    assert body["matched"] == 3
    assert body["distinct_candidates"] == 1

    assert len(qdrant.calls) == 1, "Qdrant pytany więcej niż raz na bieg"
    asked = qdrant.calls[0]
    assert asked.count(cand) == 1
    assert len(asked) == len(set(asked)), "ten sam kandydat w pytaniu dwa razy"


# ── Zbieżność: drugi bieg MUSI trafić zero ───────────────────────────────────


async def test_repair_converges_after_recompute(
    app_client: AsyncClient, app_auth_headers: dict[str, str], qdrant: _QdrantStub
) -> None:
    """Dowód, że naprawa ZBIEGA — a nie tylko deklaracja.

    Poprzednia wersja narzędzia (predykat na ``candidates.embedding_id``)
    wpadała tu w nieskończoną pętlę: kandydat po kwarantannie ma kolumnę i nie
    ma wektora, więc jego przeliczenie odtwarzało objaw co do znaku, a
    ``_upsert_breakdown`` zdejmowało ``stale`` — wiersz WRACAŁ do zbioru i każdy
    kolejny bieg unieważniał go od nowa.

    Scenariusz jest więc taki sam jak wtedy: obaj kandydaci naraz, naprawa,
    przeliczenie OBU żywą ścieżką, naprawa PONOWNIE. Drugi bieg ma trafić zero.
    """
    poisoned = await _seed(qdrant, indexed=True, column=True)
    quarantined = await _seed(qdrant, indexed=False, column=True)

    first = (
        await app_client.post(REPAIR, params=FULL, headers=app_auth_headers)
    ).json()
    assert first["matched"] == 1 and first["updated"] == 1
    assert await _stale_of(*poisoned) is True
    # Kandydat po kwarantannie nigdy nie wszedł do zbioru — to jest miejsce,
    # w którym stara wersja narzędzia płaciła za przeliczenie bez skutku.
    assert await _stale_of(*quarantined) is False

    # Przeliczenie obu. Kolekcja zna pierwszego, więc dostaje realne
    # podobieństwo; drugiego nie zna, więc scoring znów zapisuje „brak
    # embeddingu" — dokładnie ten wynik, który wcześniej wskrzeszał wiersz.
    await _recompute(*poisoned, score_semantic(0.62))
    await _recompute(*quarantined, score_semantic(None))
    assert await _stale_of(*poisoned) is False, "przeliczenie nie zdjęło stale"
    assert await _stale_of(*quarantined) is False

    second = (
        await app_client.post(REPAIR, params=FULL, headers=app_auth_headers)
    ).json()
    assert second["matched"] == 0, (
        "drugi bieg znalazł wiersze — naprawa nie zbiega i operator będzie "
        "w kółko płacił za przeliczenia, które niczego nie zmieniają"
    )
    assert second["updated"] == 0
    assert second["remaining"] == 0

    preview = (await app_client.get(PREVIEW, headers=app_auth_headers)).json()
    assert preview["matched"] == 0
    assert preview["already_attempted"] == 0


# ── Zapis: partia, która mieści się w parserze Postgresa ─────────────────────


async def test_update_chunk_is_parseable_by_this_postgres() -> None:
    """Partia ``_UPDATE_CHUNK`` krotek MUSI dać się sparsować.

    Lista krotek w ``IN`` jest parsowana rekurencyjnie, więc dostatecznie długa
    wywraca zapytanie na ``StatementTooComplexError: stack depth limit
    exceeded`` — na tej bazie zmierzone między 6 000 a 8 000 krotkami. Ponieważ
    ``limit`` sięga ``MAX_REPAIR_LIMIT``, jeden ``UPDATE`` na całej partii
    kończyłby się 500-tką PO wykonaniu pełnego skanu, bez ani jednego
    naprawionego wiersza. Test celuje w PRAWDZIWEGO Postgresa, bo próg zależy
    od jego ``max_stack_depth``, nie od naszego kodu.
    """
    assert _UPDATE_CHUNK < MAX_REPAIR_LIMIT, "bez tego podział nigdy nie zadziała"
    keys = [(i, i, 0) for i in range(1, _UPDATE_CHUNK + 1)]
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            update(CandidateJobMatchScore)
            .where(
                tuple_(
                    CandidateJobMatchScore.candidate_id,
                    CandidateJobMatchScore.job_id,
                    CandidateJobMatchScore.profile_id,
                ).in_(keys),
                *suspect_row_conditions(),
            )
            .values(stale=True, invalidated_at=func.now())
        )
        await db.rollback()
    # Klucze są syntetyczne, więc liczy się sam fakt, że serwer to zapytanie
    # przyjął.
    assert res.rowcount >= 0


async def test_repair_spans_more_than_one_chunk(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    qdrant: _QdrantStub,
    monkeypatch,
) -> None:
    """Podział na partie nie gubi wierszy z dalszych partii."""
    monkeypatch.setattr("app.api.admin_match_score_repair._UPDATE_CHUNK", 1)
    rows = [await _seed(qdrant, indexed=True) for _ in range(3)]

    body = (await app_client.post(REPAIR, params=FULL, headers=app_auth_headers)).json()
    assert body["updated"] == 3
    assert body["remaining"] == 0
    for row in rows:
        assert await _stale_of(*row) is True


# ── Sufit skanu ──────────────────────────────────────────────────────────────


async def test_truncated_scan_says_so(
    app_client: AsyncClient, app_auth_headers: dict[str, str], qdrant: _QdrantStub
) -> None:
    """Przycięty skan MUSI się przyznać — i MUSI podać, gdzie wznowić.

    Bez ``scan_truncated`` obcięty zbiór raportowałby się jako komplet, a
    ``remaining == 0`` znaczyłoby „czysto" na bazie, w której zostały tysiące
    zatrutych wierszy — czyli kryterium stopu kłamałoby w najgorszą stronę.
    Samo przyznanie się nie wystarcza: bez kursora operator wie, że nie doszedł
    do końca, i nie ma czym pójść dalej.
    """
    await _seed(qdrant, indexed=True)
    await _seed(qdrant, indexed=True)

    body = (
        await app_client.get(
            PREVIEW, params={"scan_limit": 1}, headers=app_auth_headers
        )
    ).json()
    assert body["scan_truncated"] is True
    assert body["scan_limit"] == 1
    assert body["after_candidate_id"] == 0
    assert body["next_after_candidate_id"] is not None


async def test_full_scan_reports_an_empty_cursor(
    app_client: AsyncClient, app_auth_headers: dict[str, str], qdrant: _QdrantStub
) -> None:
    """Kursor pusty = okno sięgnęło końca tabeli, czyli druga połowa kryterium
    stopu. Bez tej asercji ``null`` mógłby oznaczać „nie zaimplementowano"."""
    await _seed(qdrant, indexed=True)

    body = (await app_client.get(PREVIEW, headers=app_auth_headers)).json()
    assert body["scan_truncated"] is False
    assert body["next_after_candidate_id"] is None


async def test_honest_zeros_do_not_pin_the_scan_window(
    app_client: AsyncClient, app_auth_headers: dict[str, str], qdrant: _QdrantStub
) -> None:
    """Zatruty wiersz ZA prefiksem uczciwych zer musi dać się naprawić.

    To jest asymetria, która bez kursora czyniła sufit skanu pułapką, a nie
    ograniczeniem: naprawiony wiersz WYPADA z predykatu (dostaje ``stale``),
    ale uczciwe zero nie wypada NIGDY — nie ma w nim czego naprawiać. Prefiks
    uczciwych zer okupował więc okno na stałe i każdy kolejny bieg czytał ten
    sam zbiór. Zmierzone przed poprawką: trzy biegi z rzędu ``matched=0,
    updated=0, remaining=0, scan_truncated=true`` przy zatrutym wierszu
    nietkniętym — odpowiedź czytająca się jako „gotowe" nad danymi, których
    narzędzie nie mogło już dosięgnąć NIGDY.

    Kolejność siewu jest tu istotna: ``candidate_id`` rośnie, a skan idzie po
    nim rosnąco, więc uczciwe zera lądują PRZED zatrutym wierszem.
    """
    honest_a = await _seed(qdrant, indexed=False)
    honest_b = await _seed(qdrant, indexed=False)
    poisoned = await _seed(qdrant, indexed=True)
    assert honest_a[0] < honest_b[0] < poisoned[0], "sieć testu nie odwzorowuje układu"

    # Baza testowa jest współdzielona i niesie podejrzanych z innych testów —
    # startujemy kursorem tuż przed własnym posiewem, żeby sufit 2 mierzył
    # układ tego testu, a nie zaszłości sąsiadów.
    params = {**FULL, "scan_limit": 2, "after_candidate_id": honest_a[0] - 1}
    first = (
        await app_client.post(REPAIR, params=params, headers=app_auth_headers)
    ).json()
    assert first["matched"] == 0, "uczciwe zera nie powinny być naprawiane"
    assert first["scan_truncated"] is True
    cursor = first["next_after_candidate_id"]
    assert cursor is not None and cursor > 0

    second = (
        await app_client.post(
            REPAIR,
            params={**params, "after_candidate_id": cursor},
            headers=app_auth_headers,
        )
    ).json()
    assert second["updated"] == 1, "zatruty wiersz nadal nieosiągalny"
    assert second["next_after_candidate_id"] is None
    assert await _stale_of(*poisoned) is True
    assert await _stale_of(*honest_a) is False
    assert await _stale_of(*honest_b) is False


async def test_cursor_releases_a_candidate_split_by_the_ceiling(
    app_client: AsyncClient, app_auth_headers: dict[str, str], qdrant: _QdrantStub
) -> None:
    """Kandydat URWANY sufitem wraca w następnym oknie w CAŁOŚCI.

    Kursor idzie po ``candidate_id``, więc gdyby okno kończyło się w środku
    czyjegoś zestawu wierszy i kursor stanął ZA nim, wiersze zza sufitu
    wypadłyby z zasięgu narzędzia na zawsze — cicho, bo licznik pokazywałby
    tylko to, co zdążył zobaczyć. Dlatego urwanego wypuszczamy z partii i
    wznawiamy OD niego, nie za nim.
    """
    early = await _seed(qdrant, indexed=True)
    split_candidate = await _seed_candidate(qdrant, indexed=True, column=False)
    version = scoring_algorithm_version()
    split_rows = [
        await _seed_score(split_candidate, reason=NO_EMBEDDING_REASON, version=version)
        for _ in range(3)
    ]
    assert early[0] < split_candidate

    # Sufit 2: okno łapie wiersz `early` i PIERWSZY wiersz urwanego kandydata.
    # Kursor startowy odcina podejrzanych zasianych przez sąsiednie testy —
    # baza jest współdzielona, a sufit 2 mierzyłby wtedy nie ten układ.
    first = (
        await app_client.post(
            REPAIR,
            params={**FULL, "scan_limit": 2, "after_candidate_id": early[0] - 1},
            headers=app_auth_headers,
        )
    ).json()
    assert first["matched"] == 1, "urwany kandydat nie został wypuszczony z partii"
    assert first["updated"] == 1
    assert await _stale_of(*early) is True
    for row in split_rows:
        assert await _stale_of(*row) is False

    cursor = first["next_after_candidate_id"]
    assert cursor == split_candidate - 1, "kursor przeskoczył urwanego kandydata"

    second = (
        await app_client.post(
            REPAIR,
            params={**FULL, "after_candidate_id": cursor},
            headers=app_auth_headers,
        )
    ).json()
    assert second["updated"] == 3, "wiersze zza sufitu przepadły"
    for row in split_rows:
        assert await _stale_of(*row) is True
