"""Aplikacje kandydatów ze strony B2B Network — trasa serwer–serwer.

``POST /api/public/website-applications`` woła wyłącznie serwer strony
(``src/lib/forms/delivery.ts`` w repo strony), nie przeglądarka kandydata.
Poświadczenie: ``Authorization: Bearer <WEBSITE_APPLICATIONS_TOKEN>``,
porównane w stałym czasie. Token jest sprawdzany PRZED odczytem treści
multipart, więc bez tokenu nikt nie wgra pliku na serwer.

Limit: cały ruch przychodzi z jednego adresu (serwer strony), więc kubełek
jest wspólny dla wszystkich kandydatów. Per osoba limituje strona; tu jest
sufit na rozpędzony albo przejęty serwer strony (decyzja Artura 24.11.2026:
60/min, 300/h zamiast 5/min, 30/h z ``/apply``).

Logika zgłoszenia: ``services/website_applications``. Moduł bez
``from __future__ import annotations`` — slowapi (patrz CLAUDE.md).

Od 28.11.2026 ten sam serwer strony i ten sam token wysyłają też dwa formularze
z /dla-specjalistow od osób spoza B2B (decyzje Artura z 28.11.2026):

* ``POST /api/public/website-trainer-applications`` — „Zostań trenerem”
  (``services/website_trainer_applications``);
* ``POST /api/public/website-referrals`` — „Poleć inżyniera”
  (``services/website_referrals``), bez maila do polecanej osoby.

Oba bez plików (próbka to link), więc bez skanu ClamAV. Limit niższy niż przy
aplikacjach: formularze są rzadsze, a per osoba limituje strona.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.security import secrets_equal
from app.services import file_scan
from app.services import website_applications as website
from app.services import website_referrals as referrals
from app.services import website_trainer_applications as trainers

logger = logging.getLogger(__name__)

router = APIRouter()

# Pola formularza strony (z zapasem) i najwyżej jeden plik.
_MAX_FIELDS = 40
_MAX_FILES = 1
# Formularze trenera i polecenia: same pola tekstowe, tematy powtarzane.
_INTAKE_MAX_FIELDS = 30


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


@router.post(
    "/website-applications",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    include_in_schema=False,
)
@limiter.limit("60/minute; 300/hour")
async def submit_website_application(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    expected = settings.WEBSITE_APPLICATIONS_TOKEN
    if not expected or not secrets_equal(_bearer(request), expected):
        raise website.unauthorized()

    from app.api import public_share

    async with request.form(max_files=_MAX_FILES, max_fields=_MAX_FIELDS) as form:
        app = website.parse_form(form)
        upload = form.get("cv")
        cv = (
            upload
            if isinstance(upload, StarletteUploadFile)
            and (upload.filename or upload.size)
            else None
        )
        content = None
        if cv is not None:
            # Najwyżej limit + 1 bajt w RAM (jak `/apply`, audyt 22.09 r2 SEC-03).
            await cv.seek(0)
            content = await cv.read(public_share._MAX_CV_BYTES + 1)
            public_share._validate_cv_file(cv, content)
            # Plik od kandydata z internetu — skan jak w `/apply` (fail-closed).
            await file_scan.require_clean_public_upload(
                content, source="website_application"
            )
        website.require_cv_or_linkedin(app, has_cv=cv is not None)
        return await website.submit(
            db,
            app=app,
            cv=cv,
            content=content,
            background_tasks=background_tasks,
        )


def _require_token(request: Request) -> None:
    expected = settings.WEBSITE_APPLICATIONS_TOKEN
    if not expected or not secrets_equal(_bearer(request), expected):
        raise website.unauthorized()


@router.post(
    "/website-trainer-applications",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    include_in_schema=False,
)
@limiter.limit("20/minute; 120/hour")
async def submit_website_trainer_application(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_token(request)
    async with request.form(max_files=0, max_fields=_INTAKE_MAX_FIELDS) as form:
        application = trainers.parse_form(form)
    return await trainers.submit(db, application)


@router.post(
    "/website-referrals",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    include_in_schema=False,
)
@limiter.limit("20/minute; 120/hour")
async def submit_website_referral(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_token(request)
    async with request.form(max_files=0, max_fields=_INTAKE_MAX_FIELDS) as form:
        referral = referrals.parse_form(form)
    return await referrals.submit(db, referral)
