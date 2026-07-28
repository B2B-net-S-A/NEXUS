"""
Nexus ATS — Seed Script v3
Populates the database with realistic demo data for B2B.net S.A. IT recruitment agency.
Idempotent: checks if data already exists before inserting.
Includes v3: ClientKnowledge, ScreeningNotes, Contacts.
"""
import asyncio
import os

# Hasła kont demo NIE są literałami w repo. Dopóki nimi były, gitleaks musiał
# mieć `backend/seed.*\.py` na allowliście — a to wyłączało skaner dla CAŁEGO
# pliku, czyli dokładnie tam, gdzie mogło wylądować (i wylądowało w bliźniaczym
# skrypcie) działające hasło administratora.
# Seed nie dotyka produkcji: wyżej stoi bramka „Database already seeded".
_DEMO_PWD = os.environ.get("SEED_DEMO_PASSWORD", "dev-only-change-me")
import sys
from datetime import date, datetime, timedelta, timezone
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Add the app directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.security import hash_password
from app.models.user import User, UserRole
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client, ClientStatus
from app.models.job import Job, JobStatus, JobPriority, RemotePolicy, RecruitmentType
from app.models.call import Call, CallDirection, CallStatus
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.recruitment_priority import PriorityChannel
from app.models.recruitment_pipeline import PipelineStage
from app.services.recruitment_process_commands import transition_process
from app.models.activity import Activity
from app.models.user_activity import UserActivity, UserActionType
from app.models.email_template import EmailTemplate, EmailCategory
from app.models.job_posting import JobPosting, Portal, PostingStatus
from app.models.client_knowledge import ClientKnowledge, KnowledgeCategory
from app.models.screening_note import ScreeningNote, ScreeningType, MotivationType, CounterOfferRisk
from app.models.contact import Contact
from app.models.talent_pool import TalentPool, TalentPoolMembership
from app.core.database import Base

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://nexus:nexus@localhost:5432/nexus"
)

now = datetime.now(timezone.utc)


def days_ago(n: int) -> datetime:
    return now - timedelta(days=n)


def hours_ago(n: int) -> datetime:
    return now - timedelta(hours=n)


async def seed():
    engine = create_async_engine(DATABASE_URL, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Create tables if not exist (safety net when no alembic migrations)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        # Check if already seeded
        result = await db.execute(select(User).where(User.email == "artur@b2bnet.pl"))
        if result.scalar_one_or_none():
            print("Database already seeded — skipping.")
            await engine.dispose()
            return

        print("Seeding database with demo data (v2)...")

        # ── USERS ──────────────────────────────────────────────────────────────
        users_data = [
            {
                "email": "artur@b2bnet.pl",
                "name": "Artur Twardowski",
                "role": UserRole.admin,
                "password": _DEMO_PWD,
            },
            {
                "email": "olaf@b2bnet.pl",
                "name": "Olaf Moczydłowski",
                "role": UserRole.delivery_lead,
                "password": _DEMO_PWD,
            },
            {
                "email": "marta@b2bnet.pl",
                "name": "Marta Kowalska",
                "role": UserRole.recruiter,
                "password": _DEMO_PWD,
            },
            {
                "email": "tomasz@b2bnet.pl",
                "name": "Tomasz Wierzbicki",
                "role": UserRole.sourcer,
                "password": _DEMO_PWD,
            },
            {
                "email": "dominik@b2bnet.pl",
                "name": "Dominik Zwierzchowski",
                "role": UserRole.user,
                "password": _DEMO_PWD,
            },
        ]
        users = []
        for ud in users_data:
            u = User(
                email=ud["email"],
                password_hash=hash_password(ud["password"]),
                name=ud["name"],
                role=ud["role"],
                is_active=True,
            )
            db.add(u)
            users.append(u)
        await db.flush()
        print(f"  Created {len(users)} users")

        admin_user = users[0]
        recruiter1 = users[1]  # Olaf - DL
        recruiter2 = users[2]  # Marta - Recruiter
        recruiter3 = users[3]  # Tomasz - Sourcer

        # ── CLIENTS ────────────────────────────────────────────────────────────
        clients_data = [
            {
                "name": "Nordea Bank AB",
                "industry": "Banking & Finance",
                "website": "https://nordea.com",
                "address": "ul. Bałtycka 1, 00-001 Warszawa",                "status": ClientStatus.active,
                "nda_signed": True,
                "contract_type": "ramowa",
            },
            {
                "name": "BNP Paribas Bank Polska",
                "industry": "Banking & Finance",
                "website": "https://bnpparibas.pl",
                "address": "ul. Kasprzaka 2, 01-211 Warszawa",                "status": ClientStatus.active,
                "nda_signed": True,
                "contract_type": "ramowa",
            },
            {
                "name": "Bank Pekao SA",
                "industry": "Banking & Finance",
                "website": "https://pekao.com.pl",
                "address": "ul. Żwirki i Wigury 31, 02-091 Warszawa",                "status": ClientStatus.active,
                "nda_signed": True,
                "contract_type": "ramowa",
            },
            {
                "name": "Ferro S.A.",
                "industry": "Manufacturing & Engineering",
                "website": "https://ferro.pl",
                "address": "ul. Jutrzenki 94, 02-230 Warszawa",                "status": ClientStatus.active,
                "nda_signed": True,
                "contract_type": "jednorazowa",
            },
            {
                "name": "Cognism Ltd",
                "industry": "SaaS / Sales Intelligence",
                "website": "https://cognism.com",
                "address": "ul. Puławska 182, 02-670 Warszawa",                "status": ClientStatus.active,
                "nda_signed": True,
                "contract_type": "ramowa",
            },
            {
                "name": "Asseco Poland S.A.",
                "industry": "IT / Software",
                "website": "https://asseco.pl",
                "address": "ul. Olchowa 14, 35-322 Rzeszów",                "status": ClientStatus.active,
                "nda_signed": True,
                "contract_type": "ramowa",
            },
            {
                "name": "Comarch S.A.",
                "industry": "IT / Software",
                "website": "https://comarch.com",
                "address": "Al. Jana Pawła II 39A, 31-864 Kraków",                "status": ClientStatus.active,
                "nda_signed": False,
                "contract_type": "jednorazowa",
            },
            {
                "name": "PKO Bank Polski",
                "industry": "Banking & Finance",
                "website": "https://pkobp.pl",
                "address": "ul. Puławska 15, 02-515 Warszawa",                "status": ClientStatus.prospect,
                "nda_signed": False,
                "contract_type": None,
            },
            {
                "name": "Allegro",
                "industry": "E-commerce",
                "website": "https://allegro.pl",
                "address": "ul. Grunwaldzka 182, 60-166 Poznań",                "status": ClientStatus.prospect,
                "nda_signed": False,
                "contract_type": None,
            },
            {
                "name": "ING Bank Śląski",
                "industry": "Banking & Finance",
                "website": "https://ing.pl",
                "address": "ul. Sokolska 34, 40-086 Katowice",                "status": ClientStatus.active,
                "nda_signed": True,
                "contract_type": "ramowa",
            },
        ]
        clients = []
        for cd in clients_data:
            c = Client(**cd)
            db.add(c)
            clients.append(c)
        await db.flush()
        print(f"  Created {len(clients)} clients")

        # ── JOBS ───────────────────────────────────────────────────────────────
        jobs_data = [
            {
                "title": "Senior Angular Developer",
                "description": "Szukamy doświadczonego Angular Developera do zespołu bankowości cyfrowej Nordea.",
                "requirements": "Angular 15+, TypeScript, RxJS, NgRx, 4+ lata doświadczenia",
                "location": "Warszawa / Remote",
                "salary_min": 18000,
                "salary_max": 25000,
                "remote_policy": RemotePolicy.hybrid,
                "status": JobStatus.published,
                "priority": JobPriority.urgent,
                "recruitment_type": RecruitmentType.body_leasing,
                "deadline": date.today() + timedelta(days=21),
                "client_id": clients[0].id,
                "recruiter_id": recruiter1.id,
            },
            {
                "title": "Java Backend Developer",
                "description": "Pozycja w departamencie systemów transakcyjnych BNP Paribas.",
                "requirements": "Java 17+, Spring Boot 3, Kafka, PostgreSQL, 3+ lata",
                "location": "Warszawa",
                "salary_min": 16000,
                "salary_max": 22000,
                "remote_policy": RemotePolicy.hybrid,
                "status": JobStatus.published,
                "priority": JobPriority.high,
                "recruitment_type": RecruitmentType.body_leasing,
                "deadline": date.today() + timedelta(days=28),
                "client_id": clients[1].id,
                "recruiter_id": recruiter1.id,
            },
            {
                "title": "DevOps / Cloud Engineer",
                "description": "Budowa i utrzymanie infrastruktury chmurowej Azure/AWS dla systemów bankowych.",
                "requirements": "Kubernetes, Terraform, Azure/AWS, CI/CD, 3+ lata",
                "location": "Warszawa / Zdalnie",
                "salary_min": 18000,
                "salary_max": 28000,
                "remote_policy": RemotePolicy.remote,
                "status": JobStatus.published,
                "priority": JobPriority.high,
                "recruitment_type": RecruitmentType.body_leasing,
                "deadline": date.today() + timedelta(days=35),
                "client_id": clients[2].id,
                "recruiter_id": recruiter2.id,
            },
            {
                "title": "QA Automation Engineer",
                "description": "Automatyzacja testów dla systemów ERP w Ferro S.A.",
                "requirements": "Selenium, Cypress, Java lub Python, TestNG/JUnit, 2+ lata",
                "location": "Kraków / Zdalnie",
                "salary_min": 12000,
                "salary_max": 18000,
                "remote_policy": RemotePolicy.hybrid,
                "status": JobStatus.published,
                "priority": JobPriority.medium,
                "recruitment_type": RecruitmentType.body_leasing,
                "deadline": date.today() + timedelta(days=42),
                "client_id": clients[3].id,
                "recruiter_id": recruiter2.id,
            },
            {
                "title": "Python Data Engineer",
                "description": "Budowa pipeline'ów danych dla platformy Sales Intelligence Cognism.",
                "requirements": "Python, Airflow/Prefect, dbt, Spark, BigQuery/Snowflake, 3+ lata",
                "location": "Warszawa",
                "salary_min": 17000,
                "salary_max": 24000,
                "remote_policy": RemotePolicy.hybrid,
                "status": JobStatus.published,
                "priority": JobPriority.high,
                "recruitment_type": RecruitmentType.body_leasing,
                "deadline": date.today() + timedelta(days=30),
                "client_id": clients[4].id,
                "recruiter_id": recruiter3.id,
            },
            {
                "title": "React Frontend Developer",
                "description": "Tworzenie interfejsów użytkownika dla systemów backoffice Asseco.",
                "requirements": "React 18+, TypeScript, Redux Toolkit, REST/GraphQL, 3+ lata",
                "location": "Rzeszów / Remote",
                "salary_min": 14000,
                "salary_max": 20000,
                "remote_policy": RemotePolicy.hybrid,
                "status": JobStatus.published,
                "priority": JobPriority.medium,
                "recruitment_type": RecruitmentType.body_leasing,
                "deadline": date.today() + timedelta(days=45),
                "client_id": clients[5].id,
                "recruiter_id": recruiter3.id,
            },
            {
                "title": "Scrum Master / Agile Coach",
                "description": "Prowadzenie procesów agile w dużych projektach IT dla Comarch.",
                "requirements": "PSM II lub CSM, 4+ lata w roli SM, znajomość SAFe",
                "location": "Kraków",
                "salary_min": 14000,
                "salary_max": 20000,
                "remote_policy": RemotePolicy.hybrid,
                "status": JobStatus.published,
                "priority": JobPriority.medium,
                "recruitment_type": RecruitmentType.sales_project,
                "deadline": date.today() + timedelta(days=60),
                "client_id": clients[6].id,
                "recruiter_id": recruiter1.id,
            },
            {
                "title": "iOS Developer (Swift)",
                "description": "Rozwój aplikacji mobilnej ING Mobile dla segmentu retail.",
                "requirements": "Swift 5+, SwiftUI, UIKit, CoreData, 3+ lata iOS",
                "location": "Katowice / Remote",
                "salary_min": 16000,
                "salary_max": 22000,
                "remote_policy": RemotePolicy.hybrid,
                "status": JobStatus.published,
                "priority": JobPriority.high,
                "recruitment_type": RecruitmentType.sales_project,
                "deadline": date.today() + timedelta(days=25),
                "client_id": clients[9].id,
                "recruiter_id": recruiter2.id,
            },
            {
                "title": "Tech Lead / Architect",
                "description": "Rola architekta technicznego dla nowego produktu cyfrowego Pekao SA.",
                "requirements": "Java/Kotlin lub .NET, microservices, event-driven arch, 6+ lat, TL",
                "location": "Warszawa",
                "salary_min": 25000,
                "salary_max": 35000,
                "remote_policy": RemotePolicy.onsite,
                "status": JobStatus.published,
                "priority": JobPriority.urgent,
                "recruitment_type": RecruitmentType.tender,
                "deadline": date.today() + timedelta(days=14),
                "client_id": clients[2].id,
                "recruiter_id": recruiter1.id,
            },
            {
                "title": "Fullstack Node.js Developer",
                "description": "Budowa platformy wewnętrznej automatyzacji procesów B2B.",
                "requirements": "Node.js, NestJS, React, PostgreSQL, Docker, 3+ lata",
                "location": "Warszawa / Remote",
                "salary_min": 15000,
                "salary_max": 21000,
                "remote_policy": RemotePolicy.remote,
                "status": JobStatus.draft,
                "priority": JobPriority.low,
                "recruitment_type": RecruitmentType.tender,
                "deadline": date.today() + timedelta(days=60),
                "client_id": clients[0].id,
                "recruiter_id": recruiter3.id,
            },
        ]
        jobs = []
        for jd in jobs_data:
            j = Job(**jd, created_by=admin_user.id)
            db.add(j)
            jobs.append(j)
        await db.flush()
        print(f"  Created {len(jobs)} jobs")

        # ── CANDIDATES ─────────────────────────────────────────────────────────
        candidates_data = [
            {
                "name": "Piotr", "lastname": "Kowalski",
                "email": "p.kowalski@gmail.com", "phone": "+48 601 234 567",
                "location": "Warszawa", "linkedin": "linkedin.com/in/piotrkowalski",
                "salary_expectation": 22000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=14),
                "source": "linkedin",
                "competence_category": "Frontend",
                "ai_summary": "Doświadczony Senior Angular Developer z 6-letnim stażem w Accenture. Ekspert w Angular 15+, TypeScript i RxJS. Pracował przy projektach bankowości cyfrowej. Posiada bardzo dobre umiejętności komunikacyjne i doświadczenie w pracy zdalnej. Gotowy do rozpoczęcia w ciągu 2 tygodni.",
                "notice_period": 14,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Angular", "level": "expert", "years": 6},
                    {"name": "TypeScript", "level": "expert", "years": 6},
                    {"name": "RxJS", "level": "senior", "years": 5},
                    {"name": "NgRx", "level": "senior", "years": 4},
                ],
                "tags": ["senior", "angular", "frontend", "b2b"],
                "experience": [{"company": "Accenture", "role": "Senior Angular Dev", "start": "2019-01", "end": "2024-12"}],
            },
            {
                "name": "Agnieszka", "lastname": "Nowak",
                "email": "a.nowak.dev@gmail.com", "phone": "+48 602 345 678",
                "location": "Kraków", "linkedin": "linkedin.com/in/agnieszka-nowak-dev",
                "salary_expectation": 19000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=7),
                "source": "pracuj",
                "competence_category": "Backend",
                "ai_summary": "Java Backend Lead z 8-letnim doświadczeniem, specjalizacja w systemach bankowych i finansowych. W ABB prowadziła zespół 5 programistów Java. Doskonała znajomość Spring Boot 3, Kafka i PostgreSQL. Kandydatka aktywnie szukająca nowych wyzwań w sektorze fintech.",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Java", "level": "expert", "years": 8},
                    {"name": "Spring Boot", "level": "expert", "years": 7},
                    {"name": "Kafka", "level": "senior", "years": 4},
                    {"name": "PostgreSQL", "level": "senior", "years": 6},
                ],
                "tags": ["senior", "java", "backend", "fintech", "b2b"],
                "experience": [{"company": "ABB", "role": "Java Backend Lead", "start": "2016-03", "end": "2024-06"}],
            },
            {
                "name": "Michał", "lastname": "Wiśniewski",
                "email": "m.wisniewski.cloud@gmail.com", "phone": "+48 603 456 789",
                "location": "Warszawa", "linkedin": "linkedin.com/in/michal-wisniewski-cloud",
                "salary_expectation": 26000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=30),
                "source": "linkedin",
                "competence_category": "DevOps/Cloud",
                "ai_summary": "Cloud Engineer z ekspercką wiedzą w Kubernetes, Terraform i Azure. 5 lat w T-Mobile przy infrastrukturze krytycznej dla milionów użytkowników. Certyfikat Azure Solutions Architect Expert. Zainteresowany dużymi projektami infrastrukturalnymi w sektorze bankowym.",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Kubernetes", "level": "expert", "years": 5},
                    {"name": "Terraform", "level": "expert", "years": 5},
                    {"name": "Azure", "level": "senior", "years": 5},
                    {"name": "AWS", "level": "senior", "years": 4},
                    {"name": "CI/CD", "level": "expert", "years": 6},
                ],
                "tags": ["senior", "devops", "cloud", "azure", "kubernetes", "b2b"],
                "experience": [{"company": "T-Mobile", "role": "Cloud Engineer", "start": "2019-06", "end": "2024-11"}],
            },
            {
                "name": "Katarzyna", "lastname": "Zielińska",
                "email": "k.zielinska.qa@gmail.com", "phone": "+48 604 567 890",
                "location": "Wrocław",
                "salary_expectation": 14000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=21),
                "source": "jjit",
                "competence_category": "QA",
                "ai_summary": "QA Automation Engineer z 5-letnim doświadczeniem w testowaniu automatycznym. Specjalizacja w Selenium i Cypress dla systemów ERP. Capgemini — praca przy klientach z sektora produkcyjnego i finansowego. Biegła w Pythonie i Java na poziomie testów.",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Selenium", "level": "expert", "years": 5},
                    {"name": "Cypress", "level": "senior", "years": 3},
                    {"name": "Python", "level": "senior", "years": 5},
                    {"name": "TestNG", "level": "expert", "years": 5},
                ],
                "tags": ["qa", "automation", "selenium", "cypress"],
                "experience": [{"company": "Capgemini", "role": "QA Automation Engineer", "start": "2019-09", "end": "2024-08"}],
            },
            {
                "name": "Tomasz", "lastname": "Dąbrowski",
                "email": "t.dabrowski.python@gmail.com", "phone": "+48 605 678 901",
                "location": "Warszawa",
                "salary_expectation": 21000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=7),
                "source": "linkedin",
                "competence_category": "Data Engineering",
                "ai_summary": "Data Engineer z 7-letnim doświadczeniem w Pythonie i ekosystemie danych. W Allegro budował pipeline'y przetwarzające miliardy zdarzeń dziennie. Ekspert Airflow, dbt i BigQuery. Zainteresowany projektami w obszarze Sales Intelligence i ML pipelines.",
                "notice_period": 14,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Python", "level": "expert", "years": 7},
                    {"name": "Apache Airflow", "level": "expert", "years": 4},
                    {"name": "dbt", "level": "senior", "years": 3},
                    {"name": "Spark", "level": "senior", "years": 4},
                    {"name": "BigQuery", "level": "senior", "years": 3},
                ],
                "tags": ["data-engineering", "python", "airflow", "spark"],
                "experience": [{"company": "Allegro", "role": "Data Engineer", "start": "2017-04", "end": "2024-10"}],
            },
            {
                "name": "Joanna", "lastname": "Lewandowska",
                "email": "j.lewandowska.react@gmail.com", "phone": "+48 606 789 012",
                "location": "Gdańsk",
                "salary_expectation": 17000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=14),
                "source": "manual",
                "competence_category": "Frontend",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "React", "level": "expert", "years": 5},
                    {"name": "TypeScript", "level": "expert", "years": 5},
                    {"name": "Redux Toolkit", "level": "senior", "years": 4},
                    {"name": "GraphQL", "level": "senior", "years": 3},
                ],
                "tags": ["frontend", "react", "typescript", "graphql"],
                "experience": [{"company": "Softhouse Polska", "role": "Frontend Developer", "start": "2019-02", "end": "2024-07"}],
            },
            {
                "name": "Rafał", "lastname": "Mazur",
                "email": "r.mazur.java@gmail.com", "phone": "+48 607 890 123",
                "location": "Poznań",
                "salary_expectation": 20000, "salary_currency": "PLN",
                "availability_date": date.today(),
                "source": "linkedin",
                "competence_category": "Backend",
                "notice_period": 0,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Java", "level": "expert", "years": 9},
                    {"name": "Spring Cloud", "level": "expert", "years": 6},
                    {"name": "Microservices", "level": "expert", "years": 7},
                    {"name": "Docker", "level": "expert", "years": 6},
                ],
                "tags": ["senior", "java", "microservices", "architecture", "b2b"],
                "experience": [{"company": "Fujitsu", "role": "Java Architect", "start": "2015-01", "end": "2024-12"}],
            },
            {
                "name": "Magdalena", "lastname": "Wójcik",
                "email": "m.wojcik.ios@gmail.com", "phone": "+48 608 901 234",
                "location": "Katowice",
                "salary_expectation": 19000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=21),
                "source": "linkedin",
                "competence_category": "Mobile",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Swift", "level": "expert", "years": 6},
                    {"name": "SwiftUI", "level": "expert", "years": 4},
                    {"name": "UIKit", "level": "expert", "years": 6},
                    {"name": "CoreData", "level": "senior", "years": 5},
                ],
                "tags": ["ios", "swift", "mobile", "swiftui"],
                "experience": [{"company": "Polidea", "role": "iOS Developer", "start": "2018-06", "end": "2024-11"}],
            },
            {
                "name": "Paweł", "lastname": "Kaczmarek",
                "email": "p.kaczmarek.tl@gmail.com", "phone": "+48 609 012 345",
                "location": "Warszawa",
                "salary_expectation": 32000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=30),
                "source": "referral",
                "competence_category": "Architecture",
                "ai_summary": "Tech Lead i Architekt z 12-letnim doświadczeniem Java Enterprise. W Sii prowadził 15-osobowy zespół przy projekcie dla PKO BP. Ekspert w architekturze mikroserwisowej, Event Sourcing i systemach wysokiej dostępności. Poszukuje roli architekta w sektorze bankowym lub fintech.",
                "notice_period": 60,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Java", "level": "expert", "years": 12},
                    {"name": "Architecture", "level": "expert", "years": 7},
                    {"name": "Kafka", "level": "expert", "years": 6},
                    {"name": "Kubernetes", "level": "senior", "years": 5},
                ],
                "tags": ["tech-lead", "architect", "java", "senior", "b2b"],
                "experience": [{"company": "Sii Poland", "role": "Tech Lead / Architect", "start": "2012-03", "end": "2024-12"}],
            },
            {
                "name": "Anna", "lastname": "Szymańska",
                "email": "a.szymanska.scrum@gmail.com", "phone": "+48 610 123 456",
                "location": "Kraków",
                "salary_expectation": 18000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=14),
                "source": "linkedin",
                "competence_category": "Agile/PM",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Scrum", "level": "expert", "years": 7},
                    {"name": "SAFe", "level": "expert", "years": 5},
                    {"name": "Jira", "level": "expert", "years": 8},
                    {"name": "Confluence", "level": "expert", "years": 8},
                ],
                "tags": ["scrum-master", "agile", "safe"],
                "experience": [{"company": "Atos", "role": "Scrum Master / Agile Coach", "start": "2017-05", "end": "2024-10"}],
            },
            {
                "name": "Bartosz", "lastname": "Jankowski",
                "email": "b.jankowski.node@gmail.com", "phone": "+48 611 234 567",
                "location": "Warszawa",
                "salary_expectation": 18000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=7),
                "source": "jjit",
                "competence_category": "Fullstack",
                "notice_period": 14,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Node.js", "level": "expert", "years": 5},
                    {"name": "NestJS", "level": "expert", "years": 4},
                    {"name": "React", "level": "senior", "years": 4},
                    {"name": "PostgreSQL", "level": "senior", "years": 5},
                ],
                "tags": ["fullstack", "nodejs", "nestjs", "react"],
                "experience": [{"company": "Boldare", "role": "Fullstack Developer", "start": "2019-01", "end": "2024-12"}],
            },
            {
                "name": "Kamila", "lastname": "Kowalczyk",
                "email": "k.kowalczyk.angular@gmail.com", "phone": "+48 612 345 678",
                "location": "Warszawa",
                "salary_expectation": 16000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=14),
                "source": "pracuj",
                "competence_category": "Frontend",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Angular", "level": "senior", "years": 4},
                    {"name": "TypeScript", "level": "senior", "years": 4},
                    {"name": "RxJS", "level": "mid", "years": 3},
                ],
                "tags": ["angular", "frontend"],
                "experience": [{"company": "Objectivity", "role": "Angular Developer", "start": "2020-03", "end": "2024-12"}],
            },
            {
                "name": "Sebastian", "lastname": "Wiśniewski",
                "email": "s.wisniewski.devops@gmail.com", "phone": "+48 613 456 789",
                "location": "Gdańsk",
                "salary_expectation": 23000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=21),
                "source": "linkedin",
                "competence_category": "DevOps/Cloud",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Kubernetes", "level": "senior", "years": 4},
                    {"name": "AWS", "level": "expert", "years": 5},
                    {"name": "Terraform", "level": "senior", "years": 4},
                    {"name": "GitLab CI", "level": "expert", "years": 5},
                ],
                "tags": ["devops", "aws", "cloud"],
                "experience": [{"company": "Intel", "role": "Senior DevOps Engineer", "start": "2019-07", "end": "2024-11"}],
            },
            {
                "name": "Natalia", "lastname": "Pawlak",
                "email": "n.pawlak.qa@gmail.com", "phone": "+48 614 567 890",
                "location": "Wrocław",
                "salary_expectation": 13000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=7),
                "source": "linkedin",
                "competence_category": "QA",
                "notice_period": 14,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Selenium", "level": "senior", "years": 4},
                    {"name": "Postman", "level": "expert", "years": 5},
                    {"name": "Java", "level": "mid", "years": 3},
                    {"name": "REST API Testing", "level": "senior", "years": 5},
                ],
                "tags": ["qa", "automation", "api-testing"],
                "experience": [{"company": "Infosys", "role": "QA Engineer", "start": "2020-02", "end": "2024-12"}],
            },
            {
                "name": "Łukasz", "lastname": "Zając",
                "email": "l.zajac.python@gmail.com", "phone": "+48 615 678 901",
                "location": "Warszawa",
                "salary_expectation": 20000, "salary_currency": "PLN",
                "availability_date": date.today(),
                "source": "linkedin",
                "competence_category": "Backend",
                "notice_period": 0,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Python", "level": "expert", "years": 6},
                    {"name": "Django", "level": "expert", "years": 5},
                    {"name": "FastAPI", "level": "expert", "years": 4},
                    {"name": "PostgreSQL", "level": "senior", "years": 6},
                ],
                "tags": ["python", "backend", "django", "fastapi"],
                "experience": [{"company": "Opera Software", "role": "Python Developer", "start": "2018-09", "end": "2024-12"}],
            },
            {
                "name": "Monika", "lastname": "Grabowska",
                "email": "m.grabowska.react@gmail.com", "phone": "+48 616 789 012",
                "location": "Wrocław",
                "salary_expectation": 15000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=14),
                "source": "manual",
                "competence_category": "Frontend",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "React", "level": "senior", "years": 4},
                    {"name": "TypeScript", "level": "senior", "years": 4},
                    {"name": "GraphQL", "level": "mid", "years": 2},
                ],
                "tags": ["frontend", "react"],
                "experience": [{"company": "Netguru", "role": "Frontend Developer", "start": "2020-05", "end": "2024-12"}],
            },
            {
                "name": "Krzysztof", "lastname": "Lewicki",
                "email": "k.lewicki.java@gmail.com", "phone": "+48 617 890 123",
                "location": "Poznań",
                "salary_expectation": 17000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=21),
                "source": "referral",
                "competence_category": "Backend",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Java", "level": "senior", "years": 5},
                    {"name": "Spring Boot", "level": "senior", "years": 4},
                    {"name": "MySQL", "level": "senior", "years": 5},
                    {"name": "Docker", "level": "mid", "years": 3},
                ],
                "tags": ["java", "backend"],
                "experience": [{"company": "Hycom", "role": "Java Developer", "start": "2019-06", "end": "2024-11"}],
            },
            {
                "name": "Ewa", "lastname": "Malinowska",
                "email": "e.malinowska.ios@gmail.com", "phone": "+48 618 901 234",
                "location": "Warszawa",
                "salary_expectation": 18000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=30),
                "source": "linkedin",
                "competence_category": "Mobile",
                "notice_period": 30,
                "status": CandidateStatus.passive,
                "skills": [
                    {"name": "Swift", "level": "senior", "years": 4},
                    {"name": "SwiftUI", "level": "senior", "years": 3},
                    {"name": "React Native", "level": "mid", "years": 2},
                ],
                "tags": ["ios", "mobile", "swift"],
                "experience": [{"company": "Miquido", "role": "iOS Developer", "start": "2020-08", "end": "2024-12"}],
            },
            {
                "name": "Arkadiusz", "lastname": "Czarnecki",
                "email": "a.czarnecki.devops@gmail.com", "phone": "+48 619 012 345",
                "location": "Kraków",
                "salary_expectation": 22000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=14),
                "source": "linkedin",
                "competence_category": "DevOps/Cloud",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Kubernetes", "level": "expert", "years": 5},
                    {"name": "GCP", "level": "senior", "years": 4},
                    {"name": "Terraform", "level": "expert", "years": 5},
                    {"name": "Python", "level": "mid", "years": 3},
                ],
                "tags": ["devops", "gcp", "cloud"],
                "experience": [{"company": "Google Cloud", "role": "DevOps Lead", "start": "2019-03", "end": "2024-09"}],
            },
            {
                "name": "Dominika", "lastname": "Stępień",
                "email": "d.stepien.scrum@gmail.com", "phone": "+48 620 123 456",
                "location": "Warszawa",
                "salary_expectation": 16000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=7),
                "source": "linkedin",
                "competence_category": "Agile/PM",
                "notice_period": 14,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Scrum", "level": "senior", "years": 5},
                    {"name": "Jira", "level": "expert", "years": 6},
                    {"name": "Confluence", "level": "expert", "years": 6},
                ],
                "tags": ["scrum-master", "agile"],
                "experience": [{"company": "Ericsson", "role": "Scrum Master", "start": "2019-01", "end": "2024-12"}],
            },
            {
                "name": "Jakub", "lastname": "Ostrowski",
                "email": "j.ostrowski.fullstack@gmail.com", "phone": "+48 621 234 567",
                "location": "Gdańsk",
                "salary_expectation": 19000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=14),
                "source": "jjit",
                "competence_category": "Fullstack",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Node.js", "level": "expert", "years": 6},
                    {"name": "Vue.js", "level": "senior", "years": 4},
                    {"name": "TypeScript", "level": "expert", "years": 5},
                    {"name": "MongoDB", "level": "senior", "years": 4},
                ],
                "tags": ["fullstack", "nodejs", "vue"],
                "experience": [{"company": "Snowdog", "role": "Fullstack Engineer", "start": "2018-05", "end": "2024-12"}],
            },
            {
                "name": "Marta", "lastname": "Nowicka",
                "email": "m.nowicka.data@gmail.com", "phone": "+48 622 345 678",
                "location": "Warszawa",
                "salary_expectation": 21000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=21),
                "source": "linkedin",
                "competence_category": "Data Engineering",
                "ai_summary": "Data Engineer z 6-letnim doświadczeniem w przetwarzaniu danych na dużą skalę. W ING Tech budowała pipeline'y Spark obsługujące dane transakcyjne. Doświadczenie z Databricks i Snowflake w środowiskach produkcyjnych. Szuka projektu z nowoczesnym stackiem danych.",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Python", "level": "expert", "years": 6},
                    {"name": "Spark", "level": "senior", "years": 4},
                    {"name": "Databricks", "level": "senior", "years": 3},
                    {"name": "Snowflake", "level": "senior", "years": 3},
                ],
                "tags": ["data-engineering", "python", "spark", "databricks"],
                "experience": [{"company": "ING Tech", "role": "Data Engineer", "start": "2018-09", "end": "2024-11"}],
            },
            {
                "name": "Grzegorz", "lastname": "Woźniak",
                "email": "g.wozniak.be@gmail.com", "phone": "+48 623 456 789",
                "location": "Łódź",
                "salary_expectation": 14000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=7),
                "source": "pracuj",
                "competence_category": "Backend",
                "notice_period": 14,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "PHP", "level": "senior", "years": 6},
                    {"name": "Laravel", "level": "expert", "years": 5},
                    {"name": "MySQL", "level": "senior", "years": 6},
                    {"name": "Vue.js", "level": "mid", "years": 2},
                ],
                "tags": ["php", "laravel", "backend"],
                "experience": [{"company": "FutureSimple", "role": "Backend Developer", "start": "2018-06", "end": "2024-12"}],
            },
            {
                "name": "Sylwia", "lastname": "Kamińska",
                "email": "s.kaminska.qa@gmail.com", "phone": "+48 624 567 890",
                "location": "Wrocław",
                "salary_expectation": 12000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=14),
                "source": "linkedin",
                "competence_category": "QA",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Manual Testing", "level": "expert", "years": 5},
                    {"name": "Selenium", "level": "mid", "years": 2},
                    {"name": "Jira", "level": "expert", "years": 5},
                    {"name": "SQL", "level": "mid", "years": 3},
                ],
                "tags": ["qa", "manual-testing"],
                "experience": [{"company": "Tieto", "role": "QA Engineer", "start": "2019-07", "end": "2024-12"}],
            },
            {
                "name": "Marcin", "lastname": "Kwiatkowski",
                "email": "m.kwiatkowski.angular@gmail.com", "phone": "+48 625 678 901",
                "location": "Kraków",
                "salary_expectation": 17000, "salary_currency": "PLN",
                "availability_date": date.today(),
                "source": "manual",
                "competence_category": "Frontend",
                "notice_period": 0,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Angular", "level": "senior", "years": 5},
                    {"name": "TypeScript", "level": "senior", "years": 5},
                    {"name": "SCSS", "level": "senior", "years": 5},
                    {"name": "Jest", "level": "mid", "years": 3},
                ],
                "tags": ["angular", "frontend"],
                "experience": [{"company": "Motorola Solutions", "role": "Angular Developer", "start": "2019-09", "end": "2024-12"}],
            },
            {
                "name": "Aleksandra", "lastname": "Michalska",
                "email": "a.michalska.cloud@gmail.com", "phone": "+48 626 789 012",
                "location": "Warszawa",
                "salary_expectation": 27000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=30),
                "source": "referral",
                "competence_category": "DevOps/Cloud",
                "ai_summary": "Cloud Architect z Microsoft z 6-letnim doświadczeniem w Azure. Projektowała rozwiązania multi-cloud dla klientów enterprise. Certyfikaty: Azure Solutions Architect Expert, CKA. Aktualnie pasywnie poszukuje nowych możliwości — ceni projekty z realnym wpływem na architekturę.",
                "notice_period": 60,
                "status": CandidateStatus.passive,
                "skills": [
                    {"name": "Azure", "level": "expert", "years": 6},
                    {"name": "Kubernetes", "level": "expert", "years": 5},
                    {"name": "Python", "level": "senior", "years": 5},
                    {"name": "Terraform", "level": "expert", "years": 5},
                ],
                "tags": ["cloud-architect", "azure", "devops", "senior"],
                "experience": [{"company": "Microsoft", "role": "Cloud Architect", "start": "2018-06", "end": "2024-12"}],
            },
            {
                "name": "Radosław", "lastname": "Adamski",
                "email": "r.adamski.java@gmail.com", "phone": "+48 627 890 123",
                "location": "Poznań",
                "salary_expectation": 16000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=14),
                "source": "jjit",
                "competence_category": "Backend",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Java", "level": "mid", "years": 3},
                    {"name": "Spring Boot", "level": "mid", "years": 3},
                    {"name": "Hibernate", "level": "mid", "years": 3},
                    {"name": "PostgreSQL", "level": "mid", "years": 3},
                ],
                "tags": ["java", "backend", "mid"],
                "experience": [{"company": "Nordcloud", "role": "Java Developer", "start": "2021-05", "end": "2024-12"}],
            },
            {
                "name": "Weronika", "lastname": "Borkowska",
                "email": "w.borkowska.react@gmail.com", "phone": "+48 628 901 234",
                "location": "Gdańsk",
                "salary_expectation": 14000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=7),
                "source": "linkedin",
                "competence_category": "Frontend",
                "notice_period": 14,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "React", "level": "mid", "years": 3},
                    {"name": "JavaScript", "level": "senior", "years": 4},
                    {"name": "CSS", "level": "senior", "years": 4},
                ],
                "tags": ["frontend", "react", "mid"],
                "experience": [{"company": "Startup Hub", "role": "Frontend Developer", "start": "2021-02", "end": "2024-12"}],
            },
            {
                "name": "Marek", "lastname": "Olszewski",
                "email": "m.olszewski.arch@gmail.com", "phone": "+48 629 012 345",
                "location": "Warszawa",
                "salary_expectation": 33000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=60),
                "source": "referral",
                "competence_category": "Architecture",
                "ai_summary": "Enterprise Architect z 14-letnim doświadczeniem Java i DDD. W Credit Suisse odpowiadał za architekturę systemów transakcyjnych obsługujących miliardy transakcji. Ekspert Event Sourcing, CQRS i Kafka. Dostępny za 2 miesiące — otwierający się na projekty enterprise.",
                "notice_period": 60,
                "status": CandidateStatus.passive,
                "skills": [
                    {"name": "Java", "level": "expert", "years": 14},
                    {"name": "Microservices", "level": "expert", "years": 10},
                    {"name": "Event Sourcing", "level": "expert", "years": 8},
                    {"name": "Kafka", "level": "expert", "years": 8},
                ],
                "tags": ["architect", "senior", "java", "ddd", "event-sourcing"],
                "experience": [{"company": "Credit Suisse", "role": "Enterprise Architect", "start": "2010-03", "end": "2024-09"}],
            },
            {
                "name": "Julia", "lastname": "Włodarczyk",
                "email": "j.wlodarczyk.pm@gmail.com", "phone": "+48 630 123 456",
                "location": "Warszawa",
                "salary_expectation": 18000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=14),
                "source": "linkedin",
                "competence_category": "Agile/PM",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": [
                    {"name": "Project Management", "level": "expert", "years": 8},
                    {"name": "Scrum", "level": "expert", "years": 7},
                    {"name": "PRINCE2", "level": "senior", "years": 5},
                    {"name": "Jira", "level": "expert", "years": 8},
                ],
                "tags": ["project-manager", "scrum", "agile"],
                "experience": [{"company": "PwC", "role": "Project Manager", "start": "2016-01", "end": "2024-12"}],
            },
        ]
        candidates = []
        for cd in candidates_data:
            c = Candidate(**cd)
            db.add(c)
            candidates.append(c)
        await db.flush()
        print(f"  Created {len(candidates)} candidates")

        # ── PIPELINE STAGES ────────────────────────────────────────────────────
        stages_to_create = [
            (0, 0, PipelineStage.interview, recruiter1.id, 4),
            (11, 0, PipelineStage.screening, recruiter1.id, 3),
            (25, 0, PipelineStage.new, recruiter1.id, None),
            (1, 1, PipelineStage.acceptance, recruiter1.id, 5),
            (7, 1, PipelineStage.interview, recruiter1.id, 4),
            (17, 1, PipelineStage.screening, recruiter1.id, 3),
            (28, 1, PipelineStage.new, recruiter1.id, None),
            (2, 2, PipelineStage.hired, recruiter2.id, 5),
            (12, 2, PipelineStage.acceptance, recruiter2.id, 4),
            (19, 2, PipelineStage.interview, recruiter2.id, 3),
            (27, 2, PipelineStage.screening, recruiter2.id, 4),
            (3, 3, PipelineStage.interview, recruiter2.id, 5),
            (13, 3, PipelineStage.screening, recruiter2.id, 3),
            (24, 3, PipelineStage.new, recruiter2.id, None),
            (4, 4, PipelineStage.acceptance, recruiter3.id, 5),
            (14, 4, PipelineStage.interview, recruiter3.id, 4),
            (22, 4, PipelineStage.screening, recruiter3.id, 3),
            (5, 5, PipelineStage.hired, recruiter3.id, 5),
            (15, 5, PipelineStage.interview, recruiter3.id, 4),
            (28, 5, PipelineStage.screening, recruiter3.id, 2),
            (9, 6, PipelineStage.acceptance, recruiter1.id, 4),
            (20, 6, PipelineStage.interview, recruiter1.id, 3),
            (7, 7, PipelineStage.hired, recruiter2.id, 5),
            (18, 7, PipelineStage.interview, recruiter2.id, 3),
            (8, 8, PipelineStage.interview, recruiter1.id, 5),
            (29, 8, PipelineStage.screening, recruiter1.id, 4),
        ]

        for cand_idx, job_idx, stage, moved_by_id, rating in stages_to_create:
            await transition_process(
                db,
                candidate_id=candidates[cand_idx].id,
                job_id=jobs[job_idx].id,
                stage=stage,
                actor_user_id=moved_by_id,
                moved_at=now - timedelta(hours=abs(hash(str(cand_idx))) % 72),
                rating=rating,
                work_channel=PriorityChannel.database,
                # Provenance only; the explicit channel above is evaluated by
                # the same Priority Work policy as every other ingress.
                source_authority="seed",
            )
        await db.flush()
        print(f"  Created {len(stages_to_create)} pipeline stages")

        # ── CONTRACTS ─────────────────────────────────────────────────────────
        contracts_data = [
            {
                "candidate_id": candidates[2].id,
                "client_id": clients[2].id,
                "job_id": jobs[2].id,
                "start_date": date.today() - timedelta(days=60),
                "end_date": date.today() + timedelta(days=90),
                "rate_candidate": 20000,
                "rate_client": 26000,
                "currency": "PLN",
                "contract_type": ContractType.b2b,
                "status": ContractStatus.active,
            },
            {
                "candidate_id": candidates[5].id,
                "client_id": clients[5].id,
                "job_id": jobs[5].id,
                "start_date": date.today() - timedelta(days=45),
                "end_date": date.today() + timedelta(days=135),
                "rate_candidate": 14000,
                "rate_client": 18500,
                "currency": "PLN",
                "contract_type": ContractType.b2b,
                "status": ContractStatus.active,
            },
            {
                "candidate_id": candidates[7].id,
                "client_id": clients[9].id,
                "job_id": jobs[7].id,
                "start_date": date.today() - timedelta(days=30),
                "end_date": date.today() + timedelta(days=150),
                "rate_candidate": 16000,
                "rate_client": 21000,
                "currency": "PLN",
                "contract_type": ContractType.b2b,
                "status": ContractStatus.active,
            },
            {
                "candidate_id": candidates[0].id,
                "client_id": clients[0].id,
                "job_id": None,
                "start_date": date.today() - timedelta(days=90),
                "end_date": date.today() + timedelta(days=20),
                "rate_candidate": 18000,
                "rate_client": 24000,
                "currency": "PLN",
                "contract_type": ContractType.b2b,
                "status": ContractStatus.active,
            },
            {
                "candidate_id": candidates[4].id,
                "client_id": clients[4].id,
                "job_id": None,
                "start_date": date.today() - timedelta(days=120),
                "end_date": date.today() - timedelta(days=30),
                "rate_candidate": 17000,
                "rate_client": 22000,
                "currency": "PLN",
                "contract_type": ContractType.b2b,
                "status": ContractStatus.ended,
            },
        ]

        for cd_data in contracts_data:
            rate_c = cd_data.get("rate_client")
            rate_ca = cd_data.get("rate_candidate")
            margin = (rate_c - rate_ca) if rate_c and rate_ca else None
            c = Contract(**cd_data, margin=margin)
            db.add(c)
        await db.flush()
        print(f"  Created {len(contracts_data)} contracts")

        # ── ACTIVITY LOG ──────────────────────────────────────────────────────
        activities_list = [
            Activity(entity_type="candidate", entity_id=candidates[2].id, action="hired", user_id=admin_user.id,
                     details={"job": "DevOps Engineer", "client": "Pekao SA"}),
            Activity(entity_type="candidate", entity_id=candidates[5].id, action="hired", user_id=recruiter3.id,
                     details={"job": "React Frontend", "client": "Asseco"}),
            Activity(entity_type="candidate", entity_id=candidates[7].id, action="hired", user_id=recruiter2.id,
                     details={"job": "iOS Developer", "client": "ING Bank"}),
            Activity(entity_type="job", entity_id=jobs[0].id, action="published", user_id=recruiter1.id,
                     details={"title": "Senior Angular Developer"}),
            Activity(entity_type="job", entity_id=jobs[8].id, action="published", user_id=recruiter1.id,
                     details={"title": "Tech Lead / Architect", "priority": "urgent"}),
            Activity(entity_type="candidate", entity_id=candidates[1].id, action="stage_changed", user_id=recruiter1.id,
                     details={"stage": "offer", "job": "Java Backend"}),
            Activity(entity_type="contract", entity_id=1, action="created", user_id=admin_user.id,
                     details={"candidate": "Michał Wiśniewski", "client": "Pekao SA"}),
            Activity(entity_type="candidate", entity_id=candidates[0].id, action="created", user_id=recruiter1.id,
                     details={"name": "Piotr Kowalski", "source": "linkedin"}),
            Activity(entity_type="client", entity_id=clients[7].id, action="created", user_id=admin_user.id,
                     details={"name": "PKO Bank Polski", "status": "prospect"}),
        ]
        for act in activities_list:
            db.add(act)
        await db.flush()

        # ── USER ACTIVITIES (50+ realistic entries) ────────────────────────────
        user_activities_data = [
            # Marta (recruiter2) — recruiter — adds many candidates
            (recruiter2.id, UserActionType.candidate_added, "candidate", candidates[0].id,
             {"name": "Piotr Kowalski", "source": "linkedin"}, days_ago(14)),
            (recruiter2.id, UserActionType.candidate_added, "candidate", candidates[1].id,
             {"name": "Agnieszka Nowak", "source": "pracuj"}, days_ago(13)),
            (recruiter2.id, UserActionType.candidate_added, "candidate", candidates[3].id,
             {"name": "Katarzyna Zielińska", "source": "jjit"}, days_ago(12)),
            (recruiter2.id, UserActionType.candidate_added, "candidate", candidates[6].id,
             {"name": "Rafał Mazur", "source": "linkedin"}, days_ago(11)),
            (recruiter2.id, UserActionType.candidate_added, "candidate", candidates[7].id,
             {"name": "Magdalena Wójcik", "source": "linkedin"}, days_ago(10)),
            (recruiter2.id, UserActionType.call_made, "candidate", candidates[0].id,
             {"duration_min": 15, "topic": "Angular oferta Nordea"}, days_ago(13)),
            (recruiter2.id, UserActionType.call_made, "candidate", candidates[1].id,
             {"duration_min": 20, "topic": "Java Backend BNP"}, days_ago(12)),
            (recruiter2.id, UserActionType.call_made, "candidate", candidates[3].id,
             {"duration_min": 12, "topic": "QA Ferro"}, days_ago(11)),
            (recruiter2.id, UserActionType.screening_done, "candidate", candidates[0].id,
             {"job": "Senior Angular Developer", "rating": 4}, days_ago(12)),
            (recruiter2.id, UserActionType.screening_done, "candidate", candidates[1].id,
             {"job": "Java Backend Developer", "rating": 5}, days_ago(11)),
            (recruiter2.id, UserActionType.screening_done, "candidate", candidates[7].id,
             {"job": "iOS Developer", "rating": 5}, days_ago(9)),
            (recruiter2.id, UserActionType.interview_scheduled, "candidate", candidates[0].id,
             {"job": "Senior Angular Developer", "client": "Nordea", "date": "2026-03-20"}, days_ago(9)),
            (recruiter2.id, UserActionType.interview_scheduled, "candidate", candidates[7].id,
             {"job": "iOS Developer", "client": "ING Bank", "date": "2026-03-15"}, days_ago(8)),
            (recruiter2.id, UserActionType.placement_closed, "candidate", candidates[7].id,
             {"job": "iOS Developer", "client": "ING Bank", "rate": 21000}, days_ago(5)),

            # Tomasz (recruiter3) — sourcer — sourcing from database
            (recruiter3.id, UserActionType.candidate_added, "candidate", candidates[4].id,
             {"name": "Tomasz Dąbrowski", "source": "linkedin"}, days_ago(20)),
            (recruiter3.id, UserActionType.candidate_added, "candidate", candidates[5].id,
             {"name": "Joanna Lewandowska", "source": "manual"}, days_ago(19)),
            (recruiter3.id, UserActionType.candidate_added, "candidate", candidates[10].id,
             {"name": "Bartosz Jankowski", "source": "jjit"}, days_ago(18)),
            (recruiter3.id, UserActionType.candidate_added, "candidate", candidates[14].id,
             {"name": "Łukasz Zając", "source": "linkedin"}, days_ago(17)),
            (recruiter3.id, UserActionType.candidate_added, "candidate", candidates[22].id,
             {"name": "Marta Nowicka", "source": "linkedin"}, days_ago(16)),
            (recruiter3.id, UserActionType.candidate_added, "candidate", candidates[20].id,
             {"name": "Jakub Ostrowski", "source": "jjit"}, days_ago(15)),
            (recruiter3.id, UserActionType.call_made, "candidate", candidates[4].id,
             {"duration_min": 18, "topic": "Python Data Engineering Cognism"}, days_ago(19)),
            (recruiter3.id, UserActionType.call_made, "candidate", candidates[5].id,
             {"duration_min": 22, "topic": "React Frontend Asseco"}, days_ago(18)),
            (recruiter3.id, UserActionType.call_made, "candidate", candidates[14].id,
             {"duration_min": 16, "topic": "Python Backend wstępna rozmowa"}, days_ago(16)),
            (recruiter3.id, UserActionType.screening_done, "candidate", candidates[4].id,
             {"job": "Python Data Engineer", "rating": 5}, days_ago(18)),
            (recruiter3.id, UserActionType.screening_done, "candidate", candidates[5].id,
             {"job": "React Frontend Developer", "rating": 5}, days_ago(17)),
            (recruiter3.id, UserActionType.screening_done, "candidate", candidates[14].id,
             {"job": "Python Data Engineer", "rating": 4}, days_ago(15)),
            (recruiter3.id, UserActionType.interview_scheduled, "candidate", candidates[4].id,
             {"job": "Python Data Engineer", "client": "Cognism", "date": "2026-03-18"}, days_ago(14)),
            (recruiter3.id, UserActionType.interview_scheduled, "candidate", candidates[5].id,
             {"job": "React Frontend Developer", "client": "Asseco", "date": "2026-03-12"}, days_ago(10)),
            (recruiter3.id, UserActionType.placement_closed, "candidate", candidates[5].id,
             {"job": "React Frontend Developer", "client": "Asseco", "rate": 18500}, days_ago(7)),

            # Olaf (recruiter1) — delivery lead — manages processes
            (recruiter1.id, UserActionType.candidate_added, "candidate", candidates[8].id,
             {"name": "Paweł Kaczmarek", "source": "referral"}, days_ago(25)),
            (recruiter1.id, UserActionType.candidate_added, "candidate", candidates[9].id,
             {"name": "Anna Szymańska", "source": "linkedin"}, days_ago(23)),
            (recruiter1.id, UserActionType.candidate_added, "candidate", candidates[29].id,
             {"name": "Marek Olszewski", "source": "referral"}, days_ago(20)),
            (recruiter1.id, UserActionType.call_made, "candidate", candidates[8].id,
             {"duration_min": 45, "topic": "Tech Lead Architect — deep dive"}, days_ago(24)),
            (recruiter1.id, UserActionType.call_made, "candidate", candidates[9].id,
             {"duration_min": 30, "topic": "Scrum Master Comarch"}, days_ago(22)),
            (recruiter1.id, UserActionType.call_made, "candidate", candidates[1].id,
             {"duration_min": 25, "topic": "Java Backend — update"}, days_ago(8)),
            (recruiter1.id, UserActionType.call_made, "candidate", candidates[0].id,
             {"duration_min": 20, "topic": "Angular — update po interview"}, days_ago(6)),
            (recruiter1.id, UserActionType.screening_done, "candidate", candidates[8].id,
             {"job": "Tech Lead / Architect", "rating": 5}, days_ago(23)),
            (recruiter1.id, UserActionType.screening_done, "candidate", candidates[9].id,
             {"job": "Scrum Master / Agile Coach", "rating": 4}, days_ago(21)),
            (recruiter1.id, UserActionType.screening_done, "candidate", candidates[29].id,
             {"job": "Tech Lead / Architect", "rating": 4}, days_ago(18)),
            (recruiter1.id, UserActionType.interview_scheduled, "candidate", candidates[8].id,
             {"job": "Tech Lead / Architect", "client": "Pekao SA", "date": "2026-03-22"}, days_ago(15)),
            (recruiter1.id, UserActionType.interview_scheduled, "candidate", candidates[9].id,
             {"job": "Scrum Master", "client": "Comarch", "date": "2026-03-19"}, days_ago(12)),
            (recruiter1.id, UserActionType.stage_changed, "candidate", candidates[1].id,
             {"from_stage": "interview", "to_stage": "offer", "job": "Java Backend"}, days_ago(5)),
            (recruiter1.id, UserActionType.placement_closed, "candidate", candidates[2].id,
             {"job": "DevOps Engineer", "client": "Pekao SA", "rate": 26000}, days_ago(30)),

            # Admin — various actions
            (admin_user.id, UserActionType.candidate_added, "candidate", candidates[2].id,
             {"name": "Michał Wiśniewski", "source": "linkedin"}, days_ago(45)),
            (admin_user.id, UserActionType.screening_done, "candidate", candidates[2].id,
             {"job": "DevOps Cloud Engineer", "rating": 5}, days_ago(44)),
            (admin_user.id, UserActionType.interview_scheduled, "candidate", candidates[2].id,
             {"job": "DevOps Engineer", "client": "Pekao SA", "date": "2026-02-10"}, days_ago(40)),
            (admin_user.id, UserActionType.placement_closed, "candidate", candidates[2].id,
             {"job": "DevOps Engineer", "client": "Pekao SA", "rate": 26000}, days_ago(35)),
            (admin_user.id, UserActionType.note_added, "candidate", candidates[0].id,
             {"note_type": "call", "content": "Potwierdził zainteresowanie projektem Nordea"}, days_ago(10)),
            (admin_user.id, UserActionType.call_made, "candidate", candidates[8].id,
             {"duration_min": 60, "topic": "Tech Lead — rozmowa strategiczna z DL"}, days_ago(20)),

            # Additional recent activities
            (recruiter2.id, UserActionType.candidate_added, "candidate", candidates[12].id,
             {"name": "Sebastian Wiśniewski", "source": "linkedin"}, days_ago(3)),
            (recruiter2.id, UserActionType.call_made, "candidate", candidates[12].id,
             {"duration_min": 14, "topic": "DevOps screening call"}, days_ago(2)),
            (recruiter3.id, UserActionType.candidate_added, "candidate", candidates[15].id,
             {"name": "Monika Grabowska", "source": "manual"}, days_ago(2)),
            (recruiter1.id, UserActionType.call_made, "candidate", candidates[9].id,
             {"duration_min": 15, "topic": "Update przed interview"}, days_ago(1)),
            (recruiter2.id, UserActionType.screening_done, "candidate", candidates[12].id,
             {"job": "DevOps Cloud Engineer", "rating": 4}, days_ago(1)),
        ]

        for user_id, action_type, entity_type, entity_id, details, created_at in user_activities_data:
            ua = UserActivity(
                user_id=user_id,
                action_type=action_type,
                entity_type=entity_type,
                entity_id=entity_id,
                details=details,
                created_at=created_at,
            )
            db.add(ua)
        await db.flush()
        print(f"  Created {len(user_activities_data)} user activity records")
        print(f"  Created {len(activities_list)} system activity log entries")

        # ── EMAIL TEMPLATES ───────────────────────────────────────────────────
        email_templates_data = [
            {
                "name": "Potwierdzenie aplikacji",
                "category": EmailCategory.application_received,
                "subject": "Dziękujemy za aplikację — {{job_title}}",
                "body": (
                    "Szanowny/a {{candidate_name}},\n\n"
                    "Dziękujemy za przesłanie aplikacji na stanowisko {{job_title}} w {{company_name}}.\n\n"
                    "Potwierdzamy otrzymanie Twojego zgłoszenia. Nasz zespół zapozna się z Twoim profilem "
                    "i skontaktuje się z Tobą w ciągu kilku dni roboczych.\n\n"
                    "Dziękujemy za zainteresowanie współpracą z nami.\n\n"
                    "Z poważaniem,\nZespół Rekrutacji\n{{company_name}}"
                ),
                "is_default": True,
            },
            {
                "name": "Zaproszenie na screening",
                "category": EmailCategory.screening_invite,
                "subject": "Zaproszenie na rozmowę wstępną — {{job_title}}",
                "body": (
                    "Szanowny/a {{candidate_name}},\n\n"
                    "Chcielibyśmy zaprosić Cię na krótką rozmowę wstępną (screening) dotyczącą stanowiska "
                    "{{job_title}} w {{company_name}}.\n\n"
                    "Rozmowa potrwa ok. 20-30 minut i odbędzie się telefonicznie lub przez MS Teams. "
                    "Prosimy o kontakt w celu ustalenia terminu.\n\n"
                    "Czekamy na Twoją odpowiedź.\n\n"
                    "Z poważaniem,\nZespół Rekrutacji\n{{company_name}}"
                ),
                "is_default": True,
            },
            {
                "name": "Zaproszenie na interview",
                "category": EmailCategory.interview_invite,
                "subject": "Zaproszenie na rozmowę z klientem — {{job_title}}",
                "body": (
                    "Szanowny/a {{candidate_name}},\n\n"
                    "Mamy przyjemność poinformować, że Twój profil wzbudził duże zainteresowanie "
                    "i chcielibyśmy zaprosić Cię na spotkanie z klientem w ramach procesu rekrutacji "
                    "na stanowisko {{job_title}}.\n\n"
                    "Spotkanie odbędzie się w formie wideokonferencji lub osobistej wizyty. "
                    "Prosimy o kontakt, abyśmy mogli ustalić szczegóły.\n\n"
                    "Serdecznie gratulujemy dotarcia do tego etapu!\n\n"
                    "Z poważaniem,\nZespół Rekrutacji\n{{company_name}}"
                ),
                "is_default": True,
            },
            {
                "name": "Odrzucenie",
                "category": EmailCategory.rejection,
                "subject": "Informacja o wynikach rekrutacji — {{job_title}}",
                "body": (
                    "Szanowny/a {{candidate_name}},\n\n"
                    "Dziękujemy za udział w procesie rekrutacji na stanowisko {{job_title}} "
                    "w {{company_name}} oraz za czas poświęcony na spotkania z naszym zespołem.\n\n"
                    "Po dokładnym rozważeniu wszystkich kandydatur, podjęliśmy decyzję o wyborze innego "
                    "kandydata, którego profil był lepiej dopasowany do aktualnych potrzeb klienta.\n\n"
                    "Doceniamy Twoje zaangażowanie i zachowujemy Twój profil w naszej bazie — "
                    "będziemy kontaktować się w przypadku pojawienia się odpowiednich ofert.\n\n"
                    "Życzymy powodzenia w dalszej karierze zawodowej.\n\n"
                    "Z poważaniem,\nZespół Rekrutacji\n{{company_name}}"
                ),
                "is_default": True,
            },
            {
                "name": "Oferta współpracy",
                "category": EmailCategory.offer,
                "subject": "Oferta współpracy — {{job_title}} | {{company_name}}",
                "body": (
                    "Szanowny/a {{candidate_name}},\n\n"
                    "Z przyjemnością informujemy, że po przeprowadzeniu procesu rekrutacji, "
                    "zdecydowaliśmy się złożyć Ci ofertę współpracy na stanowisko {{job_title}}.\n\n"
                    "Szczegóły oferty, w tym warunki finansowe i termin rozpoczęcia współpracy, "
                    "zostaną omówione podczas rozmowy z naszym konsultantem.\n\n"
                    "Prosimy o kontakt w celu potwierdzenia zainteresowania i ustalenia dalszych kroków.\n\n"
                    "Gratulujemy i cieszymy się na przyszłą współpracę!\n\n"
                    "Z poważaniem,\nZespół Rekrutacji\n{{company_name}}"
                ),
                "is_default": True,
            },
            {
                "name": "Ogólna wiadomość",
                "category": EmailCategory.general,
                "subject": "Wiadomość od {{company_name}}",
                "body": (
                    "Szanowny/a {{candidate_name}},\n\n"
                    "Piszemy do Ciebie w związku z Twoim profilem w naszej bazie kandydatów.\n\n"
                    "[Treść wiadomości]\n\n"
                    "W razie pytań, prosimy o kontakt.\n\n"
                    "Z poważaniem,\nZespół Rekrutacji\n{{company_name}}"
                ),
                "is_default": True,
            },
        ]

        for et_data in email_templates_data:
            et = EmailTemplate(**et_data, created_by=admin_user.id)
            db.add(et)
        await db.flush()
        print(f"  Created {len(email_templates_data)} email templates")

        # ── JOB POSTINGS (simulated) ───────────────────────────────────────────
        postings_data = [
            # Job 0 — Senior Angular Developer (Nordea) — Pracuj + JJIT + LinkedIn
            {
                "job_idx": 0, "portal": Portal.pracuj_pl, "status": PostingStatus.published,
                "published_at": days_ago(20), "expires_at": now + timedelta(days=10),
                "views": 1520, "applications": 42,
                "external_id": "PRACUJ-ANG-001", "url": "https://pracuj.pl/praca/senior-angular-nordea-001",
            },
            {
                "job_idx": 0, "portal": Portal.justjoinit, "status": PostingStatus.published,
                "published_at": days_ago(18), "expires_at": now + timedelta(days=12),
                "views": 980, "applications": 31,
                "external_id": "JJIT-ANG-001", "url": "https://justjoin.it/offers/nexus-angular-nordea",
            },
            {
                "job_idx": 0, "portal": Portal.linkedin, "status": PostingStatus.published,
                "published_at": days_ago(15), "expires_at": now + timedelta(days=15),
                "views": 2000, "applications": 50,
                "external_id": "LI-ANG-001", "url": "https://linkedin.com/jobs/view/1000001",
            },
            # Job 1 — Java Backend Developer (BNP) — Pracuj + JJIT
            {
                "job_idx": 1, "portal": Portal.pracuj_pl, "status": PostingStatus.published,
                "published_at": days_ago(25), "expires_at": now + timedelta(days=3),
                "views": 890, "applications": 28,
                "external_id": "PRACUJ-JAVA-001", "url": "https://pracuj.pl/praca/java-backend-bnp-001",
            },
            {
                "job_idx": 1, "portal": Portal.justjoinit, "status": PostingStatus.published,
                "published_at": days_ago(22), "expires_at": now + timedelta(days=6),
                "views": 1100, "applications": 36,
                "external_id": "JJIT-JAVA-001", "url": "https://justjoin.it/offers/nexus-java-bnp",
            },
            # Job 2 — DevOps / Cloud Engineer (Pekao) — LinkedIn + NoFluffJobs
            {
                "job_idx": 2, "portal": Portal.linkedin, "status": PostingStatus.published,
                "published_at": days_ago(14), "expires_at": now + timedelta(days=21),
                "views": 1750, "applications": 22,
                "external_id": "LI-DEVOPS-001", "url": "https://linkedin.com/jobs/view/1000002",
            },
            {
                "job_idx": 2, "portal": Portal.nofluffjobs, "status": PostingStatus.published,
                "published_at": days_ago(12), "expires_at": now + timedelta(days=18),
                "views": 640, "applications": 14,
                "external_id": "NFF-DEVOPS-001", "url": "https://nofluffjobs.com/job/nexus-devops-1",
            },
            # Job 3 — QA Automation Engineer (Ferro) — Pracuj (expired)
            {
                "job_idx": 3, "portal": Portal.pracuj_pl, "status": PostingStatus.expired,
                "published_at": days_ago(60), "expires_at": days_ago(30),
                "views": 420, "applications": 12,
                "external_id": "PRACUJ-QA-001", "url": "https://pracuj.pl/praca/qa-automation-ferro-001",
            },
            {
                "job_idx": 3, "portal": Portal.bulldogjob, "status": PostingStatus.published,
                "published_at": days_ago(10), "expires_at": now + timedelta(days=20),
                "views": 310, "applications": 8,
                "external_id": "BDJ-QA-001", "url": "https://bulldogjob.pl/companies/jobs/nexus-qa-1",
            },
            # Job 4 — Python Data Engineer (Cognism) — JJIT + LinkedIn
            {
                "job_idx": 4, "portal": Portal.justjoinit, "status": PostingStatus.published,
                "published_at": days_ago(10), "expires_at": now + timedelta(days=20),
                "views": 1380, "applications": 45,
                "external_id": "JJIT-PY-001", "url": "https://justjoin.it/offers/nexus-python-cognism",
            },
            {
                "job_idx": 4, "portal": Portal.linkedin, "status": PostingStatus.published,
                "published_at": days_ago(8), "expires_at": now + timedelta(days=22),
                "views": 900, "applications": 19,
                "external_id": "LI-PY-001", "url": "https://linkedin.com/jobs/view/1000003",
            },
            # Job 5 — React Frontend Developer (Asseco) — Pracuj + BulldogJob
            {
                "job_idx": 5, "portal": Portal.pracuj_pl, "status": PostingStatus.published,
                "published_at": days_ago(30), "expires_at": now + timedelta(days=15),
                "views": 760, "applications": 23,
                "external_id": "PRACUJ-REACT-001", "url": "https://pracuj.pl/praca/react-frontend-asseco-001",
            },
            {
                "job_idx": 5, "portal": Portal.bulldogjob, "status": PostingStatus.published,
                "published_at": days_ago(28), "expires_at": now + timedelta(days=12),
                "views": 480, "applications": 15,
                "external_id": "BDJ-REACT-001", "url": "https://bulldogjob.pl/companies/jobs/nexus-react-1",
            },
            # Job 8 — Tech Lead / Architect (Pekao) — LinkedIn (urgent!)
            {
                "job_idx": 8, "portal": Portal.linkedin, "status": PostingStatus.published,
                "published_at": days_ago(7), "expires_at": now + timedelta(days=7),
                "views": 1920, "applications": 17,
                "external_id": "LI-TL-001", "url": "https://linkedin.com/jobs/view/1000004",
            },
            # Job 8 — NoFluffJobs
            {
                "job_idx": 8, "portal": Portal.nofluffjobs, "status": PostingStatus.published,
                "published_at": days_ago(6), "expires_at": now + timedelta(days=8),
                "views": 830, "applications": 11,
                "external_id": "NFF-TL-001", "url": "https://nofluffjobs.com/job/nexus-techlead-1",
            },
        ]

        postings = []
        for pd in postings_data:
            jp = JobPosting(
                job_id=jobs[pd["job_idx"]].id,
                portal=pd["portal"],
                status=pd["status"],
                published_at=pd["published_at"],
                expires_at=pd["expires_at"],
                views=pd["views"],
                applications=pd["applications"],
                external_id=pd["external_id"],
                url=pd["url"],
            )
            db.add(jp)
            postings.append(jp)
        await db.flush()
        print(f"  Created {len(postings)} job postings (simulated)")

        # ── CALLS (CloudTalk placeholder) ──────────────────────────────────────
        calls_data = [
            {
                "candidate_id": candidates[0].id,   # Piotr Kowalski
                "user_id": recruiter1.id,
                "direction": CallDirection.outbound,
                "duration_seconds": 14 * 60 + 22,  # 14:22
                "status": CallStatus.completed,
                "transcript": (
                    "Rekruter: Dzień dobry Piotrze, dzwonię w sprawie projektu Angular dla Nordea. "
                    "Czy ma Pan chwilę?\n"
                    "Kandydat: Tak, oczywiście, słucham.\n"
                    "Rekruter: Chciałem potwierdzić zainteresowanie i omówić szczegóły. "
                    "Projekt startuje w przyszłym miesiącu, praca hybrydowa z Warszawy.\n"
                    "Kandydat: Brzmi dobrze. Stawka B2B to 23-25k?\n"
                    "Rekruter: Tak, budżet jest elastyczny. Mogę umówić rozmowę z klientem na przyszły tydzień?\n"
                    "Kandydat: Jak najbardziej, najlepiej środa lub czwartek."
                ),
                "summary": "Kandydat zainteresowany projektem Nordea Angular. Umówiono rozmowę z klientem na środę/czwartek.",
                "created_at": days_ago(13),
            },
            {
                "candidate_id": candidates[1].id,   # Agnieszka Nowak
                "user_id": recruiter1.id,
                "direction": CallDirection.outbound,
                "duration_seconds": 19 * 60 + 48,  # 19:48
                "status": CallStatus.completed,
                "transcript": (
                    "Rekruter: Dzień dobry, mówię do Agnieszki Nowak?\n"
                    "Kandydat: Tak, słucham.\n"
                    "Rekruter: Dzwonię z B2B.net w sprawie pozycji Java Backend Lead dla BNP Paribas. "
                    "Widziałem Pani profil — ma Pani naprawdę solidne doświadczenie w fintech.\n"
                    "Kandydat: Dziękuję, tak, 8 lat w bankowości.\n"
                    "Rekruter: Budżet do 22k B2B. Co Pani myśli?\n"
                    "Kandydat: Interesujące. Kiedy start projektu?\n"
                    "Rekruter: Kwiecień. Może Pani porozmawiać z klientem w przyszłym tygodniu?\n"
                    "Kandydat: Tak, we wtorek jestem dyspozycyjna."
                ),
                "summary": "Rozmowa wstępna z Agnieszką Nowak dot. Java Backend BNP. Zainteresowana, umówiono na wtorek.",
                "created_at": days_ago(12),
            },
            {
                "candidate_id": candidates[2].id,   # Michał Wiśniewski
                "user_id": recruiter2.id,
                "direction": CallDirection.outbound,
                "duration_seconds": 8 * 60 + 15,   # 8:15
                "status": CallStatus.completed,
                "transcript": None,
                "summary": "Screening DevOps. Kandydat dostępny od następnego miesiąca. Zainteresowany projektem Azure/K8s.",
                "created_at": days_ago(10),
            },
            {
                "candidate_id": candidates[4].id,   # Tomasz Dąbrowski
                "user_id": recruiter3.id,
                "direction": CallDirection.outbound,
                "duration_seconds": 17 * 60 + 33,
                "status": CallStatus.completed,
                "transcript": None,
                "summary": "Python Data Engineer — bardzo dobry fit dla Cognism. Doświadczenie z Airflow i BigQuery. Zainteresowany.",
                "created_at": days_ago(19),
            },
            {
                "candidate_id": candidates[5].id,   # Joanna Lewandowska
                "user_id": recruiter3.id,
                "direction": CallDirection.outbound,
                "duration_seconds": 22 * 60 + 7,
                "status": CallStatus.completed,
                "transcript": (
                    "Rekruter: Cześć Joanno, chcę porozmawiać o projekcie React dla Asseco.\n"
                    "Kandydat: Cześć, super! Właśnie szukam nowych możliwości.\n"
                    "Rekruter: Projekt backoffice, React + TypeScript, hybrydowo z Rzeszowa lub remote.\n"
                    "Kandydat: Rzeszów? Jestem z Gdańska, ale remote OK.\n"
                    "Rekruter: Tak, większość czasu remote. Stawka 17-20k B2B.\n"
                    "Kandydat: Brzmi idealnie. Kiedy interview?"
                ),
                "summary": "Joanna Lewandowska zainteresowana projektem React/Asseco. Potwierdzona praca remote. Interview wkrótce.",
                "created_at": days_ago(18),
            },
            {
                "candidate_id": candidates[8].id,   # Paweł Kaczmarek
                "user_id": recruiter1.id,
                "direction": CallDirection.outbound,
                "duration_seconds": 44 * 60 + 52,
                "status": CallStatus.completed,
                "transcript": None,
                "summary": "Deep-dive z Tech Leadem Pawłem K. 12 lat w Java Enterprise, PKO BP. Idealny kandydat na Architekta Pekao. Wymaga 60 dni wypowiedzenia.",
                "created_at": days_ago(24),
            },
            {
                "candidate_id": candidates[3].id,   # Katarzyna Zielińska
                "user_id": recruiter2.id,
                "direction": CallDirection.inbound,
                "duration_seconds": 6 * 60 + 40,
                "status": CallStatus.completed,
                "transcript": None,
                "summary": "Kandydatka zadzwoniła sama — bardzo zmotywowana, pyta o status procesu QA/Ferro.",
                "created_at": days_ago(8),
            },
            {
                "candidate_id": candidates[12].id,  # Sebastian Wiśniewski
                "user_id": recruiter2.id,
                "direction": CallDirection.outbound,
                "duration_seconds": 13 * 60 + 18,
                "status": CallStatus.completed,
                "transcript": None,
                "summary": "Screening DevOps Sebastian W. AWS expert. Ciekawa alternatywa dla projektu Cloud Engineer.",
                "created_at": days_ago(2),
            },
            {
                "candidate_id": candidates[9].id,   # Anna Szymańska
                "user_id": recruiter1.id,
                "direction": CallDirection.outbound,
                "duration_seconds": 0,
                "status": CallStatus.missed,
                "transcript": None,
                "summary": None,
                "created_at": days_ago(5),
            },
            {
                "candidate_id": candidates[9].id,   # Anna Szymańska — ponowna próba
                "user_id": recruiter1.id,
                "direction": CallDirection.outbound,
                "duration_seconds": 14 * 60 + 55,
                "status": CallStatus.completed,
                "transcript": None,
                "summary": "Anna Szymańska — update przed interview Scrum Master/Comarch. Gotowa i zmotywowana.",
                "created_at": days_ago(1),
            },
        ]

        calls = []
        for cd in calls_data:
            created_at = cd.pop("created_at")
            c = Call(**cd)
            c.created_at = created_at
            db.add(c)
            calls.append(c)
        await db.flush()
        print(f"  Created {len(calls)} call records (CloudTalk placeholder)")

        # ─────────────────────────────────────────────────────────────────────
        # V3: ClientKnowledge — wiedza o klientach
        # ─────────────────────────────────────────────────────────────────────
        knowledge_data = [
            # Nordea — selling points
            {
                "client_id": clients[0].id,
                "category": KnowledgeCategory.selling_points,
                "content": (
                    "Nordea oferuje stabilne środowisko enterprise z możliwością pracy hybrydowej (2-3 dni biuro). "
                    "Stack technologiczny: Angular 15+, Java 17, Kubernetes, Azure DevOps. "
                    "Duży nacisk na jakość kodu, code review, testy automatyczne. "
                    "Kultura pracy skandynawska — work-life balance, brak nadgodzin. "
                    "Praca w międzynarodowym środowisku (ang. jest językiem roboczym w IT)."
                ),
                "source": "Olaf Moczydłowski — rozmowa z hiring managerem 2025-11",
                "added_by_idx": 1,  # Olaf
            },
            # Nordea — interview questions
            {
                "client_id": clients[0].id,
                "category": KnowledgeCategory.interview_questions,
                "content": (
                    "Pytania techniczne Angular:\n"
                    "1. Jak zarządzasz stanem aplikacji w Angular? (NgRx vs Signals)\n"
                    "2. Opowiedz o optymalizacji wydajności w Angular — OnPush, trackBy, lazy loading\n"
                    "3. Jak testujesz komponenty Angular? (Jasmine, Spectator)\n"
                    "4. Doświadczenie z mikrofrontendami (Module Federation)?\n"
                    "\nPytania behawioralne:\n"
                    "1. Opisz sytuację, w której nie zgadzałeś się z decyzją techniczną w zespole\n"
                    "2. Jak radzisz sobie z legacy kodem w dużym projekcie?"
                ),
                "source": "Feedback po 3 procesach rekrutacyjnych dla Nordea 2025",
                "added_by_idx": 0,  # Artur
            },
            # BNP Paribas — selling points
            {
                "client_id": clients[1].id,
                "category": KnowledgeCategory.selling_points,
                "content": (
                    "BNP Paribas to jeden z największych banków w Polsce z bardzo stabilną pozycją. "
                    "Projekty długoterminowe (3-5 lat), świetna infrastruktura IT, budżety bez limitów. "
                    "Stack Java 17/21, Spring Boot 3, Kafka, Kubernetes, PostgreSQL. "
                    "Praca w hybrydzie — 2 dni biuro (Warszawa Kasprzaka), reszta remote. "
                    "Certyfikaty i szkolenia pokrywane przez klienta. "
                    "Kontrakty B2B rozliczane miesięcznie, brak ryzyka nieregularności płatności."
                ),
                "source": "Marta Kowalska — feedback po procesie 2025-10",
                "added_by_idx": 2,  # Marta
            },
            # BNP Paribas — interview questions
            {
                "client_id": clients[1].id,
                "category": KnowledgeCategory.interview_questions,
                "content": (
                    "Pytania Java Backend (BNP Paribas):\n"
                    "1. Jak rozumiesz architekturę mikroserwisów w kontekście bankowym? (saga, outbox pattern)\n"
                    "2. Doświadczenie z Kafka — producer/consumer, gwarancje dostarczenia\n"
                    "3. Jak radzisz sobie z transakcjami rozproszonymi?\n"
                    "4. Znajomość CQRS i Event Sourcing\n"
                    "5. Pytania o testy integracyjne (Testcontainers, MockMvc)\n"
                    "\nCase study:\n"
                    "Zaprojektuj serwis przetwarzający 1M transakcji/dobę — jak obsłużysz spójność danych?"
                ),
                "source": "Piotr Jankowski (hiring manager) — briefing 2025-09",
                "added_by_idx": 1,  # Olaf
            },
            # Nordea — tech stack
            {
                "client_id": clients[0].id,
                "category": KnowledgeCategory.tech_stack,
                "content": (
                    "Frontend: Angular 15+, TypeScript, NgRx, RxJS, Jest, Cypress\n"
                    "Backend: Java 17, Spring Boot 3, Kafka, PostgreSQL, Redis\n"
                    "Infrastructure: Kubernetes (AKS), Azure DevOps, Terraform\n"
                    "Monitoring: Grafana, Prometheus, ELK Stack\n"
                    "Metodologia: SAFe, dwutygodniowe sprinty, code review obowiązkowe\n"
                    "Języki: Angielski roboczy w IT, polski w codziennych kontaktach"
                ),
                "source": "Onboarding doc udostępniony przez Nordea 2025-11",
                "added_by_idx": 0,  # Artur
            },
        ]

        for kd in knowledge_data:
            added_by_idx = kd.pop("added_by_idx")
            k = ClientKnowledge(
                **kd,
                added_by=users[added_by_idx].id,
            )
            db.add(k)
        await db.flush()
        print(f"  Created {len(knowledge_data)} client knowledge entries")

        # ─────────────────────────────────────────────────────────────────────
        # V3: ScreeningNotes — ustrukturyzowane notatki ze screeningu
        # ─────────────────────────────────────────────────────────────────────
        screening_data = [
            # Piotr Kowalski — Angular (candidates[0])
            {
                "candidate_id": candidates[0].id,
                "job_id": jobs[0].id,
                "author_id": recruiter1.id,
                "screening_type": ScreeningType.initial_screening,
                "motivation_primary": MotivationType.money,
                "motivation_secondary": MotivationType.project,
                "salary_expectation": 23000,
                "salary_currency": "PLN",
                "salary_negotiable": True,
                "verified_skills": [
                    {"skill": "Angular", "level": "confirmed", "notes": "6 lat, Nordea-like projekty"},
                    {"skill": "TypeScript", "level": "confirmed", "notes": "expert poziom"},
                    {"skill": "RxJS", "level": "confirmed", "notes": "solidna znajomość"},
                    {"skill": "NgRx", "level": "basic", "notes": "zna koncepty, mniej praktyki"},
                ],
                "red_flags": None,
                "personality_notes": "Bardzo komunikatywny, doświadczenie w pracy z klientem enterprise. Angielski płynny.",
                "readiness_to_change": 4,
                "counteroffer_risk": CounterOfferRisk.low,
                "closing_strategy": "Podkreślić renomę Nordea i stabilność projektu. Stawka 23k akceptowalna.",
                "overall_impression": 4,
            },
            # Agnieszka Nowak — Java (candidates[1])
            {
                "candidate_id": candidates[1].id,
                "job_id": jobs[1].id,
                "author_id": recruiter1.id,
                "screening_type": ScreeningType.initial_screening,
                "motivation_primary": MotivationType.growth,
                "motivation_secondary": MotivationType.technology,
                "salary_expectation": 20000,
                "salary_currency": "PLN",
                "salary_negotiable": False,
                "verified_skills": [
                    {"skill": "Java", "level": "confirmed", "notes": "8 lat, expert — prowadziła zespół"},
                    {"skill": "Spring Boot", "level": "confirmed", "notes": "Spring Boot 3, mocno"},
                    {"skill": "Kafka", "level": "confirmed", "notes": "produkcja, kilka projektów"},
                    {"skill": "PostgreSQL", "level": "confirmed", "notes": "6 lat, tuning query"},
                ],
                "red_flags": None,
                "personality_notes": "Ambitna, self-starter. Szuka projektu gdzie będzie mogła prowadzić architekturę.",
                "readiness_to_change": 5,
                "counteroffer_risk": CounterOfferRisk.low,
                "closing_strategy": "Podkreślić możliwość tech leadership w BNP. Ma zainteresowanie bankowością.",
                "overall_impression": 5,
            },
            # Agnieszka Nowak — prep call (candidates[1])
            {
                "candidate_id": candidates[1].id,
                "job_id": jobs[1].id,
                "author_id": recruiter1.id,
                "screening_type": ScreeningType.prep_call,
                "motivation_primary": MotivationType.growth,
                "motivation_secondary": MotivationType.money,
                "salary_expectation": 21000,
                "salary_currency": "PLN",
                "salary_negotiable": True,
                "verified_skills": [
                    {"skill": "Java", "level": "confirmed", "notes": "potwierdzone, menedżer jak i dev"},
                    {"skill": "Testcontainers", "level": "confirmed", "notes": "używała w ABB"},
                    {"skill": "Event Sourcing", "level": "basic", "notes": "zna koncepty, mało praktyki"},
                ],
                "red_flags": "Oczekuje szybkiej ścieżki kariery — może odejść jeśli nie ma awansu w 12 mies.",
                "personality_notes": "Prep call poszedł bardzo dobrze. Przygotowana, pytała o detal architektury.",
                "readiness_to_change": 5,
                "counteroffer_risk": CounterOfferRisk.medium,
                "closing_strategy": "Przy ofercie wspomnieć o ścieżce do Tech Lead w BNP — to ją mocno interesuje.",
                "overall_impression": 5,
            },
            # Michał Wiśniewski — DevOps (candidates[2])
            {
                "candidate_id": candidates[2].id,
                "job_id": jobs[2].id,
                "author_id": recruiter2.id,
                "screening_type": ScreeningType.initial_screening,
                "motivation_primary": MotivationType.technology,
                "motivation_secondary": MotivationType.project,
                "salary_expectation": 26000,
                "salary_currency": "PLN",
                "salary_negotiable": False,
                "verified_skills": [
                    {"skill": "Kubernetes", "level": "confirmed", "notes": "certyfikat CKA, 5 lat prod"},
                    {"skill": "Azure", "level": "confirmed", "notes": "Solutions Architect Expert cert"},
                    {"skill": "Terraform", "level": "confirmed", "notes": "IaC od 5 lat"},
                    {"skill": "AWS", "level": "basic", "notes": "zna, ale Azure preferuje"},
                ],
                "red_flags": "Stawka 26k to twarda cena — nie zejdzie. Ryzyko jeśli klient chce oszczędzać.",
                "personality_notes": "Analityczny, spokojny. Lubi nieduże firmy lub projekty z prawdziwym wpływem na architekturę.",
                "readiness_to_change": 3,
                "counteroffer_risk": CounterOfferRisk.medium,
                "closing_strategy": "Projekt Azure dla Pekao będzie fit jeśli podkreślimy skalowalność i nowoczesny stack.",
                "overall_impression": 5,
            },
            # Tomasz Dąbrowski — Data (candidates[4])
            {
                "candidate_id": candidates[4].id,
                "job_id": jobs[4].id,
                "author_id": recruiter3.id,
                "screening_type": ScreeningType.initial_screening,
                "motivation_primary": MotivationType.project,
                "motivation_secondary": MotivationType.technology,
                "salary_expectation": 22000,
                "salary_currency": "PLN",
                "salary_negotiable": True,
                "verified_skills": [
                    {"skill": "Python", "level": "confirmed", "notes": "expert 7 lat"},
                    {"skill": "Apache Airflow", "level": "confirmed", "notes": "4 lata prod, custom operators"},
                    {"skill": "dbt", "level": "confirmed", "notes": "3 lata, modeling zaawansowany"},
                    {"skill": "BigQuery", "level": "confirmed", "notes": "Allegro env, dobre optymalizacje"},
                    {"skill": "Spark", "level": "basic", "notes": "zna, używał mniej regularnie"},
                ],
                "red_flags": None,
                "personality_notes": "Pasjonat data engineeringu, aktywny na konferencjach. Bardzo dobry fit dla Cognism.",
                "readiness_to_change": 4,
                "counteroffer_risk": CounterOfferRisk.low,
                "closing_strategy": "Cognism to produkt data-driven — to go argument. Budżet elastyczny do 24k.",
                "overall_impression": 5,
            },
            # Paweł Kaczmarek — Tech Lead (candidates[8])
            {
                "candidate_id": candidates[8].id,
                "job_id": jobs[8].id,
                "author_id": recruiter1.id,
                "screening_type": ScreeningType.initial_screening,
                "motivation_primary": MotivationType.project,
                "motivation_secondary": MotivationType.growth,
                "salary_expectation": 30000,
                "salary_currency": "PLN",
                "salary_negotiable": True,
                "verified_skills": [
                    {"skill": "Java", "level": "confirmed", "notes": "12 lat, expert bezsprzecznie"},
                    {"skill": "Microservices", "level": "confirmed", "notes": "7 lat, real world"},
                    {"skill": "Kafka", "level": "confirmed", "notes": "event streaming od 6 lat"},
                    {"skill": "Kubernetes", "level": "confirmed", "notes": "prod K8s 5 lat"},
                ],
                "red_flags": "60 dni wypowiedzenia — może być za długo dla klienta. Sprawdzić elastyczność Pekao.",
                "personality_notes": "Bardzo dojrzały zawodowo. Myśli strategicznie, zna się na biznesowych aspektach architektury.",
                "readiness_to_change": 4,
                "counteroffer_risk": CounterOfferRisk.high,
                "closing_strategy": "Najlepsza karta: duże projekty strategiczne + możliwość kształtowania architektury od zera. Stawka 32-35k do negocjacji.",
                "overall_impression": 5,
            },
            # Paweł Kaczmarek — prep call (candidates[8])
            {
                "candidate_id": candidates[8].id,
                "job_id": jobs[8].id,
                "author_id": admin_user.id,
                "screening_type": ScreeningType.prep_call,
                "motivation_primary": MotivationType.project,
                "motivation_secondary": MotivationType.stability,
                "salary_expectation": 32000,
                "salary_currency": "PLN",
                "salary_negotiable": False,
                "verified_skills": [
                    {"skill": "Java", "level": "confirmed", "notes": "expert, prowadził 15-os zespół"},
                    {"skill": "Event Sourcing", "level": "confirmed", "notes": "wdrażał od zera w PKO BP"},
                    {"skill": "DDD", "level": "confirmed", "notes": "aktywnie stosuje, zna patterns"},
                ],
                "red_flags": "Wysoki counteroffer risk — obecny pracodawca chce go zatrzymać. Sii oferuje kontratak.",
                "personality_notes": "Bardzo poważnie podchodzi do architektury — będzie wymagał realnego wpływu w projekcie. Jeśli dostanie tę rolę, zostanie na lata.",
                "readiness_to_change": 4,
                "counteroffer_risk": CounterOfferRisk.high,
                "closing_strategy": "Kluczowe: zagwarantować mu tytuł Lead Architekt i wpływ decyzyjny. 32k to minimum.",
                "overall_impression": 5,
            },
            # Joanna Lewandowska — React (candidates[5])
            {
                "candidate_id": candidates[5].id,
                "job_id": jobs[5].id,
                "author_id": recruiter3.id,
                "screening_type": ScreeningType.initial_screening,
                "motivation_primary": MotivationType.work_mode,
                "motivation_secondary": MotivationType.project,
                "salary_expectation": 18000,
                "salary_currency": "PLN",
                "salary_negotiable": True,
                "verified_skills": [
                    {"skill": "React", "level": "confirmed", "notes": "expert, 5 lat"},
                    {"skill": "TypeScript", "level": "confirmed", "notes": "expert, solidna"},
                    {"skill": "Redux Toolkit", "level": "confirmed", "notes": "4 lata prod"},
                    {"skill": "GraphQL", "level": "basic", "notes": "zna, używała mniej"},
                ],
                "red_flags": None,
                "personality_notes": "Priorytet: praca zdalna. Gdańsk — nieakceptowalna podróż. Projekt musi być full remote lub bardzo elastyczny.",
                "readiness_to_change": 5,
                "counteroffer_risk": CounterOfferRisk.low,
                "closing_strategy": "Podkreślić remote-first w Asseco dla tego projektu. Stawka 18-20k w zasięgu.",
                "overall_impression": 4,
            },
        ]

        for sd in screening_data:
            s = ScreeningNote(**sd)
            db.add(s)
        await db.flush()
        print(f"  Created {len(screening_data)} screening notes")

        # ─────────────────────────────────────────────────────────────────────
        # V3: Contacts — osoby kontaktowe w firmach
        # ─────────────────────────────────────────────────────────────────────
        contacts_data = [
            # Nordea — 3 contacts
            {
                "client_id": clients[0].id,
                "name": "Katarzyna Wiśniewska",
                "email": "k.wisniewska@nordea.com",
                "phone": "+48 22 521 1100",
                "position": "IT Recruitment Business Partner",
                "department": "HR / Talent Acquisition",
                "is_decision_maker": True,
                "notes": "Główny punkt kontaktowy. Decyduje o nowych pozycjach i budżetach. Preferuje kontakt mailowy + Teams. Najlepsza pora: 10-12.",
            },
            {
                "client_id": clients[0].id,
                "name": "Lars Eriksson",
                "email": "lars.eriksson@nordea.com",
                "phone": "+46 8 614 7800",
                "position": "Head of Digital Banking Technology",
                "department": "IT / Engineering",
                "is_decision_maker": True,
                "notes": "Decydent techniczny. Szwed, rozmowy po angielsku. Ocenia kandydatów podczas technical interview.",
            },
            {
                "client_id": clients[0].id,
                "name": "Marta Kowalczuk",
                "email": "m.kowalczuk@nordea.com",
                "phone": "+48 22 521 1200",
                "position": "Senior HR Specialist",
                "department": "HR",
                "is_decision_maker": False,
                "notes": "Koordynuje spotkania i formalności. Dobry kontakt do logistyki procesów.",
            },
            # BNP Paribas — 3 contacts
            {
                "client_id": clients[1].id,
                "name": "Piotr Jankowski",
                "email": "piotr.jankowski@bnpparibas.pl",
                "phone": "+48 22 566 9001",
                "position": "IT Procurement Manager",
                "department": "IT / Procurement",
                "is_decision_maker": True,
                "notes": "Negocjuje warunki umów. Twardy negocjator — warto mieć przygotowane porównanie stawek rynkowych. Preferuje spotkania face-to-face.",
            },
            {
                "client_id": clients[1].id,
                "name": "Dorota Jabłońska",
                "email": "d.jablonska@bnpparibas.pl",
                "phone": "+48 22 566 9002",
                "position": "Senior Technical Recruiter",
                "department": "HR",
                "is_decision_maker": False,
                "notes": "Techniczna rekruterka od strony BNP. Weryfikuje CV przed przesłaniem do menedżera. Dobry kontakt roboczych.",
            },
            {
                "client_id": clients[1].id,
                "name": "Tomasz Dąbkowski",
                "email": "t.dabkowski@bnpparibas.pl",
                "phone": "+48 22 566 9100",
                "position": "Head of Data Platform",
                "department": "IT / Data Engineering",
                "is_decision_maker": True,
                "notes": "Decydent dla projektu Data Engineering Squad. Szuka doświadczonych inżynierów Python/Spark. Znajomość Confluent Kafka mile widziana.",
            },
            # Ferro — 2 contacts
            {
                "client_id": clients[3].id,
                "name": "Marcin Dąbrowski",
                "email": "m.dabrowski@ferro.pl",
                "phone": "+48 33 844 1001",
                "position": "IT Director",
                "department": "IT",
                "is_decision_maker": True,
                "notes": "Jedyny decydent w Ferro po stronie IT. Nastawiony na jakość i terminowość. Mniej zainteresowany stawkami niż efektem.",
            },
            {
                "client_id": clients[3].id,
                "name": "Alicja Kowalska",
                "email": "a.kowalska@ferro.pl",
                "phone": "+48 33 844 1002",
                "position": "HR Specialist",
                "department": "HR",
                "is_decision_maker": False,
                "notes": "Koordinuje rekrutacje, zbiera CV. Nie ma wpływu decyzyjnego — wszystko idzie do Marcina D.",
            },
            # Cognism — 2 contacts
            {
                "client_id": clients[4].id,
                "name": "Sarah Mitchell",
                "email": "s.mitchell@cognism.com",
                "phone": "+44 20 3988 7401",
                "position": "Head of Engineering",
                "department": "Engineering",
                "is_decision_maker": True,
                "notes": "Decydentka techniczna w Cognism. Mówi po angielsku, rozmowy teams. Bardzo konkretna — oczekuje od razu profili pasujących do JD.",
            },
            {
                "client_id": clients[4].id,
                "name": "James Cooper",
                "email": "j.cooper@cognism.com",
                "phone": "+44 20 3988 7402",
                "position": "Talent Acquisition Partner",
                "department": "People & Culture",
                "is_decision_maker": False,
                "notes": "TA partner — weryfikuje formalne warunki. Dobry do eskalacji jeśli process się blokuje.",
            },
        ]

        for cd in contacts_data:
            c = Contact(**cd)
            db.add(c)
        await db.flush()
        print(f"  Created {len(contacts_data)} contacts")

        # ── TALENT POOLS (v4) ──────────────────────────────────────────────
        admin_user = users[0]  # Artur

        talent_pools_data = [
            {
                "name": "Senior Angular",
                "description": "Seniorzy Angular — gotowi do rozmów z Nordea i BNP. Min. 5 lat w Angular 10+.",
                "criteria": {"technology": "Angular", "seniority": "senior", "min_years": 5},
            },
            {
                "name": "DevOps Engineers",
                "description": "Inżynierowie DevOps/Cloud — Kubernetes, Terraform, Azure/AWS. Dla projektów infrastrukturalnych.",
                "criteria": {"technology": "DevOps", "cloud": ["Azure", "AWS"], "skills": ["Kubernetes", "Terraform"]},
            },
            {
                "name": "QA Automation",
                "description": "Specjaliści QA Automation — Selenium, Playwright, Cypress. Dla projektów wymagających automatyzacji testów.",
                "criteria": {"role": "QA", "automation": True, "skills": ["Selenium", "Playwright", "Cypress"]},
            },
        ]

        talent_pool_objects = []
        for tp_data in talent_pools_data:
            tp = TalentPool(
                name=tp_data["name"],
                description=tp_data["description"],
                criteria=tp_data["criteria"],
                created_by=admin_user.id,
            )
            db.add(tp)
            talent_pool_objects.append(tp)
        await db.flush()

        # Distribute candidates across pools
        # Pool 0: Senior Angular — Frontend/Angular candidates
        # Pool 1: DevOps Engineers — DevOps candidates
        # Pool 2: QA Automation — QA candidates
        pool_assignments = []
        for i, candidate in enumerate(candidates):
            category = (candidate.competence_category or "").lower()
            tags = [t.lower() for t in (candidate.tags or [])] if isinstance(candidate.tags, list) else []
            skills_names = [
                s.get("name", "").lower() if isinstance(s, dict) else s.lower()
                for s in (candidate.skills or [])
            ] if isinstance(candidate.skills, list) else []

            all_text = " ".join([category] + tags + skills_names)

            assigned_pools = []
            if any(kw in all_text for kw in ["angular", "frontend", "react", "vue", "javascript", "typescript"]):
                assigned_pools.append(0)  # Senior Angular
            if any(kw in all_text for kw in ["devops", "kubernetes", "docker", "terraform", "cloud", "azure", "aws", "ci/cd"]):
                assigned_pools.append(1)  # DevOps
            if any(kw in all_text for kw in ["qa", "testing", "selenium", "playwright", "cypress", "test"]):
                assigned_pools.append(2)  # QA Automation

            # Fallback — distribute remaining by index
            if not assigned_pools:
                assigned_pools.append(i % 3)

            pool_assignments.append((candidate, assigned_pools))

        membership_count = 0
        for candidate, pool_indices in pool_assignments:
            for pool_idx in pool_indices[:2]:  # max 2 pools per candidate
                membership = TalentPoolMembership(
                    talent_pool_id=talent_pool_objects[pool_idx].id,
                    candidate_id=candidate.id,
                    added_by=admin_user.id,
                )
                db.add(membership)
                membership_count += 1
        await db.flush()

        print(f"  Created {len(talent_pool_objects)} talent pools with {membership_count} memberships (v4)")

        await db.commit()
        print("\n✅ Seed v4 completed successfully!")
        print(f"   Admin login: artur@b2bnet.pl / {_DEMO_PWD}")
        print(f"   DL login:    olaf@b2bnet.pl / {_DEMO_PWD} (Delivery Lead)")
        print(f"   Recruiter:   marta@b2bnet.pl / {_DEMO_PWD}")
        print(f"   Sourcer:     tomasz@b2bnet.pl / {_DEMO_PWD}")
        print(f"   Users: {len(users)}, Clients: {len(clients)}, Jobs: {len(jobs)}, Candidates: {len(candidates)}")
        print(f"   Pipeline stages: {len(stages_to_create)}, Contracts: {len(contracts_data)}")
        print(f"   User activities: {len(user_activities_data)}, System activities: {len(activities_list)}")
        print(f"   Email templates: {len(email_templates_data)}")
        print(f"   V3: Knowledge: {len(knowledge_data)}, Screenings: {len(screening_data)}")
        print(f"   V3: Contacts: {len(contacts_data)}")
        print(f"   V4: Talent Pools: {len(talent_pool_objects)}, Memberships: {membership_count}")

    await engine.dispose()


async def seed_extended():
    """
    Extended seed data — adds 20 more candidates, 5 more jobs, 30 pipeline entries,
    5 contracts, 50 activities, and 10 calendar events.
    Idempotent: checks by email before creating candidates.
    """
    from app.models.calendar_event import CalendarEvent, EventType, EventStatus

    engine = create_async_engine(DATABASE_URL, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        # Check if base seed ran
        result = await db.execute(select(User).where(User.email == "artur@b2bnet.pl"))
        admin_user = result.scalar_one_or_none()
        if not admin_user:
            print("Base seed not found — run seed() first.")
            await engine.dispose()
            return

        # Load existing users
        result = await db.execute(select(User))
        all_users = result.scalars().all()
        users_by_email = {u.email: u for u in all_users}
        recruiter1 = users_by_email["olaf@b2bnet.pl"]
        recruiter2 = users_by_email["marta@b2bnet.pl"]
        recruiter3 = users_by_email["tomasz@b2bnet.pl"]
        dom_user = users_by_email["dominik@b2bnet.pl"]

        # Load existing clients
        result = await db.execute(select(Client))
        all_clients = result.scalars().all()
        clients_by_name = {c.name: c for c in all_clients}

        # Load existing jobs
        result = await db.execute(select(Job))
        existing_jobs = result.scalars().all()

        print("Seeding extended data...")

        # ── 5 NEW JOBS ──────────────────────────────────────────────────────
        new_jobs_data = [
            {
                "title": "Cloud Architect",
                "description": "Projektowanie i wdrożenie architektury multi-cloud dla systemu bankowości korporacyjnej Nordea. Stack: Azure + AWS, Terraform, Kubernetes.",
                "requirements": "Azure Solutions Architect / AWS SA Pro, Terraform, Kubernetes, 6+ lat cloud, doświadczenie w sektorze bankowym",
                "location": "Warszawa",
                "salary_min": 22000,
                "salary_max": 32000,
                "remote_policy": RemotePolicy.hybrid,
                "status": JobStatus.published,
                "priority": JobPriority.urgent,
                "recruitment_type": RecruitmentType.body_leasing,
                "deadline": date.today() + timedelta(days=18),
                "client_id": clients_by_name["Nordea Bank AB"].id,
                "recruiter_id": recruiter1.id,
            },
            {
                "title": "QA Lead",
                "description": "Zarządzanie zespołem 6 QA inżynierów w projekcie transformacji digitalnej BNP Paribas. Odpowiedzialność za strategię testów, automatyzację i jakość dostarczania.",
                "requirements": "ISTQB Advanced, Selenium/Cypress/Playwright, CI/CD, min. 2 lata jako QA Lead, bankowość lub fintech mile widziane",
                "location": "Warszawa",
                "salary_min": 18000,
                "salary_max": 26000,
                "remote_policy": RemotePolicy.hybrid,
                "status": JobStatus.published,
                "priority": JobPriority.high,
                "recruitment_type": RecruitmentType.body_leasing,
                "deadline": date.today() + timedelta(days=28),
                "client_id": clients_by_name["BNP Paribas Bank Polska"].id,
                "recruiter_id": recruiter2.id,
            },
            {
                "title": "Data Engineer",
                "description": "Budowa nowoczesnej platformy danych dla ING Bank Śląski. Migracja z legacy Hadoop do Databricks + Snowflake. Tworzenie pipeline'ów ETL i Data Lakehouse.",
                "requirements": "Python, PySpark, Databricks, Snowflake lub dbt, Airflow, 4+ lata Data Engineering",
                "location": "Katowice / Zdalnie",
                "salary_min": 18000,
                "salary_max": 26000,
                "remote_policy": RemotePolicy.hybrid,
                "status": JobStatus.published,
                "priority": JobPriority.high,
                "recruitment_type": RecruitmentType.body_leasing,
                "deadline": date.today() + timedelta(days=35),
                "client_id": clients_by_name["ING Bank Śląski"].id,
                "recruiter_id": recruiter3.id,
            },
            {
                "title": "Security Analyst",
                "description": "Analityk bezpieczeństwa IT dla Asseco Poland — monitorowanie zagrożeń, audyty bezpieczeństwa, SIEM, zarządzanie incydentami. Projekty dla klientów sektora publicznego.",
                "requirements": "CISSP / CEH / OSCP (min. jeden), SIEM (Splunk lub QRadar), pentest, 3+ lata cybersecurity",
                "location": "Rzeszów / Kraków",
                "salary_min": 15000,
                "salary_max": 22000,
                "remote_policy": RemotePolicy.onsite,
                "status": JobStatus.published,
                "priority": JobPriority.medium,
                "recruitment_type": RecruitmentType.tender,
                "deadline": date.today() + timedelta(days=45),
                "client_id": clients_by_name["Asseco Poland S.A."].id,
                "recruiter_id": recruiter2.id,
            },
            {
                "title": "Scrum Master",
                "description": "Scrum Master dla nowego produktu cyfrowego Bank Pekao SA — e-banking next gen. Praca z 3 cross-funkcjonalnymi teamami, framework SAFe.",
                "requirements": "PSM II lub CSM, SAFe Scrum Master cert, 4+ lata jako SM, doświadczenie w fintech lub bankowości",
                "location": "Warszawa",
                "salary_min": 16000,
                "salary_max": 22000,
                "remote_policy": RemotePolicy.hybrid,
                "status": JobStatus.published,
                "priority": JobPriority.medium,
                "recruitment_type": RecruitmentType.sales_project,
                "deadline": date.today() + timedelta(days=50),
                "client_id": clients_by_name["Bank Pekao SA"].id,
                "recruiter_id": recruiter1.id,
            },
        ]

        new_jobs = []
        for jd in new_jobs_data:
            j = Job(**jd, created_by=admin_user.id)
            db.add(j)
            new_jobs.append(j)
        await db.flush()
        print(f"  Created {len(new_jobs)} new jobs")

        # ── 20 NEW CANDIDATES (idempotent by email) ─────────────────────────
        new_candidates_data = [
            {
                "name": "Tomasz", "lastname": "Wiśniewski",
                "email": "t.wisniewski.cloud@gmail.com", "phone": "+48 700 100 201",
                "location": "Warszawa", "linkedin": "linkedin.com/in/tomasz-wisniewski-cloud",
                "salary_expectation": 28000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=30),
                "source": "linkedin",
                "competence_category": "DevOps/Cloud",
                "ai_summary": "Doświadczony Cloud Architect z 8-letnim stażem w środowiskach Azure i AWS. Pracował jako starszy architekt w Orange Polska przy dużych projektach transformacji chmurowej. Posiada certyfikaty Azure Solutions Architect Expert oraz AWS Solutions Architect Professional. Poszukuje ambitnych projektów enterprise w sektorze bankowym.",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": {"technologies": ["Azure", "AWS", "Terraform", "Kubernetes", "Helm"], "level": "senior"},
                "tags": ["cloud-architect", "azure", "aws", "senior", "b2b"],
            },
            {
                "name": "Karolina", "lastname": "Zielińska",
                "email": "k.zielinska.java@gmail.com", "phone": "+48 700 100 202",
                "location": "Kraków", "linkedin": "linkedin.com/in/karolina-zielinska-java",
                "salary_expectation": 21000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=14),
                "source": "pracuj",
                "competence_category": "Backend",
                "ai_summary": "Senior Java Developer z 7-letnim doświadczeniem w systemach finansowych. W Capgemini rozwijała platformę płatniczą obsługującą transakcje dla 5 banków. Biegła w Spring Boot 3, Kafka i architekturze mikroserwisowej. Szuka nowych wyzwań technicznych w sektorze fintech lub bankowości.",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": {"technologies": ["Java", "Spring Boot", "Kafka", "PostgreSQL", "Docker"], "level": "senior"},
                "tags": ["senior", "java", "backend", "fintech", "b2b"],
            },
            {
                "name": "Przemysław", "lastname": "Kowalczyk",
                "email": "p.kowalczyk.data@gmail.com", "phone": "+48 700 100 203",
                "location": "Warszawa",
                "salary_expectation": 24000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=7),
                "source": "linkedin",
                "competence_category": "Data Engineering",
                "ai_summary": "Data Engineer z 6-letnim doświadczeniem w budowaniu platform danych. W Booking.com tworzył skalowalne pipeline'y na AWS EMR i Databricks dla danych e-commerce. Certyfikowany Databricks Associate i AWS Data Analytics. Pasjonuje go optymalizacja zapytań Spark i architektura Data Lakehouse.",
                "notice_period": 14,
                "status": CandidateStatus.active,
                "skills": {"technologies": ["Python", "PySpark", "Databricks", "Snowflake", "dbt", "Airflow"], "level": "senior"},
                "tags": ["data-engineering", "python", "databricks", "spark", "senior"],
            },
            {
                "name": "Natalia", "lastname": "Wiśniewska",
                "email": "n.wisniewska.qa@gmail.com", "phone": "+48 700 100 204",
                "location": "Wrocław",
                "salary_expectation": 20000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=21),
                "source": "linkedin",
                "competence_category": "QA",
                "ai_summary": "QA Lead z 7-letnim doświadczeniem w testowaniu automatycznym i zarządzaniu zespołami QA. W Accenture prowadziła team 8 inżynierów jakości dla klientów bankowych. Ekspercka wiedza z Selenium, Playwright i Cypress. Certyfikat ISTQB Advanced Level Test Manager.",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": {"technologies": ["Selenium", "Playwright", "Cypress", "Python", "Java", "Jenkins"], "level": "lead"},
                "tags": ["qa-lead", "qa", "automation", "selenium", "playwright", "senior"],
            },
            {
                "name": "Mateusz", "lastname": "Dąbrowski",
                "email": "m.dabrowski.sec@gmail.com", "phone": "+48 700 100 205",
                "location": "Kraków",
                "salary_expectation": 19000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=14),
                "source": "referral",
                "competence_category": "Security",
                "ai_summary": "Cybersecurity Analyst z 5-letnim doświadczeniem w monitorowaniu zagrożeń i analizie incydentów. W CERT Polska i następnie w PWC uczestniczył w reagowaniu na ataki APT i red team exercises. Certyfikaty CEH i OSCP. Znajomość Splunk, QRadar i technik ofensywnych.",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": {"technologies": ["Splunk", "QRadar", "Python", "SIEM", "Pentest", "Wireshark"], "level": "senior"},
                "tags": ["security", "cybersecurity", "siem", "pentest", "senior"],
            },
            {
                "name": "Aleksandra", "lastname": "Nowak",
                "email": "a.nowak.sm@gmail.com", "phone": "+48 700 100 206",
                "location": "Warszawa",
                "salary_expectation": 19000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=14),
                "source": "linkedin",
                "competence_category": "Agile/PM",
                "ai_summary": "Scrum Master z 6-letnim doświadczeniem w dużych transformacjach agile. W Santander Bank prowadziła jednocześnie 4 zespoły scrum w środowisku SAFe. Certyfikat SAFe 6.0 Program Consultant oraz PSM II. Komunikatywna, doskonale radzi sobie z konfliktami i eskalacjami.",
                "notice_period": 14,
                "status": CandidateStatus.active,
                "skills": {"technologies": ["Scrum", "SAFe", "Jira", "Confluence", "Azure DevOps"], "level": "senior"},
                "tags": ["scrum-master", "safe", "agile", "senior"],
            },
            {
                "name": "Bartłomiej", "lastname": "Nowicki",
                "email": "b.nowicki.java@gmail.com", "phone": "+48 700 100 207",
                "location": "Poznań",
                "salary_expectation": 23000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=21),
                "source": "pracuj",
                "competence_category": "Backend",
                "ai_summary": "Senior Java Developer z 8-letnim doświadczeniem w systemach enterprise. W ING Tech pracował przy core banking systemach obsługujących 4 miliony klientów. Ekspert Spring Boot 3, Kafka, Event Sourcing i CQRS. Zna architekturę hexagonalną i DDD w praktyce.",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": {"technologies": ["Java", "Spring Boot", "Kafka", "CQRS", "Event Sourcing", "PostgreSQL"], "level": "senior"},
                "tags": ["senior", "java", "backend", "ddd", "cqrs", "b2b"],
            },
            {
                "name": "Monika", "lastname": "Kowalska",
                "email": "m.kowalska.cloud@gmail.com", "phone": "+48 700 100 208",
                "location": "Warszawa",
                "salary_expectation": 26000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=30),
                "source": "linkedin",
                "competence_category": "DevOps/Cloud",
                "ai_summary": "Senior DevOps Engineer z certyfikatem CKA i Azure DevOps Expert. 6 lat w Microsofcie przy infrastrukturze platformy Azure dla klientów finansowych. Biegła w Terraform, Helm, ArgoCD i GitOps. Preferuje środowiska enterprise z realnym wpływem na architekturę.",
                "notice_period": 60,
                "status": CandidateStatus.passive,
                "skills": {"technologies": ["Kubernetes", "Azure", "Terraform", "ArgoCD", "Helm", "GitOps"], "level": "senior"},
                "tags": ["devops", "cloud", "azure", "kubernetes", "gitops", "senior"],
            },
            {
                "name": "Piotr", "lastname": "Mazurek",
                "email": "p.mazurek.react@gmail.com", "phone": "+48 700 100 209",
                "location": "Gdańsk",
                "salary_expectation": 18000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=7),
                "source": "jjit",
                "competence_category": "Frontend",
                "ai_summary": "Senior React Developer z 5-letnim doświadczeniem w tworzeniu złożonych SPA. W Grupie Wirtualna Polska budował duże aplikacje React dla milionów użytkowników. Biegły w TypeScript, Redux Toolkit, React Query i micro-frontends. Aktywny contributor open source.",
                "notice_period": 14,
                "status": CandidateStatus.active,
                "skills": {"technologies": ["React", "TypeScript", "Redux Toolkit", "React Query", "Jest", "Webpack"], "level": "senior"},
                "tags": ["frontend", "react", "typescript", "senior"],
            },
            {
                "name": "Agata", "lastname": "Wróbel",
                "email": "a.wrobel.data@gmail.com", "phone": "+48 700 100 210",
                "location": "Katowice",
                "salary_expectation": 20000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=14),
                "source": "pracuj",
                "competence_category": "Data Engineering",
                "ai_summary": "Data Engineer z ING Bank Śląski z 5-letnim doświadczeniem w pipeline'ach finansowych. Budowała systemy raportowania regulacyjnego (IFRS 9, AnaCredit) w Pythonie i Spark. Certyfikat Databricks i Google Cloud Professional Data Engineer. Szuka nowego projektu w obszarze finansów lub e-commerce.",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": {"technologies": ["Python", "PySpark", "Google BigQuery", "dbt", "Airflow", "SQL"], "level": "mid-senior"},
                "tags": ["data-engineering", "python", "bigquery", "gcp"],
            },
            {
                "name": "Łukasz", "lastname": "Kamecki",
                "email": "l.kamecki.sec@gmail.com", "phone": "+48 700 100 211",
                "location": "Warszawa",
                "salary_expectation": 18000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=14),
                "source": "linkedin",
                "competence_category": "Security",
                "ai_summary": "Security Engineer z 4-letnim doświadczeniem w bezpieczeństwie aplikacji i infrastruktury. W Ryanair Security Team wdrażał systemy SIEM i zarządzał incydentami bezpieczeństwa. Specjalizuje się w security for DevOps (DevSecOps), hardening Kubernetes i analizie podatności.",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": {"technologies": ["Splunk", "Kubernetes security", "DevSecOps", "Python", "Nessus", "OWASP"], "level": "mid-senior"},
                "tags": ["security", "devsecops", "kubernetes", "mid"],
            },
            {
                "name": "Patrycja", "lastname": "Lewandowska",
                "email": "p.lewandowska.fe@gmail.com", "phone": "+48 700 100 212",
                "location": "Wrocław",
                "salary_expectation": 17000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=14),
                "source": "manual",
                "competence_category": "Frontend",
                "ai_summary": "Frontend Developer z 4-letnim doświadczeniem w Angular i React. W TomTom budowała interfejsy map dla produktów B2B. Płynna znajomość RxJS, NgRx i Storybook. Ceni projekty z dobrą kulturą kodu i code review.",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": {"technologies": ["Angular", "React", "TypeScript", "RxJS", "NgRx", "Storybook"], "level": "mid"},
                "tags": ["frontend", "angular", "react", "mid"],
            },
            {
                "name": "Robert", "lastname": "Stępień",
                "email": "r.stepien.java@gmail.com", "phone": "+48 700 100 213",
                "location": "Łódź",
                "salary_expectation": 19000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=21),
                "source": "referral",
                "competence_category": "Backend",
                "ai_summary": "Java Developer z 6-letnim doświadczeniem, specjalizacja w systemach płatniczych. W Finastra implementował protokoły ISO 20022 i SWIFT. Zna dobrze Spring Cloud, Kafka i systemy transakcyjne wysokiej dostępności. Otwarty na nowe projekty bankowe jako senior developer.",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": {"technologies": ["Java", "Spring Cloud", "Kafka", "ISO 20022", "PostgreSQL", "Redis"], "level": "senior"},
                "tags": ["senior", "java", "backend", "payments", "fintech"],
            },
            {
                "name": "Joanna", "lastname": "Kowalska",
                "email": "j.kowalska.devops@gmail.com", "phone": "+48 700 100 214",
                "location": "Warszawa",
                "salary_expectation": 22000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=14),
                "source": "linkedin",
                "competence_category": "DevOps/Cloud",
                "ai_summary": "DevOps Engineer z 5-letnim doświadczeniem w AWS i GitOps. W Allegro Tech zarządzała infrastrukturą EKS obsługującą setki mikroserwisów. Certyfikat AWS Solutions Architect i CKA. Biegła w Terraform, GitHub Actions i observability (Grafana, Prometheus).",
                "notice_period": 14,
                "status": CandidateStatus.active,
                "skills": {"technologies": ["AWS", "Kubernetes", "Terraform", "GitHub Actions", "Prometheus", "Grafana"], "level": "senior"},
                "tags": ["devops", "aws", "kubernetes", "cloud", "senior"],
            },
            {
                "name": "Marek", "lastname": "Ziółkowski",
                "email": "m.ziolkowski.qa@gmail.com", "phone": "+48 700 100 215",
                "location": "Gdańsk",
                "salary_expectation": 16000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=7),
                "source": "jjit",
                "competence_category": "QA",
                "ai_summary": "QA Automation Engineer z 4-letnim doświadczeniem w testowaniu backendowym i API. W Poczcie Polskiej tworzył frameworki testowe w Pythonie dla systemów e-commerce. Specjalizuje się w Playwright, REST API testing i testach integracyjnych w CI/CD.",
                "notice_period": 14,
                "status": CandidateStatus.active,
                "skills": {"technologies": ["Playwright", "Python", "REST API", "Postman", "Jenkins", "Docker"], "level": "mid"},
                "tags": ["qa", "automation", "playwright", "api-testing"],
            },
            {
                "name": "Agnieszka", "lastname": "Dąbrowska",
                "email": "a.dabrowska.sm@gmail.com", "phone": "+48 700 100 216",
                "location": "Kraków",
                "salary_expectation": 17000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=14),
                "source": "pracuj",
                "competence_category": "Agile/PM",
                "ai_summary": "Scrum Master z 5-letnim doświadczeniem w firmach produktowych i consultingu. W Sollers Consulting prowadziła zwinne projekty dla europejskich ubezpieczycieli. Certyfikat PSM II i SPC SAFe. Doświadczenie w onboardingu nowych zespołów i szkoleniach z agile.",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": {"technologies": ["Scrum", "SAFe", "Jira", "Confluence", "Miro", "Retrium"], "level": "senior"},
                "tags": ["scrum-master", "safe", "agile", "senior"],
            },
            {
                "name": "Wojciech", "lastname": "Mazur",
                "email": "w.mazur.net@gmail.com", "phone": "+48 700 100 217",
                "location": "Warszawa",
                "salary_expectation": 22000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=21),
                "source": "linkedin",
                "competence_category": "Backend",
                "ai_summary": ".NET Developer z 7-letnim doświadczeniem w systemach enterprise. W Infosys tworzył rozwiązania dla klientów ubezpieczeniowych w .NET 8 i Azure. Biegły w C#, ASP.NET Core, Entity Framework i Azure Service Bus. Szuka projektu gdzie może rozwijać się jako tech lead.",
                "notice_period": 30,
                "status": CandidateStatus.active,
                "skills": {"technologies": [".NET", "C#", "ASP.NET Core", "Azure Service Bus", "Entity Framework", "SQL Server"], "level": "senior"},
                "tags": ["dotnet", "csharp", "backend", "azure", "senior"],
            },
            {
                "name": "Kamil", "lastname": "Brzozowski",
                "email": "k.brzozowski.ml@gmail.com", "phone": "+48 700 100 218",
                "location": "Warszawa",
                "salary_expectation": 25000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=30),
                "source": "referral",
                "competence_category": "Data Engineering",
                "ai_summary": "ML Engineer i Data Engineer z doświadczeniem w budowaniu produktów AI w sektorze finansowym. W mBank tworzył modele scoringowe i infrastrukturę MLOps w Kubeflow. Zna dobrze Python, MLflow, Feature Store i architekturę Data Lakehouse. Pasjonat LLMOps.",
                "notice_period": 30,
                "status": CandidateStatus.passive,
                "skills": {"technologies": ["Python", "MLflow", "Kubeflow", "Databricks", "Spark", "Feature Store"], "level": "senior"},
                "tags": ["ml-engineer", "mlops", "data-engineering", "python", "senior"],
            },
            {
                "name": "Izabela", "lastname": "Wierzbicka",
                "email": "i.wierzbicka.fe@gmail.com", "phone": "+48 700 100 219",
                "location": "Poznań",
                "salary_expectation": 15000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=7),
                "source": "pracuj",
                "competence_category": "Frontend",
                "ai_summary": "Mid-level Angular Developer z 3-letnim doświadczeniem. W Comarch rozwijała aplikacje do zarządzania polisami ubezpieczeniowymi. Solidna znajomość Angular 14+, NgRx i RxJS. Aktywnie poszerza wiedzę o micro-frontend architecture i testy e2e w Cypress.",
                "notice_period": 14,
                "status": CandidateStatus.active,
                "skills": {"technologies": ["Angular", "TypeScript", "NgRx", "RxJS", "Cypress", "SCSS"], "level": "mid"},
                "tags": ["frontend", "angular", "mid"],
            },
            {
                "name": "Sebastian", "lastname": "Ostrowski",
                "email": "s.ostrowski.java@gmail.com", "phone": "+48 700 100 220",
                "location": "Wrocław",
                "salary_expectation": 14000, "salary_currency": "PLN",
                "availability_date": date.today() + timedelta(days=7),
                "source": "jjit",
                "competence_category": "Backend",
                "ai_summary": "Java Developer z 2-letnim komercyjnym doświadczeniem, aktywnie rozwijający się junior. W Sii uczył się od seniorów architektury mikroserwisowej dla klientów bankowych. Zna Spring Boot 3, JUnit 5, REST API i podstawy Kubernetes. Szuka projektu, gdzie może zdobyć doświadczenie produkcyjne.",
                "notice_period": 14,
                "status": CandidateStatus.active,
                "skills": {"technologies": ["Java", "Spring Boot", "JUnit", "REST API", "Git", "Docker"], "level": "junior"},
                "tags": ["java", "backend", "junior"],
            },
        ]

        # Check existing emails and skip duplicates
        result = await db.execute(select(Candidate.email))
        existing_emails = {row[0] for row in result.fetchall()}

        new_candidates = []
        skipped = 0
        for cd in new_candidates_data:
            if cd["email"] in existing_emails:
                skipped += 1
                continue
            c = Candidate(**cd)
            db.add(c)
            new_candidates.append(c)
        await db.flush()
        print(f"  Created {len(new_candidates)} new candidates (skipped {skipped} duplicates)")

        if not new_candidates:
            print("  All new candidates already exist — skipping pipeline, contracts, activities")
            await engine.dispose()
            return

        # ── 30 PIPELINE ENTRIES for new candidates ─────────────────────────
        # Map candidate names for readability
        # new_candidates order: 0=Tomasz W, 1=Karolina Z, 2=Przemysław K, 3=Natalia W (QA Lead), 4=Mateusz D (Sec),
        #                        5=Aleksandra N (SM), 6=Bartłomiej N (Java), 7=Monika K (DevOps), 8=Piotr M (React),
        #                        9=Agata W (Data), 10=Łukasz K (Sec), 11=Patrycja L (FE), 12=Robert S (Java),
        #                        13=Joanna K (DevOps), 14=Marek Z (QA), 15=Agnieszka D (SM), 16=Wojciech M (.NET),
        #                        17=Kamil B (ML), 18=Izabela W (FE), 19=Sebastian O (Java)
        # new_jobs: 0=Cloud Architect, 1=QA Lead, 2=Data Engineer, 3=Security Analyst, 4=Scrum Master
        # existing_jobs indices 0-9 also available

        def safe_cand(idx):
            return new_candidates[idx] if idx < len(new_candidates) else new_candidates[0]

        def safe_job(idx):
            return new_jobs[idx] if idx < len(new_jobs) else new_jobs[0]

        pipeline_entries = [
            # Cloud Architect — Tomasz Wiśniewski (perfect fit)
            (safe_cand(0), safe_job(0), PipelineStage.interview, recruiter1.id, 5),
            # Cloud Architect — Monika Kowalska
            (safe_cand(7), safe_job(0), PipelineStage.screening, recruiter1.id, 4),
            # Cloud Architect — Joanna Kowalska (DevOps)
            (safe_cand(13), safe_job(0), PipelineStage.new, recruiter1.id, None),
            # Cloud Architect — from existing candidates (Aleksandra Michalska = existing index 26)
            # QA Lead — Natalia Wiśniewska
            (safe_cand(3), safe_job(1), PipelineStage.interview, recruiter2.id, 5),
            # QA Lead — Marek Ziółkowski
            (safe_cand(14), safe_job(1), PipelineStage.screening, recruiter2.id, 4),
            # QA Lead — Mateusz Dąbrowski — wrong fit but interviewed
            (safe_cand(4), safe_job(1), PipelineStage.new, recruiter2.id, None),
            # Data Engineer — Przemysław Kowalczyk (excellent fit)
            (safe_cand(2), safe_job(2), PipelineStage.acceptance, recruiter3.id, 5),
            # Data Engineer — Agata Wróbel
            (safe_cand(9), safe_job(2), PipelineStage.interview, recruiter3.id, 4),
            # Data Engineer — Kamil Brzozowski (ML angle)
            (safe_cand(17), safe_job(2), PipelineStage.screening, recruiter3.id, 3),
            # Security Analyst — Mateusz Dąbrowski
            (safe_cand(4), safe_job(3), PipelineStage.interview, recruiter2.id, 5),
            # Security Analyst — Łukasz Kamecki
            (safe_cand(10), safe_job(3), PipelineStage.screening, recruiter2.id, 4),
            # Scrum Master — Aleksandra Nowak (SM specialist)
            (safe_cand(5), safe_job(4), PipelineStage.interview, recruiter1.id, 5),
            # Scrum Master — Agnieszka Dąbrowska
            (safe_cand(15), safe_job(4), PipelineStage.screening, recruiter1.id, 4),
            # Cross-match new candidates to existing jobs
            # Karolina Zielińska → Java Backend Developer (existing job 1)
            (safe_cand(1), existing_jobs[1], PipelineStage.acceptance, recruiter1.id, 5),
            # Bartłomiej Nowicki → Java Backend Developer (existing job 1)
            (safe_cand(6), existing_jobs[1], PipelineStage.screening, recruiter1.id, 4),
            # Robert Stępień → Java Backend Developer (existing job 1)
            (safe_cand(12), existing_jobs[1], PipelineStage.new, recruiter1.id, None),
            # Piotr Mazurek → Senior Angular Developer (existing job 0)
            (safe_cand(8), existing_jobs[0], PipelineStage.interview, recruiter1.id, 4),
            # Patrycja Lewandowska → Senior Angular Developer (existing job 0)
            (safe_cand(11), existing_jobs[0], PipelineStage.screening, recruiter1.id, 3),
            # Izabela Wierzbicka → React Frontend Developer (existing job 5)
            (safe_cand(18), existing_jobs[5], PipelineStage.new, recruiter3.id, None),
            # Sebastian Ostrowski → Java Backend (junior level) existing job 1
            (safe_cand(19), existing_jobs[1], PipelineStage.screening, recruiter2.id, 2),
            # Tomasz Wiśniewski → DevOps Cloud Engineer (existing job 2 - also fits)
            (safe_cand(0), existing_jobs[2], PipelineStage.screening, recruiter2.id, 4),
            # Joanna Kowalska → DevOps Cloud Engineer (existing job 2)
            (safe_cand(13), existing_jobs[2], PipelineStage.interview, recruiter2.id, 5),
            # Agata Wróbel → Python Data Engineer (existing job 4)
            (safe_cand(9), existing_jobs[4], PipelineStage.screening, recruiter3.id, 4),
            # Przemysław Kowalczyk → Python Data Engineer (existing job 4)
            (safe_cand(2), existing_jobs[4], PipelineStage.interview, recruiter3.id, 5),
            # Natalia Wiśniewska → QA Automation Engineer (existing job 3)
            (safe_cand(3), existing_jobs[3], PipelineStage.hired, recruiter2.id, 5),
            # Marek Ziółkowski → QA Automation Engineer (existing job 3)
            (safe_cand(14), existing_jobs[3], PipelineStage.interview, recruiter2.id, 4),
            # Aleksandra Nowak → Scrum Master / Agile Coach (existing job 6)
            (safe_cand(5), existing_jobs[6], PipelineStage.interview, recruiter1.id, 4),
            # Agnieszka Dąbrowska → Scrum Master / Agile Coach (existing job 6)
            (safe_cand(15), existing_jobs[6], PipelineStage.screening, recruiter1.id, 3),
            # Wojciech Mazur → Tech Lead / Architect (existing job 8) — .NET variant
            (safe_cand(16), existing_jobs[8], PipelineStage.new, recruiter1.id, None),
            # Kamil Brzozowski → Python Data Engineer (existing job 4 - ML fit)
            (safe_cand(17), existing_jobs[4], PipelineStage.new, recruiter3.id, None),
        ]

        for cand, job, stage, moved_by_id, rating in pipeline_entries:
            await transition_process(
                db,
                candidate_id=cand.id,
                job_id=job.id,
                stage=stage,
                actor_user_id=moved_by_id,
                moved_at=now - timedelta(hours=abs(hash(str(cand.id) + str(job.id))) % 120),
                rating=rating,
                work_channel=PriorityChannel.database,
                # Provenance only; never a Priority Work bypass.
                source_authority="seed",
            )
        await db.flush()
        print(f"  Created {len(pipeline_entries)} pipeline entries")

        # ── 5 NEW CONTRACTS ─────────────────────────────────────────────────
        new_contracts_data = [
            # Tomasz Wiśniewski (Cloud Architect) → Nordea
            {
                "candidate_id": safe_cand(0).id,
                "client_id": clients_by_name["Nordea Bank AB"].id,
                "job_id": safe_job(0).id,
                "start_date": date.today() + timedelta(days=14),
                "end_date": date.today() + timedelta(days=14 + 180),
                "rate_candidate": 26000,
                "rate_client": 33000,
                "currency": "PLN",
                "contract_type": ContractType.b2b,
                "status": ContractStatus.draft,
            },
            # Karolina Zielińska (Java Senior) → BNP Paribas
            {
                "candidate_id": safe_cand(1).id,
                "client_id": clients_by_name["BNP Paribas Bank Polska"].id,
                "job_id": existing_jobs[1].id,
                "start_date": date.today() + timedelta(days=30),
                "end_date": date.today() + timedelta(days=30 + 180),
                "rate_candidate": 19000,
                "rate_client": 25000,
                "currency": "PLN",
                "contract_type": ContractType.b2b,
                "status": ContractStatus.draft,
            },
            # Przemysław Kowalczyk (Data Engineer) → ING
            {
                "candidate_id": safe_cand(2).id,
                "client_id": clients_by_name["ING Bank Śląski"].id,
                "job_id": safe_job(2).id,
                "start_date": date.today() - timedelta(days=10),
                "end_date": date.today() + timedelta(days=170),
                "rate_candidate": 22000,
                "rate_client": 28500,
                "currency": "PLN",
                "contract_type": ContractType.b2b,
                "status": ContractStatus.active,
            },
            # Natalia Wiśniewska (QA Lead) → BNP Paribas - extension
            {
                "candidate_id": safe_cand(3).id,
                "client_id": clients_by_name["BNP Paribas Bank Polska"].id,
                "job_id": safe_job(1).id,
                "start_date": date.today() + timedelta(days=21),
                "end_date": date.today() + timedelta(days=21 + 180),
                "rate_candidate": 19000,
                "rate_client": 25000,
                "currency": "PLN",
                "contract_type": ContractType.b2b,
                "status": ContractStatus.draft,
            },
            # Joanna Kowalska (DevOps) → Bank Pekao SA — started
            {
                "candidate_id": safe_cand(13).id,
                "client_id": clients_by_name["Bank Pekao SA"].id,
                "job_id": existing_jobs[2].id,
                "start_date": date.today() - timedelta(days=5),
                "end_date": date.today() + timedelta(days=175),
                "rate_candidate": 20000,
                "rate_client": 26500,
                "currency": "PLN",
                "contract_type": ContractType.b2b,
                "status": ContractStatus.active,
            },
        ]

        for cd_data in new_contracts_data:
            rate_c = cd_data.get("rate_client")
            rate_ca = cd_data.get("rate_candidate")
            margin = (rate_c - rate_ca) if rate_c and rate_ca else None
            c = Contract(**cd_data, margin=margin)
            db.add(c)
        await db.flush()
        print(f"  Created {len(new_contracts_data)} new contracts")

        # ── 50 ACTIVITY RECORDS ─────────────────────────────────────────────
        all_user_ids = [admin_user.id, recruiter1.id, recruiter2.id, recruiter3.id, dom_user.id]
        activity_records = []

        def make_activity(entity_type, entity_id, action, user_id, details, days_offset):
            return Activity(
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                user_id=user_id,
                details=details,
                created_at=now - timedelta(days=days_offset, hours=abs(hash(str(entity_id) + action)) % 8),
            )

        # Activities for new candidates
        for i, cand in enumerate(new_candidates[:15]):
            act_user = all_user_ids[i % len(all_user_ids)]
            activity_records.append(make_activity(
                "candidate", cand.id, "created", act_user,
                {"name": f"{cand.name} {cand.lastname}", "source": cand.source},
                days_offset=30 - i * 2
            ))

        # Stage changes for pipeline entries
        pipeline_actions = [
            (safe_cand(0), "stage_changed", recruiter1.id, {"stage": "interview", "job": "Cloud Architect"}, 5),
            (safe_cand(1), "stage_changed", recruiter1.id, {"stage": "offer", "job": "Java Backend Developer"}, 4),
            (safe_cand(2), "stage_changed", recruiter3.id, {"stage": "offer", "job": "Data Engineer"}, 3),
            (safe_cand(3), "stage_changed", recruiter2.id, {"stage": "hired", "job": "QA Automation Engineer"}, 2),
            (safe_cand(4), "stage_changed", recruiter2.id, {"stage": "technical", "job": "Security Analyst"}, 6),
            (safe_cand(5), "stage_changed", recruiter1.id, {"stage": "interview", "job": "Scrum Master"}, 5),
            (safe_cand(6), "stage_changed", recruiter1.id, {"stage": "screening", "job": "Java Backend Developer"}, 7),
            (safe_cand(7), "stage_changed", recruiter1.id, {"stage": "screening", "job": "Cloud Architect"}, 8),
            (safe_cand(8), "stage_changed", recruiter1.id, {"stage": "interview", "job": "Senior Angular Developer"}, 4),
            (safe_cand(9), "stage_changed", recruiter3.id, {"stage": "interview", "job": "Data Engineer"}, 3),
            (safe_cand(13), "hired", recruiter2.id, {"job": "DevOps Cloud Engineer", "client": "Bank Pekao SA"}, 5),
            (safe_cand(14), "stage_changed", recruiter2.id, {"stage": "interview", "job": "QA Automation Engineer"}, 3),
        ]
        for cand, action, user_id, details, days_offset in pipeline_actions:
            activity_records.append(make_activity("candidate", cand.id, action, user_id, details, days_offset))

        # Contract activity
        activity_records.append(make_activity(
            "contract", 0, "created", admin_user.id,
            {"candidate": "Przemysław Kowalczyk", "client": "ING Bank Śląski", "rate": 28500}, 10
        ))
        activity_records.append(make_activity(
            "contract", 0, "created", admin_user.id,
            {"candidate": "Joanna Kowalska", "client": "Bank Pekao SA", "rate": 26500}, 5
        ))

        # Job published activities for new jobs
        for i, job in enumerate(new_jobs):
            activity_records.append(make_activity(
                "job", job.id, "published", recruiter1.id if i % 2 == 0 else recruiter2.id,
                {"title": job.title, "client_id": job.client_id}, 20 - i * 3
            ))

        # Call / screening activities spread over last 30 days
        call_activities = [
            (safe_cand(0), "call_made", recruiter1.id, {"duration_min": 30, "topic": "Cloud Architect — deep screening"}, 12),
            (safe_cand(1), "call_made", recruiter1.id, {"duration_min": 22, "topic": "Java Senior — BNP Paribas offer"}, 4),
            (safe_cand(2), "call_made", recruiter3.id, {"duration_min": 18, "topic": "Data Engineer — ING offer call"}, 3),
            (safe_cand(3), "call_made", recruiter2.id, {"duration_min": 25, "topic": "QA Lead — interview prep BNP"}, 5),
            (safe_cand(4), "call_made", recruiter2.id, {"duration_min": 20, "topic": "Security Analyst — Asseco screening"}, 8),
            (safe_cand(5), "call_made", recruiter1.id, {"duration_min": 15, "topic": "Scrum Master — Pekao intro"}, 6),
            (safe_cand(6), "call_made", recruiter1.id, {"duration_min": 19, "topic": "Java Backend — BNP wstępna"}, 9),
            (safe_cand(8), "call_made", recruiter1.id, {"duration_min": 16, "topic": "React Frontend — Angular screening"}, 7),
            (safe_cand(9), "call_made", recruiter3.id, {"duration_min": 14, "topic": "Data Engineer — ING screening"}, 10),
            (safe_cand(13), "call_made", recruiter2.id, {"duration_min": 21, "topic": "DevOps — Pekao intro call"}, 8),
        ]
        for cand, action, user_id, details, days_offset in call_activities:
            activity_records.append(make_activity("candidate", cand.id, action, user_id, details, days_offset))

        # Quality control activities (Dominik)
        qc_activities = [
            (safe_cand(0), "quality_review", dom_user.id, {"verdict": "approved", "notes": "Profil weryfikowany — Cloud Architect w pełni zgodny z wymogami Nordea"}, 10),
            (safe_cand(3), "quality_review", dom_user.id, {"verdict": "approved", "notes": "QA Lead — mocne doświadczenie, zatwierdzone do wysyłki do BNP"}, 6),
            (safe_cand(1), "quality_review", dom_user.id, {"verdict": "approved", "notes": "Senior Java — CV poprawione, gotowe do prezentacji klientowi"}, 4),
        ]
        for cand, action, user_id, details, days_offset in qc_activities:
            activity_records.append(make_activity("candidate", cand.id, action, user_id, details, days_offset))

        for act in activity_records:
            db.add(act)
        await db.flush()
        print(f"  Created {len(activity_records)} activity records")

        # ── 10 CALENDAR EVENTS ──────────────────────────────────────────────
        # this_monday = start of current week
        today = date.today()
        days_to_monday = today.weekday()  # 0=Mon
        this_monday = today - timedelta(days=days_to_monday)

        def make_dt(day_offset_from_monday, hour, minute=0):
            d = this_monday + timedelta(days=day_offset_from_monday)
            return datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc)

        calendar_events_data = [
            # This week
            {
                "title": "Interview technic — Tomasz Wiśniewski / Nordea (Cloud Architect)",
                "description": "Rozmowa techniczna z hiring managerem Lars Eriksson. Stack: Azure, Terraform, K8s. Kandydat przygotowany na pytania o multi-cloud i Security Zones.",
                "event_type": EventType.interview,
                "start_time": make_dt(1, 10, 0),  # Tuesday 10:00
                "end_time": make_dt(1, 11, 30),
                "candidate_id": safe_cand(0).id,
                "job_id": safe_job(0).id,
                "client_id": clients_by_name["Nordea Bank AB"].id,
                "attendees": ["t.wisniewski.cloud@gmail.com", "lars.eriksson@nordea.com", "olaf@b2bnet.pl"],
                "location": "MS Teams",
                "teams_link": "https://teams.microsoft.com/l/meetup-join/123abc",
                "created_by": recruiter1.id,
                "status": EventStatus.scheduled,
            },
            {
                "title": "Prep call — Karolina Zielińska przed interview BNP",
                "description": "Przygotowanie Karoliny do rozmowy z BNP Paribas. Omówienie pytań technicznych Java/Kafka, oczekiwania salary, motywacja.",
                "event_type": EventType.prep_call,
                "start_time": make_dt(1, 14, 0),  # Tuesday 14:00
                "end_time": make_dt(1, 14, 45),
                "candidate_id": safe_cand(1).id,
                "job_id": existing_jobs[1].id,
                "client_id": clients_by_name["BNP Paribas Bank Polska"].id,
                "attendees": ["k.zielinska.java@gmail.com", "olaf@b2bnet.pl"],
                "location": "Telefon / Teams",
                "created_by": recruiter1.id,
                "status": EventStatus.scheduled,
            },
            {
                "title": "Screening — Natalia Wiśniewska (QA Lead)",
                "description": "Wstępny screening QA Lead z Accenture. Weryfikacja doświadczenia Playwright, zarządzanie zespołem, znajomość ISTQB Advanced.",
                "event_type": EventType.screening,
                "start_time": make_dt(2, 11, 0),  # Wednesday 11:00
                "end_time": make_dt(2, 11, 30),
                "candidate_id": safe_cand(3).id,
                "job_id": safe_job(1).id,
                "client_id": clients_by_name["BNP Paribas Bank Polska"].id,
                "attendees": ["n.wisniewska.qa@gmail.com", "marta@b2bnet.pl"],
                "location": "MS Teams",
                "created_by": recruiter2.id,
                "status": EventStatus.scheduled,
            },
            {
                "title": "Interview — Przemysław Kowalczyk / ING Data Engineer",
                "description": "Rozmowa techniczna z data team ING. PySpark, Databricks, architektura Delta Lakehouse. Kandydat po ofercie — formalna rozmowa z menedżerem.",
                "event_type": EventType.interview,
                "start_time": make_dt(2, 14, 0),  # Wednesday 14:00
                "end_time": make_dt(2, 15, 0),
                "candidate_id": safe_cand(2).id,
                "job_id": safe_job(2).id,
                "client_id": clients_by_name["ING Bank Śląski"].id,
                "attendees": ["p.kowalczyk.data@gmail.com", "l.pawlak@ing.pl", "tomasz@b2bnet.pl"],
                "location": "Teams",
                "created_by": recruiter3.id,
                "status": EventStatus.scheduled,
            },
            {
                "title": "Screening — Mateusz Dąbrowski (Security Analyst)",
                "description": "Wstępna kwalifikacja kandydata na Security Analyst dla Asseco. Weryfikacja CEH/OSCP, Splunk i doświadczenia incident response.",
                "event_type": EventType.screening,
                "start_time": make_dt(3, 10, 0),  # Thursday 10:00
                "end_time": make_dt(3, 10, 45),
                "candidate_id": safe_cand(4).id,
                "job_id": safe_job(3).id,
                "client_id": clients_by_name["Asseco Poland S.A."].id,
                "attendees": ["m.dabrowski.sec@gmail.com", "marta@b2bnet.pl"],
                "location": "Teams / Telefon",
                "created_by": recruiter2.id,
                "status": EventStatus.scheduled,
            },
            {
                "title": "Meeting sprzedażowy — ING Data Engineering Squad Q3",
                "description": "Spotkanie z Łukaszem Pawlakiem (ING) w sprawie rozszerzenia o 2 Data Engineers + Data Architect. Negocjacja stawek ramowych, zakres projektu.",
                "event_type": EventType.meeting,
                "start_time": make_dt(3, 14, 30),  # Thursday 14:30
                "end_time": make_dt(3, 16, 0),
                "candidate_id": None,
                "job_id": safe_job(2).id,
                "client_id": clients_by_name["ING Bank Śląski"].id,
                "attendees": ["l.pawlak@ing.pl", "artur@b2bnet.pl", "olaf@b2bnet.pl"],
                "location": "Biuro ING, ul. Sokolska 34, Katowice",
                "created_by": admin_user.id,
                "status": EventStatus.scheduled,
            },
            # Next week
            {
                "title": "Interview — Aleksandra Nowak (Scrum Master) / Bank Pekao",
                "description": "Rozmowa z hiring managerem Pekao. SAFe framework, prowadzenie 3+ teamów, doświadczenie w digital banking. Ważna rozmowa — oferta pending.",
                "event_type": EventType.interview,
                "start_time": make_dt(7, 10, 0),  # Next Monday 10:00
                "end_time": make_dt(7, 11, 0),
                "candidate_id": safe_cand(5).id,
                "job_id": safe_job(4).id,
                "client_id": clients_by_name["Bank Pekao SA"].id,
                "attendees": ["a.nowak.sm@gmail.com", "a.kowalczyk@pekao.com.pl", "olaf@b2bnet.pl"],
                "location": "Pekao HQ, ul. Żwirki i Wigury 31, Warszawa",
                "created_by": recruiter1.id,
                "status": EventStatus.scheduled,
            },
            {
                "title": "Prep call — Bartłomiej Nowicki przed interview BNP Java",
                "description": "Ostatnie przygotowanie Bartłomieja do rozmowy z BNP — pytania CQRS/Event Sourcing, Kafka, transakcje rozproszone.",
                "event_type": EventType.prep_call,
                "start_time": make_dt(7, 13, 0),  # Next Monday 13:00
                "end_time": make_dt(7, 13, 45),
                "candidate_id": safe_cand(6).id,
                "job_id": existing_jobs[1].id,
                "client_id": clients_by_name["BNP Paribas Bank Polska"].id,
                "attendees": ["b.nowicki.java@gmail.com", "olaf@b2bnet.pl"],
                "location": "Teams",
                "created_by": recruiter1.id,
                "status": EventStatus.scheduled,
            },
            {
                "title": "Interview — Piotr Mazurek (React/Angular) / Nordea",
                "description": "Rozmowa techniczna Angular z Lars Eriksson. Kandidat ma React background — zweryfikować poziom Angular. Pytania: NgRx, micro-frontends, performance.",
                "event_type": EventType.interview,
                "start_time": make_dt(8, 14, 0),  # Next Tuesday 14:00
                "end_time": make_dt(8, 15, 30),
                "candidate_id": safe_cand(8).id,
                "job_id": existing_jobs[0].id,
                "client_id": clients_by_name["Nordea Bank AB"].id,
                "attendees": ["p.mazurek.react@gmail.com", "lars.eriksson@nordea.com", "olaf@b2bnet.pl"],
                "location": "MS Teams",
                "created_by": recruiter1.id,
                "status": EventStatus.scheduled,
            },
            {
                "title": "Deadline — Nordea Q2 2026 — zamknięcie ofert ramowych",
                "description": "Termin złożenia ostatecznych propozycji stawek ramowych dla umowy Nordea na 5 pozycji w Q2 2026. Przygotować porównanie rynkowe i uzasadnienie cen.",
                "event_type": EventType.deadline,
                "start_time": make_dt(9, 9, 0),  # Next Wednesday 09:00
                "end_time": make_dt(9, 9, 0),
                "all_day": True,
                "candidate_id": None,
                "job_id": None,
                "client_id": clients_by_name["Nordea Bank AB"].id,
                "attendees": ["artur@b2bnet.pl", "olaf@b2bnet.pl"],
                "location": None,
                "created_by": admin_user.id,
                "status": EventStatus.scheduled,
            },
        ]

        for ev_data in calendar_events_data:
            ev = CalendarEvent(**ev_data)
            db.add(ev)
        await db.flush()
        print(f"  Created {len(calendar_events_data)} calendar events")

        await db.commit()
        print("\n✅ Extended seed completed successfully!")
        print(f"   New candidates: {len(new_candidates)}, New jobs: {len(new_jobs)}")
        print(f"   Pipeline entries: {len(pipeline_entries)}, Contracts: {len(new_contracts_data)}")
        print(f"   Activities: {len(activity_records)}")
        print(f"   Calendar events: {len(calendar_events_data)}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
    asyncio.run(seed_extended())
