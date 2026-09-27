"""Zatwierdzony opis publiczny rekrutacji dla testów formularza zgłoszeń.

Runda 10 (R10-N10-9): stary `/api/public/apply/{token}` stosuje tę samą regułę
co `/r/{slug}` — bez zatwierdzonego opisu publicznego link daje 404. Testy
samego formularza zakładają opis tak, jak zapisuje go „Zatwierdź”.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.database import AsyncSessionLocal
from app.models.job import Job
from app.models.job_public_profile import JobPublicProfile
from app.services import job_public_profile as jpp


async def approve_public_profile(job_id: int) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job is not None, f"brak rekrutacji {job_id}"
        profile = await db.get(JobPublicProfile, job_id)
        if profile is None:
            profile = JobPublicProfile(job_id=job_id)
            db.add(profile)
        profile.about = profile.about or "Opis rekrutacji do testu."
        profile.sections = dict(jpp.normalize_sections(profile.sections))
        _default, title = await jpp.public_titles(db, job, profile)
        profile.approved_at = datetime.now(timezone.utc)
        profile.approved_hash = jpp.content_hash(
            profile.subtitle, profile.about, profile.sections, title
        )
        await db.commit()
        status, _default, _title = await jpp.resolve_status(db, job, profile)
    assert status == jpp.STATUS_APPROVED, status
