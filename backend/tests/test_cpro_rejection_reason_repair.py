"""Powód z treści maila CPro w bazie (B7, 19.11.2026): nowe maile i stare wpisy.

Automat poczty CPro wpisywał każde odrzucenie przez klienta jako „Inne”. Od tej
zmiany wybiera powód z szablonu po treści maila, a naprawa jednorazowa przepina
stare wpisy tym samym słownikiem. Szablon w teście ma własne powody, więc nie
zależy od seedów szablonu domyślnego.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.pipeline_template import PipelineTemplate, RejectionReason, TerminalType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services import cpro_mail
from app.services.cpro_rejection_reason_repair import run_cpro_rejection_reason_repair

pytestmark = pytest.mark.asyncio

NAMES = (
    "Inne (rejected)",
    "Nie spełnia wymagań technicznych",
    "Brak doświadczenia",
    "client_chose_other",
    "client_no_reason",
)


async def _template(db, *, with_names=NAMES) -> tuple[int, dict[str, int]]:
    template = PipelineTemplate(name=f"B7 szablon {uuid.uuid4().hex[:8]}")
    db.add(template)
    await db.flush()
    ids: dict[str, int] = {}
    for name in with_names:
        reason = RejectionReason(
            template_id=template.id, name=name, category=TerminalType.rejected
        )
        db.add(reason)
        await db.flush()
        ids[name] = reason.id
    return template.id, ids


async def test_reason_id_follows_the_mail_text_and_falls_back_to_other() -> None:
    async with AsyncSessionLocal() as db:
        template_id, ids = await _template(db)
        reason = lambda text: cpro_mail._reason_id(  # noqa: E731
            db, template_id, withdrawn=False, cpro_reason=text
        )
        assert await reason("Insufficient PM experience") == ids["Brak doświadczenia"]
        assert (
            await reason("too IT heavy profile")
            == ids["Nie spełnia wymagań technicznych"]
        )
        assert await reason(None) == ids["client_no_reason"]
        # Bez trafienia w słowniku: „Inne”, jak dotąd.
        assert await reason("Not available anymore!") == ids["Inne (rejected)"]
        # Słownik trafił, ale szablon nie ma powodu (admin skasował): „Inne”.
        assert (
            await reason("Duplicated and more expensive offer")
            == ids["Inne (rejected)"]
        )
        await db.rollback()


async def test_reason_id_without_other_in_template_is_none() -> None:
    async with AsyncSessionLocal() as db:
        template_id, _ = await _template(db, with_names=("Brak doświadczenia",))
        assert (
            await cpro_mail._reason_id(
                db, template_id, withdrawn=False, cpro_reason="Lorem ipsum"
            )
            is None
        )
        await db.rollback()


async def _rejection(
    db, template_id: int, reason_id: int, notes: str, ended_by: str
) -> int:
    unique = uuid.uuid4().hex[:8]
    client = Client(name=f"B7 klient {unique}")
    candidate = Candidate(
        name="Bsiedem", lastname=f"Osoba{unique}", email=f"b7-{unique}@example.com"
    )
    db.add_all([client, candidate])
    await db.flush()
    job = Job(
        title=f"B7 {unique}",
        client_id=client.id,
        status=JobStatus.published,
        pipeline_template_id=template_id,
    )
    db.add(job)
    await db.flush()
    stage = CandidateStage(
        candidate_id=candidate.id,
        job_id=job.id,
        stage=PipelineStage.rejected,
        moved_at=datetime.now(timezone.utc) - timedelta(days=2),
        rejection_reason_id=reason_id,
        notes=notes,
        ended_by=ended_by,
    )
    db.add(stage)
    await db.flush()
    return stage.id


async def test_repair_moves_cpro_rows_once_and_keeps_a_receipt() -> None:
    marker = f"b7_test_{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        template_id, ids = await _template(db)
        other = ids["Inne (rejected)"]
        rows = {
            "experience": await _rejection(
                db, template_id, other, "Z CPro: No PM exp", "client"
            ),
            "chose_other": await _rejection(
                db,
                template_id,
                other,
                "Z CPro: other candidate was selected for the role",
                "client",
            ),
            "no_match": await _rejection(
                db, template_id, other, "Z CPro: Not available anymore!", "client"
            ),
            # Ręczne „Inne” z opisem człowieka: naprawa go nie dotyka.
            "manual": await _rejection(db, template_id, other, "No PM exp", "client"),
            # Odrzucenie przez nas z dopiskiem o CPro: też nie.
            "ours": await _rejection(
                db, template_id, other, "Z CPro: No PM exp", "recruiter"
            ),
        }
        await db.commit()

    async with AsyncSessionLocal() as db:
        summary = await run_cpro_rejection_reason_repair(db, marker=marker)
        await db.commit()
    assert summary is not None

    async with AsyncSessionLocal() as db:
        reason_of = {
            key: await db.scalar(
                select(CandidateStage.rejection_reason_id).where(
                    CandidateStage.id == sid
                )
            )
            for key, sid in rows.items()
        }
        receipt = (await db.get(AppSetting, marker)).value

    assert reason_of["experience"] == ids["Brak doświadczenia"]
    assert reason_of["chose_other"] == ids["client_chose_other"]
    assert reason_of["no_match"] == other
    assert reason_of["manual"] == other
    assert reason_of["ours"] == other
    mine = {row[0]: row for row in receipt["rows"] if row[0] in rows.values()}
    assert mine == {
        rows["experience"]: [rows["experience"], other, ids["Brak doświadczenia"]],
        rows["chose_other"]: [rows["chose_other"], other, ids["client_chose_other"]],
    }
    assert receipt["kept_other"].get("no_match", 0) >= 1

    async with AsyncSessionLocal() as db:
        assert await run_cpro_rejection_reason_repair(db, marker=marker) is None
        await db.rollback()
