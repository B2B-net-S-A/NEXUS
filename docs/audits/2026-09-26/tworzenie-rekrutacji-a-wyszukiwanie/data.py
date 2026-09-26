"""Shared loaders for the search research. Read-only (import ro_boot first)."""
import os, pickle, random
from types import SimpleNamespace
from sqlalchemy import text, select

CACHE = "/research/cache"
os.makedirs(CACHE, exist_ok=True)

POS_STAGES = ("cv_sent", "interview", "client_interview", "acceptance", "hired")
STRONG = ("client_interview", "acceptance", "hired")
RANK = {"verified": 0, "cv_sent": 1, "interview": 1, "client_interview": 2, "acceptance": 3, "hired": 4}


async def boot():
    from app.services.skill_taxonomy_loader import refresh_alias_map
    await refresh_alias_map()


def _cache(name):
    return os.path.join(CACHE, name + ".pkl")


async def load_candidates(force=False):
    """id -> SimpleNamespace(known: set[str] canonical-lower, canon: set, meta...)."""
    p = _cache("cands")
    if os.path.exists(p) and not force:
        return pickle.load(open(p, "rb"))
    from app.core.database import AsyncSessionLocal
    from app.services.scoring_service import candidate_known_skill_names, _canon_skill
    out = {}
    async with AsyncSessionLocal() as db:
        res = await db.stream(text("""
            SELECT id, skills, verified_tech, tags,
                   jsonb_build_object(
                     'traffit_technologie', cv_extracted_data->'traffit_technologie',
                     'skills', cv_extracted_data->'skills',
                     '_manual_override_skills', cv_extracted_data->'_manual_override_skills',
                     'sectors', cv_extracted_data->'sectors') AS cvx,
                   left(raw_cv_text, 4000) AS raw, years_it_experience, languages,
                   city, location, expected_rate_hourly, status::text AS status,
                   competence_category_id
            FROM candidates"""))
        async for r in res:
            c = SimpleNamespace(id=r.id, skills=r.skills, verified_tech=r.verified_tech,
                                tags=r.tags, cv_extracted_data=r.cvx, raw_cv_text=r.raw)
            known = candidate_known_skill_names(c)
            out[r.id] = SimpleNamespace(
                id=r.id, known=set(known), canon={_canon_skill(k) for k in known},
                yoe=r.years_it_experience, languages=r.languages, city=r.city,
                location=r.location, rate=float(r.expected_rate_hourly) if r.expected_rate_hourly is not None else None,
                status=r.status, cc=r.competence_category_id,
                sectors=(r.cvx or {}).get("sectors"),
            )
    pickle.dump(out, open(p, "wb"))
    return out


async def load_positives(force=False):
    """job_id -> {candidate_id: best_rank}  (rank>=1 = sent to client)."""
    p = _cache("pos")
    if os.path.exists(p) and not force:
        return pickle.load(open(p, "rb"))
    from app.core.database import AsyncSessionLocal
    out = {}
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text("""
            SELECT job_id, candidate_id, stage::text AS stage FROM analytics_first_milestones
            WHERE job_id IS NOT NULL"""))).all()
    for j, c, s in rows:
        r = RANK.get(s)
        if r is None:
            continue
        d = out.setdefault(j, {})
        d[c] = max(d.get(c, -1), r)
    pickle.dump(out, open(p, "wb"))
    return out


async def load_jobs():
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    async with AsyncSessionLocal() as db:
        jobs = (await db.execute(select(Job))).scalars().all()
        for j in jobs:  # detach-safe copy of the attributes we need
            db.expunge(j)
    return jobs


def present(label, canon_set, known_set):
    """Mirror of scoring_service.skill_present on precomputed sets."""
    from app.services.requirement_contract import alternatives
    from app.services.scoring_service import ALIAS_MAP, _canon_skill
    opts = alternatives(label)
    if len(opts) > 1:
        return any(present(ALIAS_MAP.get(o.lower(), o), canon_set, known_set) for o in opts)
    return label in known_set or _canon_skill(label) in canon_set
