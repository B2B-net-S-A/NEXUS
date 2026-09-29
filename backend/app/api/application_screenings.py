"""„Odrzuceni przez AI” w rekrutacji (0404).

Zgłoszenia z linku rekrutacji, które przegląd AI zostawił w bazie
(``screened_out``) albo których nie udało się ocenić (``failed``). Lista
stoi zwinięta na górze kolumny „Nowi” — z powodem po polsku, cytatem z CV
i przyciskiem „Dodaj mimo to”.

Dostęp jak skrzynka „Propozycje” (``job_proposals.py``): odczyt = sekcja
Pipeline + dostęp do rekrutacji (``_authorized_job``), „Dodaj mimo to” =
to, czego wymaga dodanie kandydata do rekrutacji (``RecruiterPlus`` +
członkostwo w zespole). Lista niesie tożsamość węższą niż profil — bez
e-maila i telefonu.
"""

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, RecruiterPlus, get_db
from app.api.recruitment_access import ensure_job_membership
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.models.application_screening import ApplicationScreening
from app.models.candidate import Candidate
from app.services import application_screening as screening

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

_LIST_LIMIT = 50


async def _job(db, user, job_id: int):
    from app.api.candidate_search import (  # noqa: PLC0415
        _authorized_job,
        _search_access,
    )

    _search_access(user)
    return await _authorized_job(db, user, job_id)


def _reasons(row: ApplicationScreening) -> list[dict]:
    reasons = row.reasons if isinstance(row.reasons, list) else []
    out = []
    for item in reasons:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if text:
            out.append({"text": text, "quote": str(item.get("quote") or "") or None})
    if not out and row.status == "failed":
        out.append(
            {
                "text": "Nie udało się ocenić ani dodać zgłoszenia automatycznie.",
                "quote": None,
            }
        )
    return out


def _source(row: ApplicationScreening) -> Optional[str]:
    context = row.context if isinstance(row.context, dict) else {}
    value = context.get("utm_source")
    return str(value) if value else None


@router.get("/jobs/{job_id}/screened-out")
async def list_screened_out(
    job_id: int,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _job(db, user, job_id)
    where = (ApplicationScreening.job_id == job_id, screening.listed_clause())
    total = int(
        await db.scalar(select(func.count(ApplicationScreening.id)).where(*where)) or 0
    )
    rows = (
        await db.execute(
            select(ApplicationScreening, Candidate.name, Candidate.lastname)
            .join(Candidate, Candidate.id == ApplicationScreening.candidate_id)
            .where(*where)
            .order_by(ApplicationScreening.created_at.desc())
            .limit(_LIST_LIMIT)
        )
    ).all()
    items = [
        {
            "id": row.id,
            "candidate_id": row.candidate_id,
            "name": name,
            "lastname": lastname,
            "applied_at": row.created_at,
            "decided_at": row.decided_at,
            "status": row.status,
            "verdict": row.verdict,
            "source": _source(row),
            "must_found": row.must_found,
            "must_total": row.must_total,
            "reasons": _reasons(row),
        }
        for row, name, lastname in rows
    ]
    return {"job_id": job_id, "total": total, "items": items}


@router.post("/jobs/{job_id}/screened-out/{screening_id}/add")
async def add_screened_out(
    job_id: int,
    screening_id: int,
    user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    await _job(db, user, job_id)
    await ensure_job_membership(db, user, job_id)
    row = await screening.add_despite(
        db, job_id=job_id, screening_id=screening_id, user_id=user.id
    )
    candidate_id = row.candidate_id
    await db.commit()
    return {"job_id": job_id, "candidate_id": candidate_id, "added": True}
