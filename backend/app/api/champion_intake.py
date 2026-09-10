"""Stateless Champion intake shared by the editor, Radar and CV upload."""

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser, get_db

router = APIRouter(prefix="/champion")
TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "champion"
    / "Profil_Championa_v4.0.docx"
)


@router.get("/template")
async def download_template(current_user: OperationalUser):
    return FileResponse(
        TEMPLATE,
        filename=TEMPLATE.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


async def read_preview(file, db):
    import anthropic
    from app.models.ai_feature import AIFeatureKey
    from app.services.ai_quota import AIQuotaExceeded, ai_feature
    from app.services.champion_document import table_profile
    from app.services.champion_intake import preview_document
    from app.services.champion_profile_ingest import oversize_precheck, validate_upload

    too_big = oversize_precheck(getattr(file, "size", None))
    if too_big:
        raise HTTPException(413, too_big)
    data = await file.read()
    error = validate_upload(file.filename or "", len(data))
    if error:
        raise HTTPException(422, error)
    try:
        if file.filename.lower().endswith(".docx") and table_profile(data) is not None:
            return await preview_document(data, file.filename)
        async with ai_feature(db, AIFeatureKey.champion_profile_parse):
            return await preview_document(data, file.filename)
    except AIQuotaExceeded as exc:
        raise HTTPException(503, str(exc)) from exc
    except anthropic.APIError as exc:
        raise HTTPException(
            503, "Model AI chwilowo niedostępny — spróbuj za chwilę."
        ) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, f"Nie udało się odczytać profilu: {exc}") from exc
    except Exception as exc:
        # Invalid ZIP/XML is a document error; no document contents in logs.
        from zipfile import BadZipFile
        from lxml.etree import XMLSyntaxError

        if isinstance(exc, (BadZipFile, XMLSyntaxError)):
            raise HTTPException(422, "Nieczytelny dokument Word.") from exc
        raise


@router.post("/preview")
async def preview(
    current_user: OperationalUser,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    return await read_preview(file, db)


@router.post("/validate")
async def validate_preview(current_user: OperationalUser, payload: dict):
    from app.services.champion_intake import prepare_profile, validation

    try:
        cp = prepare_profile(payload.get("profile"), actor_id=None)
        return {"champion_profile": cp, "validation": validation(cp)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
