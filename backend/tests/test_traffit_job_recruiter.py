"""Import rekrutacji dopełnia pusty `recruiter_id` prowadzącym z Traffita.

Prod 22.09.2026: 310/310 opublikowanych rekrutacji z Traffita i 3970/3974
zamkniętych miało `recruiter_id` NULL, mimo że pełny sync 20.09 przeszedł
wszystkie 4259. Dwie przyczyny, obie po stronie importu, nie reguły upsertu:

1. odpowiedź LISTY `/recruitments/` nie ma pola `responsible_person` (ma je
   tylko detal `/recruitments/{id}`) — sprawdzone na żywym API 23.09.2026;
2. detal podaje je jako listę `[{"id", "email"}]`, a mapper czytał tylko dict.

Skutki: „Prowadzi: Nieprzypisany" na /jobs, 403 rekruterów na Tablicy
rekrutacji (`ensure_job_membership`), poranne skróty bez adresata.

Testy idą przez prawdziwego Postgresa i prawdziwe `import_jobs`, bo reguła
„nie nadpisuj prowadzącego ustawionego w NEXUSIE" siedzi w SQL upsertu.
Baza testowa jest wspólna — asercje tylko na własnych wierszach (uuid).
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.job import Job
from app.models.user import User, UserRole
from app.services.traffit.importer import TraffitImporter


class _Resp:
    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> Any:
        return self._body


class _JobsTraffit:
    """Lista bez `responsible_person` (jak prawdziwe API), detal z listą osób."""

    def __init__(
        self,
        users: list[dict],
        recruitments: list[dict],
        responsible: dict[str, list[dict]],
        failing: frozenset[str] = frozenset(),
    ) -> None:
        self.users = users
        self.recruitments = recruitments
        self.responsible = responsible
        self.failing = failing
        self.detail_calls: list[str] = []

    async def total_count(self, path):
        return len(self.recruitments)

    async def get_paginated(self, path, *, page_size=100, filter_=None, **kw):
        rows = self.users if path == "/users/" else self.recruitments
        for r in rows:
            yield r

    async def _get_raw(self, path, *, page=1, page_size=100, extra_headers=None):
        ext = path.strip("/").split("/")[-1]
        self.detail_calls.append(ext)
        if ext in self.failing:
            return _Resp(500, {})
        rec = next(r for r in self.recruitments if str(r["id"]) == ext)
        return _Resp(200, {**rec, "responsible_person": self.responsible.get(ext, [])})


async def _seed(tag: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        traffit_owner = User(
            email=f"traffit-owner-{tag}@example.com",
            name="Prowadzący z Traffita",
            password_hash="not-a-login",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
        )
        nexus_owner = User(
            email=f"nexus-owner-{tag}@example.com",
            name="Prowadzący z NEXUSA",
            password_hash="not-a-login",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
        )
        client = Client(
            name=f"Klient {tag}", external_source="traffit", external_id=f"c-{tag}"
        )
        db.add_all([traffit_owner, nexus_owner, client])
        await db.flush()

        def job(ext: str, **kw) -> Job:
            return Job(
                title=f"Rekrutacja {ext}",
                client_id=client.id,
                external_source="traffit",
                external_id=ext,
                **kw,
            )

        db.add_all(
            [
                job(f"empty-{tag}"),
                job(f"nexus-owned-{tag}", recruiter_id=nexus_owner.id),
                job(f"handed-off-{tag}", is_open=True),
                job(f"detail-fails-{tag}"),
            ]
        )
        await db.commit()
        return {
            "traffit_owner": traffit_owner.id,
            "nexus_owner": nexus_owner.id,
            "traffit_user": {"id": f"tu-{tag}", "email": traffit_owner.email},
        }


async def _recruiter(ext: str) -> Optional[int]:
    async with AsyncSessionLocal() as db:
        row = await db.execute(
            text(
                "SELECT recruiter_id FROM jobs "
                "WHERE external_source = 'traffit' AND external_id = :e"
            ),
            {"e": ext},
        )
        return row.scalar_one()


@pytest.mark.asyncio
async def test_empty_recruiter_is_filled_from_traffit_without_overriding_nexus():
    tag = uuid.uuid4().hex[:10]
    seeded = await _seed(tag)
    exts = {
        name: f"{name}-{tag}"
        for name in ("new", "empty", "nexus-owned", "handed-off", "detail-fails")
    }
    person = [{"id": seeded["traffit_user"]["id"], "email": "x@example.com"}]
    traffit = _JobsTraffit(
        users=[seeded["traffit_user"]],
        recruitments=[
            {"id": ext, "name": f"Rekrutacja {ext}", "client": {"id": f"c-{tag}"}}
            for ext in exts.values()
        ],
        responsible={ext: person for ext in exts.values()},
        failing=frozenset({exts["detail-fails"]}),
    )

    async with AsyncSessionLocal() as db:
        progress = await TraffitImporter(
            traffit, db, dry_run=False, batch_size=10
        ).import_jobs()

    # Sedno: nowy i pusty wiersz dostają prowadzącego z Traffita.
    assert await _recruiter(exts["new"]) == seeded["traffit_owner"]
    assert await _recruiter(exts["empty"]) == seeded["traffit_owner"]
    # Ustawiony w NEXUSIE zostaje — i nie kosztuje zapytania o detal.
    assert await _recruiter(exts["nexus-owned"]) == seeded["nexus_owner"]
    assert exts["nexus-owned"] not in traffit.detail_calls
    # Przekazana do NEXUSA z pustym prowadzącym to kolejka automatu przydziałów.
    assert await _recruiter(exts["handed-off"]) is None
    assert exts["handed-off"] not in traffit.detail_calls
    # Padnięty detal: wiersz z listy i tak zapisany, błąd policzony i przypięty.
    assert await _recruiter(exts["detail-fails"]) is None
    assert progress.errors == 1
    assert f"recruitment_detail:{exts['detail-fails']}" in progress.error_refs

    assert progress.recruiter_resolved == 2
    assert progress.as_dict()["recruiter_resolved"] == 2
    assert progress.inserted + progress.updated == len(exts)


@pytest.mark.asyncio
async def test_second_run_does_not_refetch_filled_recruiters():
    """Po dopełnieniu delta nie płaci już za detal tej rekrutacji."""
    tag = uuid.uuid4().hex[:10]
    seeded = await _seed(tag)
    ext = f"empty-{tag}"
    traffit = _JobsTraffit(
        users=[seeded["traffit_user"]],
        recruitments=[{"id": ext, "name": "X", "client": {"id": f"c-{tag}"}}],
        responsible={ext: [{"id": seeded["traffit_user"]["id"]}]},
    )

    for _ in range(2):
        async with AsyncSessionLocal() as db:
            await TraffitImporter(
                traffit, db, dry_run=False, batch_size=10
            ).import_jobs()

    assert traffit.detail_calls == [ext]
    assert await _recruiter(ext) == seeded["traffit_owner"]
