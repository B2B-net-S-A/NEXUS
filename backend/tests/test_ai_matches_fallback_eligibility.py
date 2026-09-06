"""Gałąź tag-fallback `/ai-matches` też musi przepuszczać przez bramkę.

PRODUKTOWY OVERRIDE (2026-09): bramka (`_gate_and_dealbreakers`) nie WYCINA już
`warn` — kandydat z aktywnym NDA/konfliktem u klienta oferty jest POKAZYWANY
z anotacją `eligibility` i `assignment_allowed=false`, żeby rekruter widział
blokadę zamiast dostać 409 dopiero po kliknięciu. Wycinane są wyłącznie `hidden`
(globalna blacklista, duplikat). Te testy pilnują więc, że NDA-kandydat WRACA
z zablokowaną akcją (a nie że znika) i że fail-closed bramki został zachowany.

Do 2026-08-20 bramka (`filter_eligible_candidates`) stała wyłącznie w gałęzi
semantycznej, i to WEWNĄTRZ `try`. Fallback filtrował `Candidate.status !=
"blacklisted"` i nic więcej. Wchodzi się w niego trzema drogami i tylko jedna
z nich jest awarią:

1. wyjątek z `search_candidates_semantic` (Qdrant/Voyage padł),
2. wyjątek z czegokolwiek innego w gałęzi semantycznej — **w tym z samej
   bramki**, bo stała pod tym samym `try`,
3. **cicho**: `hits == []` sprawia, że `if hits:` jest fałszywe, gałąź
   semantyczna kończy się bez `return`, a sterowanie schodzi do fallbacku
   bez żadnego wyjątku i bez żadnego wpisu w logu o degradacji.

Droga (3) to normalna praca systemu przy chudej kolekcji Qdranta, nie awaria —
i to ona sprawiała, że dziura była codzienna, a nie incydentalna.

Testy celowo NIE używają globalnej blacklisty: fallback odsiewał ją już wcześniej,
więc taki dowód przechodziłby na `main` i niczego by nie dowodził. Blokada, która
przeciekała, to aktywny `CandidateConflict` z klientem oferty — dlatego seed
stawia kandydata ze statusem `active` i konfliktem typu `nda`.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.client import Client
from app.models.job import Job


@pytest_asyncio.fixture
async def gated_fixture():
    """Klient + oferta + dwóch kandydatów: czysty i zablokowany NDA u klienta.

    `hiring_manager_contact_id` zostaje `None` — weto HM to osobna gałąź bramki,
    a ten test dotyczy konfliktu klienckiego. Bramka musi działać także wtedy,
    gdy oferta nie ma przypisanego hiring managera (tak wygląda większość
    ofert zaimportowanych z Traffita).
    """
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"AIMatch Fallback Client {unique}")
        db.add(client)
        await db.flush()

        job = Job(
            title=f"AIMatch Fallback Job {unique}",
            client_id=client.id,
            description="Python backend engineer, FastAPI, PostgreSQL",
            requirements="python, fastapi, postgresql",
            hiring_manager_contact_id=None,
        )
        clean = Candidate(
            name="Czysta",
            lastname=f"Kandydatka{unique}",
            email=f"clean-{unique}@example.com",
            status=CandidateStatus.active,
            skills=[{"name": "python"}, {"name": "fastapi"}],
            raw_cv_text="python fastapi postgresql",
        )
        blocked = Candidate(
            # NIE blacklisted globalnie — inaczej odsiałby go filtr sprzed fixa
            # i test byłby zielony na `main`.
            name="Zablokowany",
            lastname=f"Kandydat{unique}",
            email=f"blocked-{unique}@example.com",
            status=CandidateStatus.active,
            skills=[{"name": "python"}, {"name": "fastapi"}],
            raw_cv_text="python fastapi postgresql",
        )
        db.add_all([job, clean, blocked])
        await db.flush()

        db.add(
            CandidateConflict(
                candidate_id=blocked.id,
                client_id=client.id,
                type=ConflictType.nda,
                reason="pytest — NDA u klienta oferty",
                active=True,
            )
        )
        await db.commit()
        ids = (job.id, clean.id, blocked.id, client.id)

    yield ids

    job_id, clean_id, blocked_id, client_id = ids
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CandidateConflict).where(CandidateConflict.client_id == client_id)
        )
        await db.execute(
            delete(Candidate).where(Candidate.id.in_([clean_id, blocked_id]))
        )
        await db.execute(delete(Job).where(Job.id == job_id))
        await db.execute(delete(Client).where(Client.id == client_id))
        await db.commit()


def _ids(body: dict) -> list[int]:
    return [m["candidate"]["id"] for m in body["matches"]]


def _match(body: dict, cid: int) -> dict | None:
    for m in body["matches"]:
        if m["candidate"]["id"] == cid:
            return m
    return None


def _widen_pool(monkeypatch) -> None:
    """Fallback bierze `LIMIT effective_pool` BEZ `ORDER BY`.

    Przy domyślnych 100 to, czy zasiane wiersze w ogóle wejdą do puli, zależy
    od tego ilu kandydatów nasiały inne testy w tej samej bazie — czyli od
    kolejności kolekcji. Podniesienie puli zdejmuje tę zmienną; nie zmienia
    niczego, co test bada (bramka działa na tym, co do puli weszło).
    """
    monkeypatch.setattr(settings, "AI_MATCH_POOL_SIZE", 100_000)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fallback_reached_by_empty_hits_still_gates(
    app_client: AsyncClient, app_auth_headers: dict, gated_fixture, monkeypatch
):
    """Droga (3): pusty wynik Qdranta — cicho, bez wyjątku, bez logu awarii."""
    job_id, clean_id, blocked_id, _client_id = gated_fixture

    _widen_pool(monkeypatch)

    async def _no_hits(*_a, **_kw):
        return []

    monkeypatch.setattr(
        "app.services.embedding_service.search_candidates_semantic", _no_hits
    )

    resp = await app_client.get(
        f"/api/jobs/{job_id}/ai-matches",
        params={"min_score": 0.0, "limit": 500},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["search_type"] == "tag_fallback"
    returned = _ids(body)
    # PRODUKTOWY OVERRIDE: NDA-kandydat (visibility=warn) jest POKAZYWANY
    # z anotacją i zablokowaną akcją — nie wycinany.
    assert blocked_id in returned, (
        "kandydat z aktywnym NDA (warn) zniknął z listy — kontrakt wymaga "
        "pokazania go z powodem i zablokowaną akcją"
    )
    blocked_match = _match(body, blocked_id)
    assert blocked_match is not None
    elig = blocked_match["eligibility"]
    assert elig is not None, "brak anotacji dopuszczalności na zablokowanym wierszu"
    assert elig["assignment_allowed"] is False, (
        "akcja przypisania musi być zablokowana dla kandydata z NDA"
    )
    assert elig["reason_code"] == "client_nda"
    assert elig["reason"], "powód po polsku musi być obecny"
    # Czysty kandydat: obecny, bez anotacji.
    clean_match = _match(body, clean_id)
    assert clean_match is not None, "bramka wycięła kandydata bez żadnej blokady"
    assert clean_match["eligibility"] is None
    # PRODUKTOWY OVERRIDE (2026-09): `warn` (NDA) jest POKAZYWANY jako wiersz,
    # więc NIE jest liczony w `meta.eligibility_filtered` — ten licznik obejmuje
    # wyłącznie warstwę `hidden` (globalna blacklista / duplikat), której ten
    # fixture nie zasiewa. Odwraca asercję P-B (`>= 1`): klucz zostaje w API dla
    # parytetu z Talent Radarem, ale liczy tylko realnie ukrytych.
    assert body["meta"]["eligibility_filtered"] == 0, (
        "warn nie może być liczony jako odsiany — jest pokazywany z powodem"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fallback_reached_by_retrieval_exception_still_gates(
    app_client: AsyncClient, app_auth_headers: dict, gated_fixture, monkeypatch
):
    """Droga (1): retrieval rzuca — degradacja providera, nie błąd kodu."""
    job_id, clean_id, blocked_id, _client_id = gated_fixture

    _widen_pool(monkeypatch)

    async def _boom(*_a, **_kw):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(
        "app.services.embedding_service.search_candidates_semantic", _boom
    )

    resp = await app_client.get(
        f"/api/jobs/{job_id}/ai-matches",
        params={"min_score": 0.0, "limit": 500},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["search_type"] == "tag_fallback"
    returned = _ids(body)
    assert blocked_id in returned
    blocked_match = _match(body, blocked_id)
    assert blocked_match is not None and blocked_match["eligibility"] is not None
    assert blocked_match["eligibility"]["assignment_allowed"] is False
    assert clean_id in returned


@pytest.mark.integration
@pytest.mark.asyncio
async def test_gate_failure_does_not_degrade_into_an_ungated_list(
    app_client: AsyncClient, app_auth_headers: dict, gated_fixture, monkeypatch
):
    """Droga (2) — jedyny test odróżniający dwie różne poprawki.

    „Dołożyłem bramkę w fallbacku" i „wyciągnąłem bramkę z `try`" dają ten sam
    wynik w testach 1-2. Różnią się dopiero tutaj: gdy padnie SAMA bramka.
    Dopóki stała pod `try`, jej wyjątek był łapany jako degradacja retrievalu
    i request wjeżdżał w gałąź, która bramki nie ma — czyli awaria bramki
    bezpieczeństwa omijała bramkę bezpieczeństwa. Poprawną odpowiedzią jest 500.

    Bramka to teraz `_gate_and_dealbreakers`, które woła `evaluate_candidates_for_job`
    (poza `try` retrievalu) — psujemy tę funkcję, żeby udowodnić, że jej awaria
    propaguje jako 500, a nie degraduje do listy bez bramki.

    Własny klient z `raise_app_exceptions=False`, bo `conftest.app_client` go nie
    ustawia (wyjątek wyszedłby z klienta zamiast stać się odpowiedzią), a
    `app/main.py` nie ma generycznego handlera na `Exception`.
    """
    job_id, _clean_id, _blocked_id, _client_id = gated_fixture

    async def _one_hit(*_a, **_kw):
        # Prawdziwe trafienie: gałąź semantyczna MUSI wejść aż do bramki.
        return [{"candidate_id": _clean_id, "score": 0.9}]

    async def _gate_boom(*_a, **_kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "app.services.embedding_service.search_candidates_semantic", _one_hit
    )
    monkeypatch.setattr("app.api.matching.evaluate_candidates_for_job", _gate_boom)

    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as strict_client:
        resp = await strict_client.get(
            f"/api/jobs/{job_id}/ai-matches",
            params={"min_score": 0.0, "limit": 500},
            headers=app_auth_headers,
        )

    assert resp.status_code == 500, (
        "awaria bramki dopuszczalności zdegradowała się do listy BEZ bramki "
        f"({resp.status_code}, {resp.text[:200]})"
    )
