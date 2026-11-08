"""Regresja: faza ``pipelines`` gubiła ruchy ``withdrawn` na constraincie 0068.

Produkcja (2026-07-27, logi dziennego syncu Traffita)::

    Traffit phase pipelines: {'processed': 179288, 'inserted': 0,
        'updated': 178740, 'skipped': 224, 'errors': 324}
    upsert stage ext=3480: IntegrityError(... CheckViolationError: new row for
    relation "candidate_stages" violates check constraint ...)

Przyczyna źródłowa: ``ck_candidate_stages_withdrawn_requires_reason`` (migracja
0068) wymaga ``rejection_reason_id NOT NULL`` dla ``stage='withdrawn'``, a
fallback powodu był rozwiązywany WYŁĄCZNIE przez ``jobs.pipeline_template_id``.
Na prodzie 4058 z 4075 jobów ma ten FK NULL (99,6%) — mapa pokrywała 17 jobów,
więc praktycznie każdy ruch ``withdrawn`` padał, 324 etapy nie wchodziły do bazy
na KAŻDYM syncu, a ``errors>0`` trzymało watermark i ``checks.traffit=degraded``.

Testy integracyjne wymagają Postgresa z ``alembic upgrade heads`` (jak CI).
Scenariusz odtwarza dokładnie warunek prodowy: **job bez pipeline_template_id**
+ stan workflow Traffita mapowany na legacy ``withdrawn``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    StageCategoryEnum,
)

# ``CortexSkillFact`` ma relationship do ``Skill``, którego ``app.models``
# nie re-eksportuje. Bez tego importu konfiguracja mapperów SQLAlchemy pada na
# "expression 'Skill' failed to locate a name" przy pierwszym użyciu ORM.
from app.models.skill import Skill  # noqa: F401

# Format, w jakim Traffit zwraca daty (mapper go parsuje).
MOVED_AT = "2026-07-01 10:00:00"
# Ta sama chwila jako obiekt — asyncpg wymaga datetime dla bindów TIMESTAMPTZ.
MOVED_AT_DT = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)


# ── Jednostkowo: warstwy fallbacku ───────────────────────────────────────────


# ── Fake klient Traffita ─────────────────────────────────────────────────────


class _FakeTraffit:
    """Minimalny stub — `import_pipelines` używa `total_count` + `get_pages`.

    `get_pages` (nie `get_paginated`) od czasu, gdy faza dostała kursor
    wznawiania: numer strony jest tym, co kursor utrwala, a `get_paginated`
    go nie wystawia.
    """

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records

    async def total_count(self, path: str) -> int:
        return len(self._records)

    async def get_pages(
        self,
        path: str,
        *,
        page_size: int = 100,
        skip_on_5xx: bool = False,
        filter_: Optional[dict] = None,
        start_page: int = 1,
    ) -> AsyncIterator[tuple[int, list[dict[str, Any]]]]:
        # Jedna strona wystarczy — te testy sprawdzają mapowanie `withdrawn`,
        # nie paginację; `start_page > 1` oznaczałoby, że wszystko już przeszło.
        if start_page <= 1 and self._records:
            yield 1, list(self._records)

    async def get_paginated(
        self,
        path: str,
        *,
        page_size: int = 100,
        skip_on_5xx: bool = False,
        filter_: Optional[dict] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        # Nadal potrzebne: `import_pipelines` woła `build_user_id_map`, które
        # ciągnie /users/ tą metodą. Zwraca te same rekordy co `get_pages` —
        # dla /users/ mapowanie po emailu i tak nic z nich nie dopasuje.
        for record in self._records:
            yield record


@pytest_asyncio.fixture
async def prod_shaped_withdrawn_move():
    """Job BEZ pipeline_template_id + stan Traffita mapowany na withdrawn."""
    unique = uuid.uuid4().hex[:8]
    # Traffit id-ki muszą być unikalne (partial unique na external_source+id).
    emp_ext = f"tw-emp-{unique}"
    rec_ext = f"tw-rec-{unique}"
    state_ext = f"tw-state-{unique}"
    history_ext = f"tw-hist-{unique}"

    async with AsyncSessionLocal() as db:
        template = PipelineTemplate(
            name=f"Traffit withdrawn tpl {unique}",
            external_source="traffit",
            external_id=f"tw-tpl-{unique}",
        )
        client = Client(name=f"Traffit withdrawn client {unique}")
        db.add_all([template, client])
        await db.flush()

        stage_def = PipelineStageDef(
            template_id=template.id,
            name=f"Współpraca zakończona {unique}",
            order=1,
            category=StageCategoryEnum.terminal,
            legacy_enum_value="withdrawn",
            external_source="traffit",
            external_id=state_ext,
        )
        # KLUCZOWE: pipeline_template_id = NULL — stan 99,6% jobów na prodzie.
        job = Job(
            title=f"Traffit withdrawn job {unique}",
            client_id=client.id,
            external_source="traffit",
            external_id=rec_ext,
        )
        candidate = Candidate(
            name="Wycofany",
            lastname=f"Kandydat-{unique}",
            external_source="traffit",
            external_id=emp_ext,
        )
        db.add_all([stage_def, job, candidate])
        await db.commit()

        assert job.pipeline_template_id is None, (
            "fixture musi odtwarzać prodowy warunek: job bez pipeline'u"
        )
        return {
            "template_id": template.id,
            "stage_def_id": stage_def.id,
            "job_id": job.id,
            "candidate_id": candidate.id,
            "history_ext": history_ext,
            "record": {
                "id": history_ext,
                "employee": {"id": emp_ext},
                "recruitment": {"id": rec_ext},
                "workflow_state": {"id": state_ext},
                "date": MOVED_AT,
            },
        }


# ── Integracyjnie: dowód, że dane dziś łamiące constraint wchodzą ────────────


@pytest.mark.asyncio
async def test_constraint_really_rejects_withdrawn_without_reason(
    prod_shaped_withdrawn_move,
):
    """Tripwire: bez powodu DB ODRZUCA wiersz — czyli test niżej ma sens.

    To jest dokładnie ten INSERT, który importer wykonywał przed naprawą.
    """
    ids = prod_shaped_withdrawn_move
    async with AsyncSessionLocal() as db:
        with pytest.raises(IntegrityError) as exc:
            await db.execute(
                text(
                    """
                    INSERT INTO candidate_stages (
                        external_id, external_source, candidate_id, job_id,
                        stage_def_id, stage, moved_at, rejection_reason_id,
                        verification_status, created_at, updated_at
                    ) VALUES (
                        :ext, 'traffit', :cid, :jid, :sd,
                        CAST('withdrawn' AS pipelinestage),
                        CAST(:moved_at AS TIMESTAMPTZ), NULL,
                        CAST('active' AS verificationstatus), NOW(), NOW()
                    )
                    """
                ),
                {
                    "ext": f"{ids['history_ext']}-raw",
                    "cid": ids["candidate_id"],
                    "jid": ids["job_id"],
                    "sd": ids["stage_def_id"],
                    "moved_at": MOVED_AT_DT,
                },
            )
        await db.rollback()
    assert "ck_candidate_stages_withdrawn_requires_reason" in str(exc.value)


@pytest.mark.asyncio
async def test_job_template_only_lookup_would_miss_this_job(
    prod_shaped_withdrawn_move,
):
    """Dowód przyczyny źródłowej: STARA mapa (tylko po template'cie joba) tego
    joba nie zawiera, więc fallback zwracał None → CheckViolationError."""
    ids = prod_shaped_withdrawn_move
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            text(
                """
                SELECT j.id AS job_id
                FROM jobs j
                JOIN rejection_reasons rr
                  ON rr.template_id = j.pipeline_template_id
                WHERE rr.name = 'legacy_unknown'
                  AND rr.category = 'withdrawn'
                  AND j.id = :jid
                """
            ),
            {"jid": ids["job_id"]},
        )
        assert rows.fetchone() is None


# ── Kontrakt: withdrawn bez fallbacku to SKIP, nie ERROR ─────────────────────


# ── Regresja bug #2: adopt nie może kraść cudzego external_id ────────────────
