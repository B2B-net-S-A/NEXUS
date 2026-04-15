"""
DynaMinds ATS — Seed v6: Rich Pipeline Data
Populates realistic pipeline entries across multiple jobs with candidates
spread across all stages (B2B.net flow).
"""
import asyncio
import os
import sys
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.database import Base
from app.models.user import User
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.activity import Activity

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://dynaminds:dynaminds@localhost:5433/dynaminds"
)

# Pipeline flow — candidates progress through these stages sequentially
PIPELINE_FLOW = [
    PipelineStage.new,
    PipelineStage.prep_call,
    PipelineStage.screening,
    PipelineStage.interview,
    PipelineStage.cv_sent,
    PipelineStage.client_interview,
    PipelineStage.acceptance,
    PipelineStage.negotiation,
    PipelineStage.onboarding,
    PipelineStage.hired,
]


def now_utc():
    return datetime.now(timezone.utc)


def random_past(max_days=30):
    return now_utc() - timedelta(days=random.randint(0, max_days), hours=random.randint(0, 23))


async def seed_v6():
    engine = create_async_engine(DATABASE_URL, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        # Get existing users
        users_result = await db.execute(select(User))
        users = users_result.scalars().all()
        if not users:
            print("No users found! Run main seed first.")
            await engine.dispose()
            return
        user_ids = [u.id for u in users]
        admin_id = user_ids[0]

        # Get existing candidates and jobs
        cands_result = await db.execute(select(Candidate).order_by(Candidate.id))
        candidates = cands_result.scalars().all()
        
        jobs_result = await db.execute(select(Job).order_by(Job.id))
        jobs = jobs_result.scalars().all()

        if len(candidates) < 10 or len(jobs) < 3:
            print(f"Need at least 10 candidates and 3 jobs. Have: {len(candidates)} candidates, {len(jobs)} jobs.")
            await engine.dispose()
            return

        print(f"Found {len(candidates)} candidates, {len(jobs)} jobs, {len(users)} users")

        # Clear existing pipeline data
        await db.execute(delete(CandidateStage))
        await db.commit()
        print("Cleared old pipeline data")

        # ── Distribution plan ──
        # For each job, assign candidates to various stages with realistic distribution:
        # Many at new/prep_call, fewer as pipeline progresses (funnel shape)
        # Some rejected at various points, some withdrawn
        
        STAGE_WEIGHTS = {
            PipelineStage.new: 6,
            PipelineStage.prep_call: 5,
            PipelineStage.screening: 4,
            PipelineStage.interview: 3,
            PipelineStage.cv_sent: 3,
            PipelineStage.client_interview: 2,
            PipelineStage.acceptance: 2,
            PipelineStage.negotiation: 1,
            PipelineStage.onboarding: 1,
            PipelineStage.hired: 1,
        }

        total_entries = 0
        cand_idx = 0

        for job in jobs[:10]:  # Process up to 10 jobs
            # Determine how many candidates for this job (5-15)
            remaining_count = len(candidates) - cand_idx
            if remaining_count < 3:
                break
            num_candidates = random.randint(3, min(15, remaining_count))

            job_candidates = candidates[cand_idx:cand_idx + num_candidates]
            cand_idx += num_candidates

            # Create weighted stage assignments
            for candidate in job_candidates:
                # Weighted random stage selection
                stage_choices = list(STAGE_WEIGHTS.keys())
                weights = list(STAGE_WEIGHTS.values())
                target_stage = random.choices(stage_choices, weights=weights, k=1)[0]
                
                # 15% chance of being rejected somewhere along the way
                is_rejected = random.random() < 0.15
                # 5% chance of withdrawal
                is_withdrawn = random.random() < 0.05

                # Create history: candidate progresses through stages up to target_stage
                target_idx = PIPELINE_FLOW.index(target_stage)
                base_time = random_past(max_days=30)

                for step_idx in range(target_idx + 1):
                    stage = PIPELINE_FLOW[step_idx]
                    moved_at = base_time + timedelta(days=step_idx * random.randint(1, 4), hours=random.randint(1, 12))
                    
                    entry = CandidateStage(
                        candidate_id=candidate.id,
                        job_id=job.id,
                        stage=stage,
                        moved_at=moved_at,
                        moved_by=random.choice(user_ids),
                        rating=random.choice([None, None, 3, 4, 5]) if step_idx >= 2 else None,
                        notes=_random_note(stage) if random.random() < 0.3 else None,
                    )
                    db.add(entry)
                    total_entries += 1

                # Add rejection/withdrawal if applicable
                if is_rejected and not is_withdrawn:
                    reject_time = base_time + timedelta(days=(target_idx + 1) * 2)
                    db.add(CandidateStage(
                        candidate_id=candidate.id,
                        job_id=job.id,
                        stage=PipelineStage.rejected,
                        moved_at=reject_time,
                        moved_by=random.choice(user_ids),
                        notes=random.choice([
                            "Nie spełnia wymagań technicznych",
                            "Zbyt wysokie oczekiwania finansowe",
                            "Brak doświadczenia w wymaganej technologii",
                            "Klient odrzucił kandydaturę",
                            "Nie przeszedł testu technicznego",
                        ]),
                    ))
                    total_entries += 1
                elif is_withdrawn:
                    withdraw_time = base_time + timedelta(days=(target_idx + 1) * 2)
                    db.add(CandidateStage(
                        candidate_id=candidate.id,
                        job_id=job.id,
                        stage=PipelineStage.withdrawn,
                        moved_at=withdraw_time,
                        moved_by=random.choice(user_ids),
                        notes=random.choice([
                            "Kandydat przyjął inną ofertę",
                            "Zrezygnował z procesu",
                            "Kontroferta od obecnego pracodawcy",
                        ]),
                    ))
                    total_entries += 1

            print(f"  Job '{job.title}': {num_candidates} candidates seeded")

        # If we have leftover candidates, spread them across first 3 jobs
        remaining = candidates[cand_idx:]
        if remaining:
            for i, candidate in enumerate(remaining[:30]):
                job = jobs[i % min(3, len(jobs))]
                stage = random.choices(PIPELINE_FLOW[:6], weights=[5, 4, 3, 2, 2, 1], k=1)[0]
                stage_idx = PIPELINE_FLOW.index(stage)
                base_time = random_past(max_days=20)
                
                for step_idx in range(stage_idx + 1):
                    s = PIPELINE_FLOW[step_idx]
                    db.add(CandidateStage(
                        candidate_id=candidate.id,
                        job_id=job.id,
                        stage=s,
                        moved_at=base_time + timedelta(days=step_idx * 2, hours=random.randint(1, 8)),
                        moved_by=random.choice(user_ids),
                    ))
                    total_entries += 1
            print(f"  Spread {min(30, len(remaining))} remaining candidates across jobs")

        await db.commit()
        print(f"\n✅ Seed v6 complete: {total_entries} pipeline entries created")

    await engine.dispose()


def _random_note(stage: PipelineStage) -> str:
    notes = {
        PipelineStage.new: [
            "CV wygląda obiecująco",
            "Profil dopasowany do wymagań",
            "LinkedIn weryfikacja OK",
            "Rekomendacja od kolegi z branży",
        ],
        PipelineStage.prep_call: [
            "Zmotywowany, szuka nowego wyzwania",
            "Aktualnie na wypowiedzeniu, dostępny za 2 tyg",
            "Oczekiwania: 25-30k PLN/mies",
            "Dobry kontakt telefoniczny, sprawdza się",
        ],
        PipelineStage.screening: [
            "Solid technical background",
            "5 lat doświadczenia w wymaganym stacku",
            "Komunikatywny, dobry angielski",
            "Potrzebuje relokacji — może być blocker",
        ],
        PipelineStage.interview: [
            "Bardzo dobry wywiad techniczny",
            "Dobrze prezentuje doświadczenie",
            "Wymaga dodatkowej weryfikacji SQL",
            "Świetny cultural fit",
        ],
        PipelineStage.cv_sent: [
            "CV wysłane do hiring managera",
            "Klient potwierdził odbiór CV",
            "Czekamy na feedback od klienta",
        ],
        PipelineStage.client_interview: [
            "Rozmowa zaplanowana na przyszły tydzień",
            "Klient zadowolony z profilu",
            "Techniczny przeszedł, czeka na finał z managerem",
        ],
        PipelineStage.acceptance: [
            "Klient akceptuje kandydata!",
            "Pozytywny feedback, przechodzą do oferty",
        ],
        PipelineStage.negotiation: [
            "Negocjujemy stawkę — kandydat chce +10%",
            "Umowa w trakcie przygotowania",
            "Czekamy na podpis ze strony klienta",
        ],
        PipelineStage.onboarding: [
            "Start: poniedziałek",
            "Dokumenty zebrane, czeka na laptop",
            "Dostępy przygotowane",
        ],
        PipelineStage.hired: [
            "Kontrakt aktywny ✅",
            "Pracuje od 2 tygodni, feedback pozytywny",
        ],
    }
    return random.choice(notes.get(stage, ["Brak notatek"]))


if __name__ == "__main__":
    asyncio.run(seed_v6())
