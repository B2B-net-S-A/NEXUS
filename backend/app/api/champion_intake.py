"""Stateless Champion intake shared by the editor, Radar and CV upload."""

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser, get_db
from app.api.section_access import require_section_access_any
from app.core.rate_limit import limiter
from app.services.section_permissions import ProductSection

# Wspólne dla edytora w rekrutacji (Pipeline) oraz Radaru i generatora CV
# (Sourcing), więc wystarcza którakolwiek z sekcji (F02). Poziom wynika z metody:
# `/preview` i `/validate` zużywają płatną kwotę AI, więc wymagają zapisu —
# konto z sekcją obniżoną do odczytu nie może wydawać budżetu AI.
router = APIRouter(
    prefix="/champion",
    dependencies=[
        Depends(
            require_section_access_any(ProductSection.sourcing, ProductSection.pipeline)
        )
    ],
)
TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "champion"
    / "Profil_Championa_v4.0.docx"
)


@router.get("/template")
@limiter.limit("60/minute")
async def download_template(request: Request, current_user: OperationalUser):
    return FileResponse(
        TEMPLATE,
        filename=TEMPLATE.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


async def read_preview(file, db):
    import anthropic
    from app.services.ai_quota import AIQuotaExceeded
    from app.services.champion_intake import preview_document
    from app.services.champion_profile_ingest import (
        oversize_precheck,
        validate_upload,
        MAX_FILE_BYTES,
    )

    too_big = oversize_precheck(getattr(file, "size", None))
    if too_big:
        raise HTTPException(413, too_big)
    data = await file.read(MAX_FILE_BYTES + 1)
    error = validate_upload(file.filename or "", len(data))
    if error:
        raise HTTPException(422, error)
    try:
        return await preview_document(data, file.filename, db=db)
    except AIQuotaExceeded as exc:
        raise HTTPException(503, str(exc)) from exc
    except anthropic.APIError as exc:
        raise HTTPException(
            503, "Model AI chwilowo niedostępny — spróbuj za chwilę."
        ) from exc
    except ValidationError as exc:
        # ValidationError is a ValueError: without this branch the user got
        # the raw Pydantic dump with an errors.pydantic.dev link (UAT M04-B01).
        fields = sorted(
            {
                ".".join(str(part) for part in err.get("loc", ()))
                for err in exc.errors()
                if err.get("loc")
            }
        )
        where = f" ({', '.join(fields[:5])})" if fields else ""
        raise HTTPException(
            422,
            "Nie udało się odczytać profilu: dokument ma niepoprawne albo "
            f"niekompletne pola{where}. "
            "Uzupełnij je we wzorze albo w edytorze Championa.",
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
@limiter.limit("10/minute")
async def preview(
    request: Request,
    current_user: OperationalUser,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    return await read_preview(file, db)


@router.post("/validate")
@limiter.limit("30/minute")
async def validate_preview(
    request: Request, current_user: OperationalUser, payload: dict
):
    from app.services.champion_intake import prepare_profile, validation

    try:
        cp = prepare_profile(payload.get("profile"), actor_id=None)
        return {"champion_profile": cp, "validation": validation(cp)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
