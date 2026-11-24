"""Aplikacje kandydatów ze strony B2B Network (serwer strony → NEXUS).

Decyzja Artura 24.11.2026: CV i aplikacje ze strony idą do NEXUSA, briefy
klientów e-mailem. Strona wysyła formularz po stronie serwera na
``POST /api/public/website-applications`` (``api/public_website_applications``).
Dwa formularze:

* ``baza`` (/dla-specjalistow) — e-mail, CV albo sam LinkedIn, stawka; bez
  imienia i nazwiska;
* ``oferta`` (/kariera/[slug]) — imię, nazwisko, e-mail, CV, stawka,
  „dostępny od”, miasto, tryb pracy. Oferty żyją na stronie, nie są
  rekrutacjami NEXUSA, więc zgłoszenie nie otwiera procesu.

Inaczej niż ``/apply/{token}`` nie ma linku ani rekrutera, więc nikt nie
dostaje dzwonka. Każde zgłoszenie zostawia za to wpis w kolejce „Zgłoszenia”
(``/applications``, ``application_submissions`` ze statusem
``pending_review``) — decyzja Artura 24.11.2026:

* **nowy e-mail** — kandydat powstaje od razu (źródło „strona WWW”, główne CV),
  a wpis w kolejce wskazuje jego profil; „Połącz” zamyka wpis;
* **e-mail już w bazie** — kandydat NIE jest ruszany (P0-CAND-01); CV leży
  bezwładnie przy wpisie, a rekruter decyduje: połącz, scal, utwórz, odrzuć.

Zgody przychodzą jako dosłowne treści zaznaczonych pól. Wiersz
``candidate_consents`` dostaje treść (``consent_text``, 0773), jej skrót
i datę — to dowód zgody z RODO art. 7 ust. 1. Potwierdzenie do kandydata
wysyła strona, więc NEXUS żadnego maila nie wysyła.

Strona pokazuje kandydatowi błąd przy każdej odpowiedzi innej niż 2xx, więc
422 dostaje tylko to, czego zgłoszenie nie może nie mieć (e-mail, zgoda, CV
albo LinkedIn, imię i nazwisko przy ofercie, plik CV). Pole opcjonalne, które
się nie czyta (stawka spoza zakresu, „dostępny od” jako tekst), zostaje jako
surowa wartość w zgłoszeniu i nie blokuje przyjęcia.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from fastapi import BackgroundTasks, HTTPException, UploadFile
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.application_submission import (
    ApplicationSubmission,
    ApplicationSubmissionStatus,
)
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_consent import (
    CONSENT_KIND_CURRENT,
    CONSENT_KIND_FUTURE,
    CONSENT_KIND_RECRUITMENT,
    CandidateConsent,
)
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.services.candidate_name_rules import without_name_markers
from app.services.public_apply import (
    PLACEHOLDER_NAME,
    RATE_MAX,
    RATE_MIN,
    cv_content_type,
    cv_display_filename,
    field_error,
)

logger = logging.getLogger(__name__)

SOURCE_LABEL = "strona WWW"
VIA = "website"
TEXT_VERSION = "www"
SOURCES = ("baza", "oferta")

MAX_CONSENTS = 5
CONSENT_MAX = 2000
NAME_MAX = 100
LINKEDIN_MAX = 500
SHORT_MAX = 120
SLUG_MAX = 120
TITLE_MAX = 200

# Strona wysyła etykietę opcji („Zdalnie”), NEXUS trzyma wartości techniczne.
_WORK_MODES = {
    "zdalnie": "remote",
    "hybryda": "hybrid",
    "stacjonarnie": "onsite",
    "dowolny": "any",
    "remote": "remote",
    "hybrid": "hybrid",
    "onsite": "onsite",
    "any": "any",
}

_EMAIL = TypeAdapter(EmailStr)


@dataclass(frozen=True)
class WebsiteApplication:
    source: str
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    offer_slug: Optional[str]
    offer_title: Optional[str]
    linkedin: Optional[str]
    consents: tuple[str, ...]
    rate_hourly: Optional[Decimal]
    availability_date: Optional[date]
    city: Optional[str]
    work_mode: Optional[str]
    # Surowe pola z formularza (także te, których nie dało się odczytać).
    raw: dict[str, Optional[str]]


def _text(value: Any, field_name: str, max_len: int) -> Optional[str]:
    """Pole tekstowe formularza: przycięte, puste = ``None``, za długie = 422."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise field_error(field_name, "Pole musi być tekstem.")
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_len:
        raise field_error(
            field_name, f"Pole może mieć najwyżej {max_len} znaków.", cleaned[:50]
        )
    return cleaned


def _rate(raw: Optional[str]) -> Optional[Decimal]:
    if raw is None:
        return None
    try:
        rate = Decimal(raw.replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return None
    if not rate.is_finite() or rate < RATE_MIN or rate > RATE_MAX:
        return None
    return rate.quantize(Decimal("0.01"))


def _iso_date(raw: Optional[str]) -> Optional[date]:
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def parse_form(form: Any) -> WebsiteApplication:
    """Formularz multipart → zgłoszenie albo 422 przy polu (kształt FastAPI)."""
    source = _text(form.get("source"), "source", 20)
    if source not in SOURCES:
        raise field_error("source", "Nieznane źródło zgłoszenia.", source)

    email_raw = _text(form.get("email"), "email", 254)
    if email_raw is None:
        raise field_error("email", "Podaj adres e-mail.")
    try:
        email = str(_EMAIL.validate_python(email_raw))
    except ValidationError:
        raise field_error("email", "Niepoprawny adres e-mail.", email_raw) from None

    first_name = _text(form.get("first_name"), "first_name", NAME_MAX)
    last_name = _text(form.get("last_name"), "last_name", NAME_MAX)
    offer_slug = _text(form.get("offer_slug"), "offer_slug", SLUG_MAX)
    offer_title = _text(form.get("offer_title"), "offer_title", TITLE_MAX)
    if source == "oferta":
        for name, value in (("first_name", first_name), ("last_name", last_name)):
            if value is None:
                raise field_error(name, "Uzupełnij to pole.")
        if offer_slug is None:
            raise field_error("offer_slug", "Brak oferty, na którą jest zgłoszenie.")

    consents: list[str] = []
    for value in form.getlist("consent"):
        text = _text(value, "consent", CONSENT_MAX)
        if text is not None and text not in consents:
            consents.append(text)
    if not consents:
        raise field_error(
            "consent",
            "Brak zgody na przetwarzanie danych — bez niej nie możemy przyjąć "
            "zgłoszenia.",
        )
    if len(consents) > MAX_CONSENTS:
        raise field_error("consent", "Za dużo zgód w jednym zgłoszeniu.")

    raw = {
        "rate": _text(form.get("rate"), "rate", SHORT_MAX),
        "available_from": _text(
            form.get("available_from"), "available_from", SHORT_MAX
        ),
        "city": _text(form.get("city"), "city", SHORT_MAX),
        "work_mode": _text(form.get("work_mode"), "work_mode", SHORT_MAX),
    }
    return WebsiteApplication(
        source=source,
        email=email,
        first_name=first_name,
        last_name=last_name,
        offer_slug=offer_slug,
        offer_title=offer_title,
        linkedin=_text(form.get("linkedin"), "linkedin", LINKEDIN_MAX),
        consents=tuple(consents),
        rate_hourly=_rate(raw["rate"]),
        availability_date=_iso_date(raw["available_from"]),
        city=raw["city"],
        work_mode=_WORK_MODES.get((raw["work_mode"] or "").lower()),
        raw=raw,
    )


def consent_kind(app: WebsiteApplication, index: int) -> str:
    """Rodzaj zgody według formularza strony.

    „Baza” ma jedną zgodę na obecne i przyszłe rekrutacje. Oferta: pierwsza
    zgoda to obowiązkowa zgoda na tę rekrutację, kolejne to dobrowolna zgoda
    na przyszłe (kolejność ``consents`` w ``src/lib/forms/parse.ts`` strony).
    """
    if app.source == "baza":
        return CONSENT_KIND_RECRUITMENT
    return CONSENT_KIND_CURRENT if index == 0 else CONSENT_KIND_FUTURE


def _consent_rows(app: WebsiteApplication, **subject: int) -> list[CandidateConsent]:
    now = datetime.now(timezone.utc)
    return [
        CandidateConsent(
            kind=consent_kind(app, index),
            text_version=TEXT_VERSION,
            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            consent_text=text,
            given_at=now,
            **subject,
        )
        for index, text in enumerate(app.consents)
    ]


def _where(app: WebsiteApplication) -> str:
    if app.source == "oferta":
        return f"oferta „{app.offer_title or app.offer_slug}”"
    return "baza kandydatów (/dla-specjalistow)"


def _details_line(app: WebsiteApplication) -> Optional[str]:
    parts = []
    if app.raw.get("rate"):
        parts.append(f"stawka: {app.raw['rate']} zł/h")
    if app.raw.get("available_from"):
        parts.append(f"dostępny od: {app.raw['available_from']}")
    if app.raw.get("city"):
        parts.append(f"miasto: {app.raw['city']}")
    if app.raw.get("work_mode"):
        parts.append(f"tryb: {app.raw['work_mode']}")
    if not parts:
        return None
    line = "; ".join(parts)
    return line[0].upper() + line[1:] + "."


def queue_message(app: WebsiteApplication, *, duplicate: bool, has_cv: bool) -> str:
    """Opis wpisu w kolejce „Zgłoszenia” — rekruter widzi go na karcie."""
    head = f"Strona WWW, {_where(app)}."
    if duplicate:
        body = (
            "Ten adres był już w bazie — profil bez zmian. Zdecyduj: połącz, "
            "scal, utwórz albo odrzuć."
        )
    else:
        body = "Nowa osoba — profil założony automatycznie" + (
            ", CV w profilu." if has_cv else ", bez CV (podany LinkedIn)."
        )
        body += " „Połącz” zamyka wpis."
    details = _details_line(app)
    return " ".join(part for part in (head, body, details) if part)


def _payload(app: WebsiteApplication) -> dict[str, Any]:
    return {
        "via": VIA,
        "source": app.source,
        "offer": (
            {"slug": app.offer_slug, "title": app.offer_title}
            if app.source == "oferta"
            else None
        ),
        "first_name": app.first_name,
        "last_name": app.last_name,
        "email": app.email,
        "linkedin": app.linkedin,
        "expected_rate_hourly": (
            str(app.rate_hourly) if app.rate_hourly is not None else None
        ),
        "availability_date": (
            app.availability_date.isoformat() if app.availability_date else None
        ),
        "city": app.city,
        "work_mode": app.work_mode,
        "raw": dict(app.raw),
        "consent": {
            "kinds": [consent_kind(app, i) for i in range(len(app.consents))],
            "text_version": TEXT_VERSION,
        },
    }


def _submission(
    app: WebsiteApplication, *, matched_candidate_id: int, duplicate: bool, has_cv: bool
) -> ApplicationSubmission:
    return ApplicationSubmission(
        invite_link_token_sha256=None,
        job_id=None,
        status=ApplicationSubmissionStatus.pending_review.value,
        submitted_first_name=app.first_name or PLACEHOLDER_NAME,
        submitted_last_name=app.last_name or PLACEHOLDER_NAME,
        submitted_email=app.email,
        submitted_linkedin=app.linkedin,
        submitted_message=queue_message(app, duplicate=duplicate, has_cv=has_cv),
        matched_candidate_id=matched_candidate_id,
        raw_payload=_payload(app),
    )


async def submit(
    db: AsyncSession,
    *,
    app: WebsiteApplication,
    cv: Optional[UploadFile],
    content: Optional[bytes],
    background_tasks: BackgroundTasks,
) -> dict:
    """Obie gałęzie zgłoszenia; commit w środku. Odpowiedź bez śladu duplikatu."""
    existing = await db.scalar(
        select(Candidate).where(func.lower(Candidate.email) == app.email.lower())
    )
    if existing is not None:
        await _record_duplicate(db, app=app, existing=existing, cv=cv, content=content)
        await db.commit()
        return {"ok": True, "status": "received"}

    candidate_id = await _create_candidate(db, app=app, cv=cv, content=content)
    await db.commit()
    if cv is not None:
        from app.api import public_share

        # Lookup przez moduł: testy podmieniają `_invite_post_apply_task`.
        background_tasks.add_task(public_share._invite_post_apply_task, candidate_id)
    return {"ok": True, "status": "received"}


async def _record_duplicate(
    db: AsyncSession,
    *,
    app: WebsiteApplication,
    existing: Candidate,
    cv: Optional[UploadFile],
    content: Optional[bytes],
) -> None:
    """E-mail już w bazie: kandydat bez zmian, wpis ``pending_review`` z CV."""
    from app.api import public_share

    submission = _submission(
        app,
        matched_candidate_id=existing.id,
        duplicate=True,
        has_cv=cv is not None,
    )
    if cv is not None and content is not None:
        object_key, cv_bytes, raw_text = await public_share._persist_submission_cv(
            cv, content
        )
        submission.cv_object_key = object_key
        submission.cv_file_content = cv_bytes
        submission.cv_filename = cv_display_filename(cv)
        submission.cv_content_type = cv_content_type(cv)
        submission.cv_size_bytes = len(content)
        submission.raw_cv_text = raw_text
    db.add(submission)
    await db.flush()
    db.add_all(_consent_rows(app, application_submission_id=submission.id))
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=existing.id,
            action="applied_via_website",
            user_id=None,
            details={
                "via": VIA,
                "source": app.source,
                "offer_slug": app.offer_slug,
                "was_duplicate": True,
                "submission_id": submission.id,
            },
        )
    )


async def _create_candidate(
    db: AsyncSession,
    *,
    app: WebsiteApplication,
    cv: Optional[UploadFile],
    content: Optional[bytes],
) -> int:
    from app.api import public_share
    from app.services.candidate_erasure_leftovers import (
        VIA_SELF_APPLICATION,
        email_was_erased,
        record_recreated_after_erasure,
    )
    from app.services.index_outbox_service import schedule_or_embed_candidate

    now = datetime.now(timezone.utc)
    erased_before = await email_was_erased(db, app.email.lower())
    # Stawka w konstruktorze, nie przypisaniem po fakcie — patrz
    # `public_apply._create_candidate` (kontrakt writera etapów).
    rate_fields: dict[str, Any] = {}
    if app.rate_hourly is not None:
        rate_fields = {
            "expected_rate_hourly": app.rate_hourly,
            "expected_rate_currency": "PLN",
            "profile_rate_updated_at": now,
        }
    remote_modes = (
        ["remote", "hybrid", "onsite"]
        if app.work_mode == "any"
        else ([app.work_mode] if app.work_mode else None)
    )
    candidate = Candidate(
        name=without_name_markers(app.first_name)
        if app.first_name
        else PLACEHOLDER_NAME,
        lastname=(
            without_name_markers(app.last_name) if app.last_name else PLACEHOLDER_NAME
        ),
        email=app.email,
        linkedin=app.linkedin,
        source=SOURCE_LABEL,
        status=CandidateStatus.active,
        created_by=None,
        city=app.city,
        availability_date=app.availability_date,
        preferences={"remote_modes": remote_modes} if remote_modes else {},
        **rate_fields,
    )
    db.add(candidate)
    await db.flush()
    candidate_id = candidate.id
    # Savepoint — awaria intencji indeksu nie cofa zgłoszenia.
    try:
        async with db.begin_nested():
            await schedule_or_embed_candidate(candidate_id, db)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "[website-apply] index intent failed candidate=%s: %s",
            candidate_id,
            type(exc).__name__,
        )
    db.add_all(_consent_rows(app, candidate_id=candidate_id))

    if cv is not None and content is not None:
        stored_filename, _raw_text = await public_share._persist_cv(
            candidate_id, cv, content
        )
        db.add(
            CandidateDocument(
                candidate_id=candidate_id,
                filename=stored_filename,
                file_content=content,
                content_type=cv_content_type(cv),
                size_bytes=len(content),
                document_kind=CandidateDocumentKind.cv,
                is_primary=True,
                uploaded_at=now,
                external_source=VIA,
                content_sha256=hashlib.sha256(content).hexdigest(),
            )
        )
    if erased_before:
        record_recreated_after_erasure(
            db, candidate_id, user_id=None, via=VIA_SELF_APPLICATION
        )
    db.add(
        _submission(
            app,
            matched_candidate_id=candidate_id,
            duplicate=False,
            has_cv=cv is not None,
        )
    )
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate_id,
            action="applied_via_website",
            user_id=None,
            details={
                "via": VIA,
                "source": app.source,
                "offer_slug": app.offer_slug,
                "was_duplicate": False,
            },
        )
    )
    return candidate_id


def require_cv_or_linkedin(app: WebsiteApplication, has_cv: bool) -> None:
    """Oferta wymaga CV; „baza” przyjmuje CV albo sam LinkedIn."""
    if has_cv:
        return
    if app.source == "oferta":
        raise field_error("cv", "Dołącz CV.")
    if app.linkedin is None:
        raise field_error("cv", "Dołącz CV albo podaj profil LinkedIn.")


def unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Brak albo niepoprawny token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
