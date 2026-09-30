"""Które etykiety must bramkują (gate_requirement) — sprawdzenie na taksonomii produkcji."""
import ro_boot  # noqa: F401
import asyncio, json
import data

LABELS = ["software developer", "project management", "business analysis", "manual testing", "qa", "systems analysis",
          "backend developer", "frontend developer", "fullstack developer", "devops engineering", "it analysis", "ai",
          "data engineering", "doświadczenie z integracją systemów (on-premise, hybrid, cloud)",
          "umiejętność pracy w dynamicznym środowisku it (devops / application operations)", "test automation",
          "it consulting", "enterprise architecture", "certyfikat istqb", "standard testów funkcjonalnych", "test planning",
          "java", "spring boot", "kafka", "scrum / agile", "fastapi / rest api", "ddd"]


async def main():
    await data.boot()
    from app.services.must_gate_terms import gate_requirement, ignored_reason
    from app.services.scoring_service import job_explicit_must_skills
    out = {}
    for l in LABELS:
        r = gate_requirement(l)
        out[l] = {"gates": r is not None, "options": list(r.options) if r else None, "why_not": None if r else ignored_reason(l)}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    # skąd pochodzą etykiety w rekrutacji 4843 i 4562
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    async with AsyncSessionLocal() as db:
        for jid in (4843, 4562, 4954, 4967):
            j = (await db.execute(select(Job).where(Job.id == jid))).scalar_one()
            print(jid, "reviewed=", j.requirements_reviewed, "contract=", bool(j.matching_requirements),
                  "col=", j.must_skills, "explicit=", job_explicit_must_skills(j))


asyncio.run(main())
