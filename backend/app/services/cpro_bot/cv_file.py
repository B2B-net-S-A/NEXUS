"""Ten sam zamrożony, zatwierdzony PDF dla webhooka i sesji operatora."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cv_document_version import CvDocumentVersion
from app.services import cv_layout, cv_new_pdf
from app.services.cv_pdf_preview import pdf_from_docx


async def render_approved_pdf(
    db: AsyncSession, version: CvDocumentVersion, *, classic_renderer=None
) -> tuple[bytes, str]:
    if cv_layout.is_new(getattr(version, "cv_layout", None)):
        return (await cv_new_pdf.approved_version_pdf(db, version)).pdf, "new"
    docx = version.docx_content
    await db.commit()
    return await (classic_renderer or pdf_from_docx)(docx), "classic"
