"""Pole „Szukaj" rejestru rekrutacji (`GET /api/jobs?q=`).

Placeholder w UI obiecuje „Tytuł, klient, technologia…". Do 09.2026 backend
filtrował wyłącznie po tytule i bez escapowania (`%` zwracało cały rejestr).
Kontrakt: `q` trafia w tytuł, numer referencyjny, nazwę klienta (także
`display_name`) i technologie z `must_skills`; znaki wieloznaczne LIKE są
dosłowne; `total` zgadza się z liczbą wierszy (klient przez EXISTS, nie JOIN).

Używa in-process `app_client` + `app_auth_headers` (admin widzi cały rejestr).
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal


async def _seed(
    *,
    title: str,
    client_name: str,
    client_display_name: str | None = None,
    reference_number: str | None = None,
    must_skills: list[str] | None = None,
) -> int:
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        cli = Client(name=client_name, display_name=client_display_name)
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=title,
            status=JobStatus.published,
            client_id=cli.id,
            reference_number=reference_number,
            must_skills=must_skills or [],
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _search(app_client: AsyncClient, headers: dict[str, str], q: str) -> dict:
    r = await app_client.get(
        "/api/jobs", headers=headers, params={"q": q, "page_size": 100}
    )
    assert r.status_code == 200, r.text
    return r.json()


def _ids(body: dict) -> set[int]:
    return {row["id"] for row in body["items"]}


async def test_q_matches_title_reference_client_and_skills(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    tag = uuid.uuid4().hex[:10]
    by_title = await _seed(title=f"Senior {tag}-Tytul", client_name=f"C-{tag}-a")
    by_ref = await _seed(
        title="Inny tytuł",
        client_name=f"C-{tag}-b",
        reference_number=f"REF-{tag}-ref",
    )
    by_client = await _seed(title="Bez tagu", client_name=f"Klient {tag}-cli")
    by_display = await _seed(
        title="Bez tagu 2",
        client_name="Nazwa surowa",
        client_display_name=f"Wyświetlana {tag}-disp",
    )
    by_skill = await _seed(
        title="Bez tagu 3",
        client_name=f"C-{tag}-e",
        must_skills=[f"Tech{tag}-skill", "Python"],
    )

    assert _ids(await _search(app_client, app_auth_headers, f"{tag}-Tytul")) == {
        by_title
    }
    assert _ids(await _search(app_client, app_auth_headers, f"{tag}-ref")) == {by_ref}
    assert _ids(await _search(app_client, app_auth_headers, f"{tag}-cli")) == {
        by_client
    }
    assert _ids(await _search(app_client, app_auth_headers, f"{tag}-disp")) == {
        by_display
    }
    assert _ids(await _search(app_client, app_auth_headers, f"tech{tag}-skill")) == {
        by_skill
    }

    # Wspólny fragment: wszystkie pięć, `total` = liczba wierszy.
    body = await _search(app_client, app_auth_headers, tag)
    assert _ids(body) == {by_title, by_ref, by_client, by_display, by_skill}
    assert body["total"] == 5


async def test_q_treats_like_wildcards_literally(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    tag = uuid.uuid4().hex[:10]
    with_percent = await _seed(title=f"Etat 50% {tag}", client_name=f"C-{tag}-p")
    plain = await _seed(title=f"Etat pelny {tag}", client_name=f"C-{tag}-q")

    body = await _search(app_client, app_auth_headers, f"50% {tag}")
    assert _ids(body) == {with_percent}
    assert plain not in _ids(body)

    # `_` nie jest już „dowolnym znakiem".
    body = await _search(app_client, app_auth_headers, f"Etat_pelny {tag}")
    assert _ids(body) == set()


async def test_q_folds_polish_diacritics_and_case(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    tag = uuid.uuid4().hex[:10]
    job_id = await _seed(title=f"Programista Żółw {tag}", client_name=f"C-{tag}-z")
    body = await _search(app_client, app_auth_headers, f"programista zolw {tag}")
    assert _ids(body) == {job_id}
