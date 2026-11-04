"""Study P: why are the people the team added to the 25.09 recruitments hidden by the search rubrics?
No scoring — only the production dealbreakers, with and without the must-have gate. Plus: the office
location as captured vs how the client e-mail describes it."""
import ro_boot  # noqa: F401
import asyncio, json, re
from collections import Counter, defaultdict
import data


async def main():
    await data.boot()
    from sqlalchemy import select, text
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.services.requirement_contract import search_dealbreaker_inputs
    from app.services.dealbreaker_filters import apply_dealbreakers
    from app.services import champion_view
    import datetime as dt
    out = {"jobs": {}, "totals": defaultdict(Counter)}
    async with AsyncSessionLocal() as db:
        jobs = (await db.execute(select(Job).where(Job.external_source == "manual", Job.created_at >= dt.datetime(2026, 9, 25, tzinfo=dt.timezone.utc)))).scalars().all()
        for j in jobs:
            added = [c for (c,) in (await db.execute(text("SELECT DISTINCT candidate_id FROM candidate_stages WHERE job_id=:j"), {"j": j.id})).all()]
            if not added:
                continue
            cs = (await db.execute(select(Candidate).where(Candidate.id.in_(added)))).scalars().all()
            row = {"title": (j.working_title or j.title)[:55], "added": len(cs),
                   "location_field": j.location, "remote_policy": getattr(j.remote_policy, "value", j.remote_policy),
                   "onsite_days": j.onsite_days_per_week, "budget": float(j.rate_budget_hourly) if j.rate_budget_hourly else None,
                   "email_mentions_cities": sorted(set(m.lower() for m in re.findall(r"(Warszaw\w*|Warsaw|Gdańsk|Gdansk|Gdyni\w*|Krak\w+|Wrocław\w*|Łód\w+|Poznań|Katowic\w*|Szczecin|Lublin|remote|zdaln\w*)", j.description or "", re.I)))}
            for name, inputs in (("prod", search_dealbreaker_inputs(j)), ("no_must", search_dealbreaker_inputs(j, exclude_missing_must=False))):
                r = apply_dealbreakers(list(cs), inputs=inputs)
                reasons = Counter(r.exclusion_reasons.get(c.id, "visible") for c in cs)
                row[name] = dict(reasons)
                out["totals"][name].update(reasons)
            # candidates' own city for those hidden by city
            r = apply_dealbreakers(list(cs), inputs=search_dealbreaker_inputs(j, exclude_missing_must=False))
            row["hidden_by_city_cand_cities"] = Counter((c.city or c.location or "?").split(",")[0].strip()[:20] for c in cs if r.exclusion_reasons.get(c.id) == "office_city_mismatch").most_common(6)
            row["over_budget_rates"] = sorted(float(c.expected_rate_hourly) for c in cs if r.exclusion_reasons.get(c.id) == "over_budget" and c.expected_rate_hourly)
            out["jobs"][j.id] = row
    out["totals"] = {k: dict(v) for k, v in out["totals"].items()}
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
    json.dump(out, open("/research/out_reasons.json", "w"), indent=1, ensure_ascii=False, default=str)


if __name__ == "__main__":
    asyncio.run(main())
