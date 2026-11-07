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


@router.post("/jobs/{job_id}/applicants/{candidate_id}/ai-check")
async def check_applicant_cv(
    job_id: int,
    candidate_id: int,
    user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """„Sprawdź w CV” dla osoby, która sama się zgłosiła (07.11.2026).

    Kolumna „Nowi” zwija zgłoszenia z brakiem umiejętności krytycznej, a ta
    liczy się ze słów w CV — „Agentic AI” opisane innymi słowami wypada.
    Ta sama ocena co przegląd zgłoszeń (``screening.assess``: kod liczy, model
    uzasadnia cytatem). Wynik ląduje w ``entry_meta.ai_check`` procesu, więc
    karta pokazuje „AI: pasuje” i wraca do „Aplikowali na ogłoszenie”.
    """
    from fastapi import HTTPException  # noqa: PLC0415

    from app.models.recruitment_process import RecruitmentProcess  # noqa: PLC0415
    from app.services.process_entry_meta import (  # noqa: PLC0415
        AI_CHECK_KEY,
        application_screening_badge,
    )

    job = await _job(db, user, job_id)
    await ensure_job_membership(db, user, job_id)
    process = await db.scalar(
        select(RecruitmentProcess).where(
            RecruitmentProcess.candidate_id == candidate_id,
            RecruitmentProcess.job_id == job_id,
        )
    )
    if process is None or process.entry_source != "application":
        raise HTTPException(
            status_code=404,
            detail="Ta osoba nie zgłosiła się sama do tej rekrutacji.",
        )
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej osoby.")
    result = await screening.assess(
        db,
        job=job,
        candidate=candidate,
        cv_text=candidate.raw_cv_text or "",
        use_model=True,
    )
    process = await db.scalar(
        select(RecruitmentProcess)
        .where(RecruitmentProcess.id == process.id)
        .with_for_update()
    )
    meta = dict(process.entry_meta or {})
    meta[AI_CHECK_KEY] = screening.entry_meta(result)
    process.entry_meta = meta
    await db.commit()
    return {
        "candidate_id": candidate_id,
        "badge": application_screening_badge(meta),
        "reasons": [
            {"text": str(r.get("text") or ""), "quote": r.get("quote") or None}
            for r in (result.reasons or [])
            if isinstance(r, dict)
        ],
        "error": result.error,
    }
