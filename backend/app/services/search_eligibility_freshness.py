"""Detect eligibility changes outside the visible page of a frozen search.

Candidate status/preferences are covered by population version checks. This
fingerprint covers the external client conflicts and manager vetoes, including
expiry without a database write. It stores no notes or personal details.
"""

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import or_, select

from app.models.candidate_conflict import CandidateConflict
from app.services.hiring_manager_verdicts import load_manager_rejections


async def eligibility_fingerprint(db, *, job, now=None) -> str:
    now = now or datetime.now(timezone.utc)
    conflicts = []
    if job.client_id is not None:
        rows = await db.execute(
            select(CandidateConflict.candidate_id, CandidateConflict.type).where(
                CandidateConflict.client_id == job.client_id,
                CandidateConflict.active.is_(True),
                or_(
                    CandidateConflict.expires_at.is_(None),
                    CandidateConflict.expires_at > now,
                ),
            )
        )
        conflicts = sorted({(cid, kind.value) for cid, kind in rows.all()})
    verdicts = await load_manager_rejections(db, job=job, candidate_ids=None)
    payload = {"version": 1, "conflicts": conflicts, "vetoes": sorted(verdicts)}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
