"""
DynaMinds ATS — Seed v4 Addendum
Adds TalentPools and TalentPoolMemberships.
Safe to run after existing seed.
"""
import asyncio
import os
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.database import Base
from app.models.user import User
from app.models.candidate import Candidate
from app.models.talent_pool import TalentPool, TalentPoolMembership

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://dynaminds:dynaminds@localhost:5432/dynaminds"
)


async def seed_v4():
    engine = create_async_engine(DATABASE_URL, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Create new tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        # Check if already seeded v4
        result = await db.execute(select(TalentPool))
        existing = result.scalars().all()
        if existing:
            print(f"V4 already seeded — {len(existing)} talent pools exist.")
            await engine.dispose()
            return

        # Get admin user
        user_result = await db.execute(select(User).where(User.email == "artur@b2bnet.pl"))
        admin = user_result.scalar_one_or_none()
        if not admin:
            print("Admin user not found — run main seed first!")
            await engine.dispose()
            return

        # Get all candidates
        cand_result = await db.execute(select(Candidate))
        candidates = cand_result.scalars().all()

        print(f"Found {len(candidates)} candidates. Creating talent pools...")

        # Create 3 talent pools
        pools = [
            TalentPool(
                name="Senior Angular",
                description="Seniorzy Angular — gotowi do rozmów z Nordea i BNP. Min. 5 lat w Angular 10+.",
                criteria={"technology": "Angular", "seniority": "senior", "min_years": 5},
                created_by=admin.id,
            ),
            TalentPool(
                name="DevOps Engineers",
                description="Inżynierowie DevOps/Cloud — Kubernetes, Terraform, Azure/AWS. Dla projektów infrastrukturalnych.",
                criteria={"technology": "DevOps", "cloud": ["Azure", "AWS"], "skills": ["Kubernetes", "Terraform"]},
                created_by=admin.id,
            ),
            TalentPool(
                name="QA Automation",
                description="Specjaliści QA Automation — Selenium, Playwright, Cypress. Dla projektów wymagających automatyzacji testów.",
                criteria={"role": "QA", "automation": True, "skills": ["Selenium", "Playwright", "Cypress"]},
                created_by=admin.id,
            ),
        ]

        for p in pools:
            db.add(p)
        await db.flush()

        membership_count = 0
        for i, candidate in enumerate(candidates):
            category = (candidate.competence_category or "").lower()
            tags = [t.lower() for t in (candidate.tags or [])] if isinstance(candidate.tags, list) else []
            skills_names = []
            if isinstance(candidate.skills, list):
                for s in candidate.skills:
                    if isinstance(s, dict):
                        skills_names.append(s.get("name", "").lower())
                    elif isinstance(s, str):
                        skills_names.append(s.lower())

            all_text = " ".join([category] + tags + skills_names)

            assigned_pools = []
            if any(kw in all_text for kw in ["angular", "frontend", "react", "vue", "javascript", "typescript", "rxjs"]):
                assigned_pools.append(0)
            if any(kw in all_text for kw in ["devops", "kubernetes", "docker", "terraform", "cloud", "azure", "aws", "ci", "pipeline", "linux"]):
                assigned_pools.append(1)
            if any(kw in all_text for kw in ["qa", "testing", "selenium", "playwright", "cypress", "test", "quality", "automation"]):
                assigned_pools.append(2)

            if not assigned_pools:
                assigned_pools.append(i % 3)

            for pool_idx in assigned_pools[:2]:
                membership = TalentPoolMembership(
                    talent_pool_id=pools[pool_idx].id,
                    candidate_id=candidate.id,
                    added_by=admin.id,
                )
                db.add(membership)
                membership_count += 1

        await db.commit()
        print(f"✅ V4 seed completed!")
        print(f"   Created 3 talent pools with {membership_count} candidate memberships")
        for p in pools:
            print(f"   - {p.name}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_v4())
