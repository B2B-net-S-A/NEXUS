"""Padnięty commit stempla nie może zostawić oferty bez znacznika na zawsze.

``embed_job`` upsertuje wektor do Qdranta, a DOPIERO POTEM ustawia
``jobs.embedding_id`` i commituje. Te dwa zapisy nie są i nie mogą być atomowe —
jeden idzie po sieci do innego systemu. Do #403 padnięty commit kończył się
w szerokim ``except Exception: return False``: wektor zostawał w kolekcji,
kolumna zostawała pusta, wołający dostawał ``False`` i szedł dalej, a oferta
cicho przestawała generować propozycje i podpowiedzi pytań. Na zawsze, bo
kolejne przebiegi widziały tę samą pustą kolumnę.

Dwa szczegóły, które muszą zostać takie, jakie są:

* naprawa stoi w WEWNĘTRZNYM ``try`` wokół samego ``commit()``, wyłącznie po
  UDANYM upsercie. W zewnętrznym ``except`` łapałaby też awarie SPRZED upsertu,
  a ostemplowanie oferty BEZ wektora wypycha ją na zawsze z jedynego zapytania
  naprawczego (``phase3``: ``WHERE embedding_id IS NULL``) — czyli kolumna
  zaczęłaby kłamać w drugą, znacznie gorszą stronę;
* naprawa ma WŁASNĄ sesję: sesja wołającego po padniętym commicie jest
  nieużywalna, więc zapis w niej byłby po prostu drugą porażką.
"""

import pytest
from sqlalchemy import text


async def _seed_job() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        client_id = (
            await db.execute(text("SELECT id FROM clients LIMIT 1"))
        ).scalar_one_or_none()
        if client_id is None:
            pytest.skip("brak klienta w bazie testowej")
        job = Job(client_id=client_id, title="DRYF 403 commit", status=JobStatus.draft)
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _read_and_drop(job_id: int):
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        value = (
            await db.execute(
                text("SELECT embedding_id FROM jobs WHERE id = :i"), {"i": job_id}
            )
        ).scalar_one()
        await db.execute(text("DELETE FROM jobs WHERE id = :i"), {"i": job_id})
        await db.commit()
        return value


@pytest.mark.asyncio
async def test_failed_commit_still_leaves_the_column_stamped(monkeypatch):
    """Wektor trafił do Qdranta, commit padł — kolumna i tak ma zostać ostemplowana."""
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services import embedding_service as es

    job_id = await _seed_job()

    async def _fake_embedding(_text):
        return [0.1] * 8

    monkeypatch.setattr(es, "generate_embedding", _fake_embedding)
    monkeypatch.setattr(es.asyncio, "to_thread", lambda fn, *a, **k: _noop())

    async def _noop():
        return None

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job is not None

        original_commit = db.commit

        async def _boom():
            raise RuntimeError("deadlock detected")

        db.commit = _boom  # type: ignore[method-assign]
        ok = await es.embed_job(job_id, db)
        db.commit = original_commit  # type: ignore[method-assign]

    assert ok is False, (
        "wołający MUSI zobaczyć porażkę — commit naprawdę padł, więc "
        "raportowanie sukcesu byłoby drugim kłamstwem"
    )
    assert await _read_and_drop(job_id) == str(job_id), (
        "wektor jest w Qdrancie, a kolumna została pusta — oferta cicho "
        "przestaje generować propozycje i podpowiedzi, i nic tego nie ponowi"
    )


@pytest.mark.asyncio
async def test_caller_session_survives_the_failed_commit(monkeypatch):
    """Po padniętym commicie sesja WOŁAJĄCEGO musi dalej działać.

    Bez `rollback()` sesja zostaje w stanie PendingRollbackError i pada nie
    tylko krok embeddingu, ale KAŻDE kolejne zapytanie. W
    `compute_proposal_for_job` intencją `except` jest „leć dalej bez warstwy
    semantycznej", a niecofnięta transakcja zabija też odczyt profilu wag —
    czyli nieudany embedding przewraca CAŁE liczenie propozycji. To ta sama
    klasa co samo #403: ścieżka awarii zatruwa to, co miało ją przeżyć.

    Test robi dokładnie to, co robi wołający: po `embed_job` sięga tą samą
    sesją po coś zupełnie niezwiązanego. Poprzednia wersja tego pliku tego NIE
    robiła i dlatego brak rollbacku przeszedł.
    """
    from app.core.database import AsyncSessionLocal
    from app.services import embedding_service as es

    job_id = await _seed_job()

    async def _fake_embedding(_text):
        return [0.1] * 8

    async def _noop():
        return None

    monkeypatch.setattr(es, "generate_embedding", _fake_embedding)
    monkeypatch.setattr(es.asyncio, "to_thread", lambda fn, *a, **k: _noop())

    async with AsyncSessionLocal() as db:
        original_commit = db.commit

        async def _boom():
            # Transakcja musi paść NAPRAWDĘ, a nie tylko udawać. Podmiana samej
            # metody `commit` na rzucającą nie brudzi sesji, więc
            # PendingRollbackError nigdy nie powstaje i test przechodzi także
            # bez `rollback()` — sprawdzałby atrapę zamiast mechanizmu (tak
            # wyglądała pierwsza wersja tego testu i dlatego niczego nie
            # trzymała). Nieudane zapytanie zostawia sesję w stanie
            # „wymaga rollbacku", czyli dokładnie tym, co robi zerwane
            # połączenie albo deadlock na produkcji.
            await db.execute(text("SELECT * FROM tabela_ktora_nie_istnieje"))

        db.commit = _boom  # type: ignore[method-assign]
        await es.embed_job(job_id, db)
        db.commit = original_commit  # type: ignore[method-assign]

        # Wołający leci dalej — to MUSI zadziałać.
        alive = await db.scalar(text("SELECT 1"))

    assert alive == 1, (
        "sesja wołającego jest martwa po nieudanym embedzie — wszystko poniżej "
        "w liczeniu propozycji przewróci się przez krok, który miał być "
        "best-effort"
    )
    await _read_and_drop(job_id)


@pytest.mark.asyncio
async def test_failure_before_the_upsert_does_not_stamp(monkeypatch):
    """Brak wektora NIE MOŻE zostać ostemplowany.

    To jest odwrotny błąd i groźniejszy: ostemplowana oferta bez wektora wypada
    na zawsze z ``WHERE embedding_id IS NULL``, czyli z jedynej ścieżki naprawy.
    """
    from app.core.database import AsyncSessionLocal
    from app.services import embedding_service as es

    job_id = await _seed_job()

    async def _no_embedding(_text):
        return None  # Voyage nie odpowiedział — wektor NIE powstał

    monkeypatch.setattr(es, "generate_embedding", _no_embedding)

    async with AsyncSessionLocal() as db:
        ok = await es.embed_job(job_id, db)

    assert ok is False
    assert await _read_and_drop(job_id) is None, (
        "ostemplowano ofertę, dla której wektor nigdy nie powstał — taka "
        "oferta nie zostanie już nigdy naprawiona"
    )


def test_similar_jobs_search_bounds_its_qdrant_call():
    """Wywołanie Qdranta na ścieżce żądania użytkownika musi mieć sufit czasu.

    Bramka ``if not job.embedding_id: return []``, którą #403 zdjęło, była
    PRZYPADKOWĄ tarczą: kończyła wywołanie natychmiast, więc dla oferty z pustą
    kolumną nigdy tu nie docieraliśmy. Bez niej oba tiery podpowiedzi pytają
    Qdranta dla każdej takiej oferty — synchronicznie, w trakcie żądania
    użytkownika. ``qdrant-client`` bez ``timeout=`` spada na domyślny ~5 s
    httpx, czyli do ~10 s na żądanie przy brown-oucie Qdranta.

    Test czyta ŹRÓDŁO, bo sufit jest własnością konstrukcji klienta: podmiana
    klienta w monkeypatchu sprawdzałaby atrapę, a nie to, co pojedzie na prod.
    """
    import ast
    import pathlib

    src = pathlib.Path(
        pathlib.Path(__file__).resolve().parent.parent
        / "app/services/embedding_service.py"
    ).read_text()
    tree = ast.parse(src)
    target = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "search_similar_jobs_by_job_id"
    )
    clients = [
        n
        for n in ast.walk(target)
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "QdrantClient"
    ]
    assert clients, (
        "nie znaleziono konstrukcji QdrantClient — zmienił się kształt funkcji"
    )
    for call in clients:
        kwargs = {k.arg for k in call.keywords}
        assert "timeout" in kwargs, (
            "QdrantClient bez `timeout=` na ścieżce żądania użytkownika — "
            "domyślny ~5 s httpx zawiesza rekrutera zamiast szybko zdegradować"
        )
