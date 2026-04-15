from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import engine, Base
from app.api import auth, candidates, jobs, clients, pipeline, notes, contracts, dashboard, search
from app.api import activities
from app.api import admin
from app.api import emails
from app.api import postings
from app.api import calls
from app.api import reports
from app.api import client_knowledge
from app.api import screenings
from app.api import sales
from app.api import contacts
from app.api import prep_kit
from app.api import ai_writer
from app.api import talent_pools
from app.api import cv_generator
from app.api import calendar
from app.api import notifications
from app.api import import_export
from app.api import fireflies
from app.api import ws
from app.api import matching


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables if not exists (dev mode; use Alembic in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Startup: ensure Qdrant collection exists
    import asyncio
    import logging
    from app.services.embedding_service import init_qdrant_collection
    try:
        await asyncio.to_thread(init_qdrant_collection)
    except Exception as e:
        logging.getLogger(__name__).warning(f"Qdrant init skipped: {e}")

    # Start calendar reminder background task
    from app.api.calendar import calendar_reminder_loop
    reminder_task = asyncio.create_task(calendar_reminder_loop())

    yield

    # Shutdown
    reminder_task.cancel()
    try:
        await reminder_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()


app = FastAPI(
    title="DynaMinds ATS & CRM",
    description="Modern recruitment platform for IT staffing agencies",
    version="0.2.0",
    lifespan=lifespan,
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(candidates.router, prefix="/api/candidates", tags=["candidates"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(clients.router, prefix="/api/clients", tags=["clients"])
app.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"])
app.include_router(notes.router, prefix="/api/notes", tags=["notes"])
app.include_router(contracts.router, prefix="/api/contracts", tags=["contracts"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(activities.router, prefix="/api/activities", tags=["activities"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(emails.router, prefix="/api", tags=["emails"])
app.include_router(postings.router, prefix="/api", tags=["postings"])
app.include_router(calls.router, prefix="/api", tags=["calls"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
app.include_router(client_knowledge.router, prefix="/api", tags=["client-knowledge"])
app.include_router(screenings.router, prefix="/api", tags=["screenings"])
app.include_router(sales.router, prefix="/api", tags=["sales"])
app.include_router(contacts.router, prefix="/api", tags=["contacts"])
app.include_router(prep_kit.router, prefix="/api", tags=["prep-kit"])
app.include_router(ai_writer.router, prefix="/api", tags=["ai-writer"])
app.include_router(talent_pools.router, prefix="/api", tags=["talent-pools"])
app.include_router(cv_generator.router, prefix="/api", tags=["cv-generator"])
app.include_router(calendar.router, prefix="/api", tags=["calendar"])
app.include_router(notifications.router, prefix="/api", tags=["notifications"])
app.include_router(import_export.router, prefix="/api", tags=["import-export"])
app.include_router(fireflies.router, prefix="/api", tags=["fireflies"])
app.include_router(ws.router, tags=["websocket"])
app.include_router(matching.router, prefix="/api", tags=["matching"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "app": "DynaMinds ATS", "version": "0.2.0"}
