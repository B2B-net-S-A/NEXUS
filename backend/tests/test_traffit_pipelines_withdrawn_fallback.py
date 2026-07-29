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
from app.services.traffit.importer import TraffitImporter, WithdrawnReasonFallback

# Format, w jakim Traffit zwraca daty (mapper go parsuje).
MOVED_AT = "2026-07-01 10:00:00"
# Ta sama chwila jako obiekt — asyncpg wymaga datetime dla bindów TIMESTAMPTZ.
MOVED_AT_DT = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)


# ── Jednostkowo: warstwy fallbacku ───────────────────────────────────────────


def test_fallback_prefers_job_template():
    fb = WithdrawnReasonFallback(by_job={10: 77}, by_stage_def={20: 88}, default_id=99)
    assert fb.resolve("withdrawn", 10, 20) == 77


def test_fallback_falls_back_to_stage_def_template():
    # Warunek prodowy: job bez template'u (spoza by_job), ale stage_def ma swój.
    fb = WithdrawnReasonFallback(by_job={10: 77}, by_stage_def={20: 88}, default_id=99)
    assert fb.resolve("withdrawn", 4242, 20) == 88
    assert fb.resolve("withdrawn", None, 20) == 88


def test_fallback_falls_back_to_default_template():
    fb = WithdrawnReasonFallback(by_job={10: 77}, by_stage_def={20: 88}, default_id=99)
    assert fb.resolve("withdrawn", 4242, 4242) == 99
    assert fb.resolve("withdrawn", None, None) == 99


def test_fallback_never_returns_none_when_any_template_seeded():
    # Sedno naprawy: dopóki istnieje CHOĆ JEDEN legacy_unknown, withdrawn ma
    # powód. Wcześniej brak wpisu w by_job = None = CheckViolationError.
    fb = WithdrawnReasonFallback(default_id=99)
    assert fb.resolve("withdrawn", None, None) == 99
    assert fb.resolve("withdrawn", 1, 2) == 99


def test_fallback_never_for_other_stages():
    fb = WithdrawnReasonFallback(by_job={10: 77}, by_stage_def={20: 88}, default_id=99)
    for stage in ("rejected", "hired", "screening", "interview", "cv_sent", "new"):
        assert fb.resolve(stage, 10, 20) is None, stage


def test_fallback_unresolvable_only_without_any_seed():
    fb = WithdrawnReasonFallback()
    assert fb.resolve("withdrawn", 1, 2) is None


# ── Fake klient Traffita ─────────────────────────────────────────────────────


class _FakeTraffit:
    """Minimalny stub — importer używa tylko total_count + get_paginated."""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records

    async def total_count(self, path: str) -> int:
        return len(self._records)

    async def get_paginated(
        self,
        path: str,
        *,
        page_size: int = 100,
        skip_on_5xx: bool = False,
        filter_: Optional[dict] = None,
    ) -> AsyncIterator[dict[str, Any]]:
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


@pytest.mark.asyncio
async def test_withdrawn_move_imports_with_fallback_reason(
    prod_shaped_withdrawn_move,
):
    """Sedno: ruch withdrawn na jobie bez template'u WCHODZI, errors == 0."""
    ids = prod_shaped_withdrawn_move
    async with AsyncSessionLocal() as db:
        importer = TraffitImporter(_FakeTraffit([ids["record"]]), db)
        progress = await importer.import_pipelines()

    assert progress.errors == 0, f"regresja: {progress.error_samples}"
    assert progress.skipped == 0
    assert progress.inserted == 1, "ruch withdrawn musi wejść, nie zniknąć"

    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    """
                    SELECT cs.stage::text AS stage, cs.rejection_reason_id,
                           rr.name AS reason_name, rr.template_id, rr.active
                    FROM candidate_stages cs
                    JOIN rejection_reasons rr ON rr.id = cs.rejection_reason_id
                    WHERE cs.external_source = 'traffit'
                      AND cs.external_id = :ext
                    """
                ),
                {"ext": ids["history_ext"]},
            )
        ).one()

    assert row.stage == "withdrawn"
    assert row.rejection_reason_id is not None
    # Warstwa 2 fallbacku: powód z template'u DEFINICJI ETAPU (job go nie ma).
    assert row.template_id == ids["template_id"]
    assert row.reason_name == "legacy_unknown"
    assert row.active is False, (
        "fallback nie może trafić do pick-listy rekrutera ani udawać "
        "realnej przyczyny wycofania"
    )


@pytest.mark.asyncio
async def test_reimport_is_idempotent_and_stays_clean(prod_shaped_withdrawn_move):
    """Dzienny sync przechodzi po tych samych rekordach — drugi przebieg to
    UPDATE bez błędów (inaczej health nigdy nie wróci do healthy)."""
    ids = prod_shaped_withdrawn_move
    async with AsyncSessionLocal() as db:
        first = await TraffitImporter(
            _FakeTraffit([ids["record"]]), db
        ).import_pipelines()
    assert first.errors == 0

    async with AsyncSessionLocal() as db:
        second = await TraffitImporter(
            _FakeTraffit([ids["record"]]), db
        ).import_pipelines()

    assert second.errors == 0, f"regresja na re-runie: {second.error_samples}"
    assert second.inserted == 0
    assert second.updated == 1

    async with AsyncSessionLocal() as db:
        count = (
            await db.execute(
                text(
                    "SELECT COUNT(*) FROM candidate_stages "
                    "WHERE external_source='traffit' AND external_id = :ext"
                ),
                {"ext": ids["history_ext"]},
            )
        ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_fallback_never_clobbers_a_real_reason(prod_shaped_withdrawn_move):
    """Powód wybrany przez rekrutera / z rejection_backfill wygrywa z fallbackiem."""
    ids = prod_shaped_withdrawn_move
    async with AsyncSessionLocal() as db:
        await TraffitImporter(_FakeTraffit([ids["record"]]), db).import_pipelines()

    async with AsyncSessionLocal() as db:
        real_reason_id = (
            await db.execute(
                text(
                    """
                    INSERT INTO rejection_reasons
                        (template_id, name, category, "order", active,
                         created_at, updated_at)
                    VALUES (:tpl, 'Kontroferta', 'withdrawn', 1, TRUE,
                            NOW(), NOW())
                    RETURNING id
                    """
                ),
                {"tpl": ids["template_id"]},
            )
        ).scalar_one()
        await db.execute(
            text(
                "UPDATE candidate_stages SET rejection_reason_id = :rid "
                "WHERE external_source='traffit' AND external_id = :ext"
            ),
            {"rid": real_reason_id, "ext": ids["history_ext"]},
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        progress = await TraffitImporter(
            _FakeTraffit([ids["record"]]), db
        ).import_pipelines()
    assert progress.errors == 0

    async with AsyncSessionLocal() as db:
        kept = (
            await db.execute(
                text(
                    "SELECT rejection_reason_id FROM candidate_stages "
                    "WHERE external_source='traffit' AND external_id = :ext"
                ),
                {"ext": ids["history_ext"]},
            )
        ).scalar_one()
    assert kept == real_reason_id


# ── Kontrakt: withdrawn bez fallbacku to SKIP, nie ERROR ─────────────────────


def test_unresolvable_withdrawn_counts_as_skip_not_error():
    """``errors>0`` blokuje watermark i trzyma health=degraded, więc znany,
    deterministyczny brak seeda musi iść do ``skipped`` z jawnym logiem."""
    import inspect

    src = inspect.getsource(TraffitImporter.import_pipelines)
    assert "progress.skipped += 1" in src
    assert "_fallback_rejection_reason_id" in src
    # Fallback liczony PRZED INSERT-em, żeby nie ubijać transakcji. INSERT
    # mieszka w `_upsert_stage_row`, więc kolejność mierzymy po jego wywołaniu.
    assert "INSERT INTO candidate_stages" in inspect.getsource(
        TraffitImporter._upsert_stage_row
    )
    assert src.index("_fallback_rejection_reason_id") < src.index(
        "_upsert_stage_row("
    )


# ── Regresja bug #2: adopt nie może kraść cudzego external_id ────────────────


@pytest.mark.asyncio
async def test_adopt_does_not_steal_external_id_from_owner():
    """Prod: ``upsert candidate ext=48895: UniqueViolationError``.

    Traffit dopisał maila pracownikowi, który w Nexusie istnieje TAKŻE jako
    osobny wiersz. Ścieżka "adopt" stemplowała external_id na wiersz dopasowany
    po mailu, kolidując z ``ux_candidates_external_source_id`` właściciela.
    """
    unique = uuid.uuid4().hex[:8]
    ext_id = f"tw-dup-{unique}"
    email = f"tw-dup-{unique}@example.com"

    async with AsyncSessionLocal() as db:
        owner = Candidate(
            name="Wlasciciel",
            lastname=f"Ext-{unique}",
            external_source="traffit",
            external_id=ext_id,
        )
        email_holder = Candidate(
            name="Posiadacz",
            lastname=f"Maila-{unique}",
            email=email,
        )
        db.add_all([owner, email_holder])
        await db.commit()
        owner_id, holder_id = owner.id, email_holder.id

    async with AsyncSessionLocal() as db:
        ext_to_id = await TraffitImporter(
            _FakeTraffit([]), db
        )._build_candidate_external_id_map()

    # Import widzi maila (→ holder) i external_id (→ owner). Musi wybrać ownera,
    # inaczej UPDATE narusza unique (external_source, external_id).
    assert ext_to_id.get(ext_id) == owner_id
    assert owner_id != holder_id

    import inspect

    src = inspect.getsource(TraffitImporter.import_candidates)
    assert "_build_candidate_external_id_map" in src
    assert "owner_id" in src
    assert "existing_id = owner_id" in src


@pytest.mark.asyncio
async def test_adopt_updates_owner_row_without_touching_email():
    """``_UPDATE_CANDIDATE_ADOPT`` nie rusza kolumny ``email`` — dzięki temu
    aktualizacja właściciela nie może naruszyć ``ix_candidates_email``."""
    from app.services.traffit.importer import _UPDATE_CANDIDATE_ADOPT

    sql = str(_UPDATE_CANDIDATE_ADOPT)
    assert "email" not in sql.split("WHERE id")[0].replace("cv_extracted_data", "")
