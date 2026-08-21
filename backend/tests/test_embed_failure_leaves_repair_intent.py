"""Nieudany embedding musi zostawić ślad, na którym da się zadziałać.

`embed_candidate` zwraca `False`, a WSZYSTKIE ścieżki zapisu kandydata tę
wartość odrzucają i łapią wyłącznie wyjątek. Jedno przejściowe 429 z Voyage'a
kończyło się więc rekordem poprawnym w Postgresie i TRWALE nieobecnym
w matchingu: `embedding_id` zostaje NULL, żaden background job na to nie
patrzy (worker outboxu i reconciler dryfu są domyślnie wyłączone, a reconciler
z założenia pomija rekordy nigdy nieindeksowane), a rekruter widzi kandydata
na liście i nie widzi go w dopasowaniach. Zmierzone raz: 8 272 z 55 217.

Regresja jest CICHA — endpoint zwraca 201, profil renderuje się normalnie.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.index_outbox import IndexOutboxEvent
from app.services import embedding_service


async def _seed_candidate(db) -> Candidate:
    unique = uuid.uuid4().hex[:8]
    cand = Candidate(
        name="Embed",
        lastname=f"Fail{unique}",
        email=f"embedfail-{unique}@example.com",
        status=CandidateStatus.active,
        raw_cv_text="python fastapi postgresql",
    )
    db.add(cand)
    await db.commit()
    return cand


async def _cleanup(db, candidate_id: int) -> None:
    await db.execute(
        delete(IndexOutboxEvent).where(IndexOutboxEvent.entity_id == candidate_id)
    )
    await db.execute(delete(Candidate).where(Candidate.id == candidate_id))
    await db.commit()


async def _events_for(db, candidate_id: int) -> list[IndexOutboxEvent]:
    rows = await db.execute(
        select(IndexOutboxEvent).where(
            IndexOutboxEvent.entity_type == "candidate",
            IndexOutboxEvent.entity_id == candidate_id,
        )
    )
    return list(rows.scalars().all())


@pytest.mark.integration
@pytest.mark.asyncio
async def test_provider_failure_records_a_durable_reindex_intent(monkeypatch):
    async def _no_embedding(*_a, **_kw):
        return None

    monkeypatch.setattr(embedding_service, "generate_embedding", _no_embedding)

    async with AsyncSessionLocal() as db:
        cand = await _seed_candidate(db)
        try:
            ok = await embedding_service.embed_candidate(cand.id, db)
            assert ok is False
            await db.flush()
            events = await _events_for(db, cand.id)
            assert len(events) == 1, (
                "kandydat wypadł z matchingu bez żadnego wiersza, na którym "
                "ktokolwiek mógłby go później naprawić"
            )
            assert events[0].status == "pending"
            assert events[0].operation == "upsert"
            # `entity_revision=0` byłoby ciche i błędne — `_superseded` uznałby
            # takie zdarzenie za załatwione dla każdego wcześniej
            # zaindeksowanego kandydata.
            assert events[0].entity_revision > 0
        finally:
            await _cleanup(db, cand.id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_intent_recorded_when_the_outbox_worker_drives_the_call(monkeypatch):
    """Przy włączonym workerze to ON woła `embed_candidate` i sam liczy próby.

    Dopisanie stamtąd nowego zdarzenia zamieniłoby każdą nieudaną próbę drenażu
    w kolejny wiersz kolejki — podczas awarii providera kolejka rosłaby
    wykładniczo, a licznik `attempts` przestałby cokolwiek znaczyć.
    """
    from app.services import index_outbox_service

    async def _no_embedding(*_a, **_kw):
        return None

    monkeypatch.setattr(embedding_service, "generate_embedding", _no_embedding)
    monkeypatch.setattr(index_outbox_service, "worker_enabled", lambda: True)

    async with AsyncSessionLocal() as db:
        cand = await _seed_candidate(db)
        try:
            ok = await embedding_service.embed_candidate(cand.id, db)
            assert ok is False
            await db.flush()
            assert await _events_for(db, cand.id) == []
        finally:
            await _cleanup(db, cand.id)


# ── Ponowienia wywołania Voyage'a ────────────────────────────────────────────
#
# Do 2026-08-21 nie było ich NIGDZIE na ścieżce providera, a każda porażka
# kosztuje kandydata (patrz nagłówek pliku). Ponawiamy tylko sygnały
# przejściowe i tylko takie, które zawodzą szybko.


class _FakeAsyncClient:
    """Minimalny podmiennik `httpx.AsyncClient` — kolejka odpowiedzi/wyjątków."""

    scripted: list = []
    calls: int = 0

    def __init__(self, *_a, **_kw) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a) -> bool:
        return False

    async def post(self, _url, **_kw):
        type(self).calls += 1
        item = type(self).scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _voyage_ok():
    import httpx

    return httpx.Response(
        200,
        json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]},
        request=httpx.Request("POST", embedding_service.VOYAGE_API_URL),
    )


def _voyage_status(code: int):
    import httpx

    return httpx.Response(
        code,
        text="upstream says no",
        request=httpx.Request("POST", embedding_service.VOYAGE_API_URL),
    )


def _install_fake_voyage(monkeypatch, scripted: list) -> type[_FakeAsyncClient]:
    import httpx

    _FakeAsyncClient.scripted = list(scripted)
    _FakeAsyncClient.calls = 0
    monkeypatch.setattr(embedding_service.settings, "VOYAGE_API_KEY", "test-key")
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(embedding_service.asyncio, "sleep", _no_sleep)
    return _FakeAsyncClient


@pytest.mark.unit
@pytest.mark.asyncio
async def test_transient_429_is_retried(monkeypatch):
    fake = _install_fake_voyage(monkeypatch, [_voyage_status(429), _voyage_ok()])

    out = await embedding_service._voyage_embed_batch(["python developer"])

    assert out == [[0.1, 0.2]], "przejściowe 429 skasowało embedding na zawsze"
    assert fake.calls == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_permanent_401_is_not_retried(monkeypatch):
    """Zły klucz nie naprawi się przez powtórzenie — to tylko trzy razy 401."""
    fake = _install_fake_voyage(monkeypatch, [_voyage_status(401), _voyage_ok()])

    out = await embedding_service._voyage_embed_batch(["python developer"])

    assert out is None
    assert fake.calls == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retries_are_bounded(monkeypatch):
    fake = _install_fake_voyage(
        monkeypatch, [_voyage_status(503), _voyage_status(503), _voyage_status(503)]
    )

    out = await embedding_service._voyage_embed_batch(["python developer"])

    assert out is None
    assert fake.calls == 3, "liczba prób przestała być ograniczona"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_timeout_is_not_retried(monkeypatch):
    """Read-timeout kosztuje pełne 60 s na próbę — trzy takie to 180 s na request."""
    import httpx

    fake = _install_fake_voyage(
        monkeypatch, [httpx.ReadTimeout("too slow"), _voyage_ok()]
    )

    out = await embedding_service._voyage_embed_batch(["python developer"])

    assert out is None
    assert fake.calls == 1
