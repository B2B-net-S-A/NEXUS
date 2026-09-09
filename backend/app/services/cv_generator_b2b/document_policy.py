"""Client policy resolution shared by saved CV share and public endpoints."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.job import Job


async def interactive_client_enabled(
    db: AsyncSession, doc: CvGeneratedDocument
) -> bool:
    """Prefer the document's explicit client; use its job for legacy rows.

    A document associated with a missing client fails closed. Unassociated
    standalone documents retain the global/default interactive behavior.
    """
    client_id = doc.client_id
    if client_id is None and doc.job_id is not None:
        job = await db.get(Job, doc.job_id)
        if job is None:
            return False
        client_id = job.client_id
    if client_id is None:
        return True
    client = await db.get(Client, client_id)
    return bool(client is not None and client.cv_interactive_enabled)
