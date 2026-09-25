"""Trzy nazwy rekrutacji (0379, 25.09.2026).

- reguła tytułu dla rekrutera = ten sam plik przypadków co front;
- lustro migracji w ``entrypoint.sh`` (prod alembic bywa osierocony);
- nowe kolumny należą do NEXUSA (sync Traffita ich nie pisze);
- odczyt maila przyjmuje nazwę i numer od klienta tylko jako dosłowny cytat;
- numer projektu w CV bierze ``client_reference`` przed regexem z tytułu;
- automat tytułu: ręczny zapis go wyłącza, pusty przywraca, Champion przelicza.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.job_column_ownership import NEXUS_OWNED
from app.services.job_working_title import (
    compose_working_title,
    display_title,
    reference_from_title,
    working_title_for_job,
)

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
MIGRATION = (
    BACKEND
    / "alembic"
    / "versions"
    / "0379_job_client_reference_working_title.py"
)
CASES = json.loads(
    (ROOT / "frontend/src/lib/__fixtures__/job-working-title-cases.json").read_text()
)["cases"]
needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_compose_matches_the_shared_cases(case) -> None:
    given = case["input"]
    assert (
        compose_working_title(
            given["role"], given["must"], given["min_years"], given["domain"]
        )
        == case["expected"]
    )


def test_compose_drops_trailing_parts_before_cutting_the_role() -> None:
    title = compose_working_title("R" * 200, ["Java"], 5, "D" * 80)
    assert title is not None and len(title) <= 255
    assert title.startswith("R" * 200) and "D" * 80 not in title


def test_migration_is_chained_and_mirrored() -> None:
    spec = importlib.util.spec_from_file_location("m0379", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.down_revision == "0378_archive_jobs_before_nexus_start"
    entrypoint = _collapse((BACKEND / "entrypoint.sh").read_text())
    for statement in module.ADD_COLUMNS:
        assert "IF NOT EXISTS" in statement
        assert _collapse(statement) in entrypoint
    assert 'startup_phase "job-names-backfill"' in entrypoint


def test_new_columns_are_never_written_by_the_traffit_sync() -> None:
    assert {"client_reference", "working_title", "working_title_auto"} <= NEXUS_OWNED


def test_reference_from_title_only_when_unambiguous() -> None:
    assert reference_from_title("Java Dev (ZOB 4521)", None) == "ZOB 4521"
    assert reference_from_title("Java Dev", "ZOB-4521") == "ZOB 4521"
    assert reference_from_title("ZOB 1 i ZOB 2", None) is None
    assert reference_from_title("BP/007/2026", None) is None


def test_working_title_prefers_champion_and_falls_back_to_the_title() -> None:
    champion = SimpleNamespace(
        title="Programista Java (ZOB 48213)",
        client_reference="ZOB 48213",
        must_skills=["Oracle"],
        champion_profile={
            "basics": {"role_name": "Java Developer", "seniority_min_years": 5},
            "stack": {"must": [{"name": "Java"}, {"name": "Kafka"}]},
            "experience": {
                "domains": [
                    {"name": "Leasing", "level": "nice"},
                    {"name": "Payments", "level": "must"},
                ]
            },
        },
    )
    assert (
        working_title_for_job(champion)
        == "Java Developer · Java, Kafka · 5+ lat · Payments"
    )

    bare = SimpleNamespace(
        title="PKO BP - Programista Java ZOB 48213",
        client_reference=None,
        must_skills=[{"name": "Java"}],
        champion_profile=None,
    )
    assert working_title_for_job(bare, ["PKO BP"]) == "Programista Java · Java"
    quoted = SimpleNamespace(
        title="Programista Java (ZOB 48213)",
        client_reference="ZOB 48213",
        must_skills=["Java"],
        champion_profile=None,
    )
    assert working_title_for_job(quoted) == "Programista Java · Java"


def test_display_title_falls_back_to_the_client_title() -> None:
    assert display_title(SimpleNamespace(working_title=None, title="A")) == "A"
    assert display_title(SimpleNamespace(working_title=" B ", title="A")) == "B"


def test_intake_keeps_client_title_and_reference_only_as_quotes() -> None:
    from app.services.job_request_intake import normalize_model_output

    text = "Dzień dobry, szukamy: Programista Java (ZOB 48213). Java, Kafka, 5 lat."
    quoted = normalize_model_output(
        {
            "role_name": "Java Developer",
            "client_title": "Programista Java (ZOB 48213)",
            "client_reference": "ZOB 48213",
            "must": ["Java", "Kafka"],
            "seniority_min_years": 5,
        },
        text,
    )
    assert quoted.client_title == "Programista Java (ZOB 48213)"
    assert quoted.client_reference == "ZOB 48213"
    assert quoted.working_title_suggestion == "Java Developer · Java, Kafka · 5+ lat"
    assert quoted.provenance["client_reference"] == "request"

    invented = normalize_model_output(
        {"client_title": "Senior Java", "client_reference": "ZOB 99999"}, text
    )
    assert invented.client_title is None
    assert invented.client_reference is None


def test_project_ref_prefers_the_client_reference() -> None:
    from app.services.cv_packages import pko_job_reference

    job = SimpleNamespace(
        client_reference="ZOB 777", title="Java ZOB 4521", reference_number=None
    )
    assert pko_job_reference(job) == "777"
    legacy = SimpleNamespace(
        client_reference=None, title="Java ZOB 4521", reference_number=None
    )
    assert pko_job_reference(legacy) == "4521"
    other = SimpleNamespace(
        client_reference="SAP 4500123456", title="x", reference_number=None
    )
    assert pko_job_reference(other) == "SAP 4500123456"
    # Numer jest dosłownym cytatem z maila — zapis klienta nie może wyciec do CV.
    for written in ("ZOB: 48213", "nr ZOB 48213", "ZOB/48213", "zob-48213"):
        quoted = SimpleNamespace(
            client_reference=written, title="x", reference_number=None
        )
        assert pko_job_reference(quoted) == "48213", written


async def _client_id() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        client = Client(name=f"wt-{uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.commit()
        return client.id


@needs_db
@pytest.mark.asyncio
async def test_working_title_follows_edits_until_set_by_hand(
    app_client, app_auth_headers
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job

    created = await app_client.post(
        "/api/jobs",
        json={
            "title": "Programista Java (ZOB 48213)",
            "client_id": await _client_id(),
            "client_reference": "  ZOB   48213 ",
            "must_skills": ["Java"],
        },
        headers=app_auth_headers,
    )
    assert created.status_code in (200, 201), created.text
    body = created.json()
    job_id = body["id"]
    assert body["client_reference"] == "ZOB 48213"
    assert body["working_title_auto"] is True
    assert body["working_title"] == "Programista Java · Java"

    champion = await app_client.put(
        f"/api/jobs/{job_id}/champion-profile",
        json={
            "basics": {"role_name": "Java Developer", "seniority_min_years": 5},
            "stack": {"must": [{"name": "Java"}, {"name": "Kafka"}]},
            "experience": {"domains": [{"name": "Payments", "level": "must"}]},
        },
        headers=app_auth_headers,
    )
    assert champion.status_code == 200, champion.text
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job.working_title == "Java Developer · Java, Kafka · 5+ lat · Payments"

    manual = await app_client.patch(
        f"/api/jobs/{job_id}",
        json={"working_title": "Java/Kafka do płatności"},
        headers=app_auth_headers,
    )
    assert manual.status_code == 200, manual.text
    again = await app_client.put(
        f"/api/jobs/{job_id}/champion-profile",
        json={"basics": {"role_name": "Senior Java Developer"}},
        headers=app_auth_headers,
    )
    assert again.status_code == 200, again.text
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert (job.working_title, job.working_title_auto) == (
            "Java/Kafka do płatności",
            False,
        )

    reset = await app_client.patch(
        f"/api/jobs/{job_id}",
        json={"working_title": ""},
        headers=app_auth_headers,
    )
    assert reset.status_code == 200, reset.text
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job.working_title_auto is True
        assert job.working_title.startswith("Senior Java Developer · Java, Kafka")


@needs_db
@pytest.mark.asyncio
async def test_list_search_finds_the_client_reference(
    app_client, app_auth_headers
) -> None:
    marker = uuid.uuid4().hex[:6].upper()
    created = await app_client.post(
        "/api/jobs",
        json={
            "title": "Analityk",
            "client_id": await _client_id(),
            "client_reference": f"REQ-{marker}",
        },
        headers=app_auth_headers,
    )
    assert created.status_code in (200, 201), created.text
    found = await app_client.get(
        "/api/jobs", params={"q": f"REQ-{marker}"}, headers=app_auth_headers
    )
    assert found.status_code == 200, found.text
    assert [j["id"] for j in found.json()["items"]] == [created.json()["id"]]


@needs_db
@pytest.mark.asyncio
async def test_backfill_fills_only_empty_names_without_touching_updated_at() -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services.job_working_title import fill_missing_job_names

    client_id = await _client_id()
    async with AsyncSessionLocal() as db:
        archive = Job(
            title="Programista Java (ZOB 4521)",
            client_id=client_id,
            must_skills=["Java", "Spring"],
        )
        manual = Job(
            title="Tester ZOB 77",
            client_id=client_id,
            client_reference="SAP 1",
            working_title="Ręczny",
            working_title_auto=False,
        )
        db.add_all([archive, manual])
        await db.commit()
        ids = {archive.id, manual.id}
        stamps = {archive.id: archive.updated_at, manual.id: manual.updated_at}

    async with AsyncSessionLocal() as db:
        receipt = await fill_missing_job_names(db, only_job_ids=ids)
        await db.commit()
    assert receipt == {"jobs_seen": 1, "working_titles": 1, "client_references": 1}

    async with AsyncSessionLocal() as db:
        filled = await db.get(Job, archive.id)
        kept = await db.get(Job, manual.id)
        assert filled.client_reference == "ZOB 4521"
        assert filled.working_title == "Programista Java · Java, Spring"
        assert filled.updated_at == stamps[archive.id]
        assert (kept.client_reference, kept.working_title) == ("SAP 1", "Ręczny")
