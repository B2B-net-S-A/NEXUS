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
``candidate_consents`` dostaje treść (``consent_text``, 0772), jej skrót
i datę — to dowód zgody z RODO art. 7 ust. 1. Potwierdzenie do kandydata
wysyła strona, więc NEXUS żadnego maila nie wysyła.

Strona pokazuje kandydatowi błąd przy każdej odpowiedzi innej niż 2xx, więc
422 dostaje tylko to, czego zgłoszenie nie może nie mieć (e-mail, zgoda, CV
albo LinkedIn, imię i nazwisko przy ofercie, plik CV). Pole opcjonalne, które
się nie czyta (stawka spoza zakresu, „dostępny od” jako tekst), zostaje jako
surowa wartość w zgłoszeniu i nie blokuje przyjęcia.

Raport kompetencji (decyzje Artura 25.11.2026): ``baza`` z ``report=1`` niesie
warunki z nowego formularza (``current_rate``, ``contract``, powtarzane
``work_mode`` i ``office_city``, ``office_days_max``, ``start``). Te pola strona
wybiera z list, więc zła wartość to błąd strony i dostaje 422; ``report=1``
wymaga CV i stawki. Warunki idą do profilu przez writery
(``website_application_terms``) — u osoby już w bazie też, ale bez pól, które
rekruter zmienił w ostatnich 14 dniach — a raport czeka na odczyt CV
(``competence_report_store``). Raport to jedyny mail NEXUSA do kandydata ze
strony.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
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
from app.services.competence_report_schema import ReportConditions
from app.services.competence_report_store import create_report_for_application
from app.services.website_application_terms import WebsiteTerms, apply_terms
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
_MODE_ORDER = ("remote", "hybrid", "onsite")

# Pola raportu kompetencji (kontrakt strony z 25.11.2026).
CONTRACTS = ("b2b", "uop", "any")
STARTS = ("now", "1m", "2-3m", "browsing")
REPORT_RATE_MAX = 2000  # jak ``ReportConditions.rate``
OFFICE_DAYS_MAX = 5
MAX_OFFICE_CITIES = 10
OFFICE_CITY_MAX = 120  # jak ``office_cities`` w ``schemas/candidate.py``

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
    # Tryby pracy w kolejności remote → hybrid → onsite (``any`` = wszystkie).
    modes: tuple[str, ...] = ()
    current_rate: Optional[int] = None
    contract: Optional[str] = None
    office_days_max: Optional[int] = None
    office_cities: tuple[str, ...] = ()
    start: Optional[str] = None
    # Warunki raportu kompetencji — są tylko przy ``report=1``.
    conditions: Optional[ReportConditions] = None

    @property
    def report(self) -> bool:
        return self.conditions is not None

    def terms(self) -> WebsiteTerms:
        return WebsiteTerms(
            rate_hourly=self.rate_hourly,
            contract=self.contract,
            modes=self.modes,
            office_days_max=self.office_days_max,
            cities=self.office_cities,
            start=self.start,
        )


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


def _whole(rate: Decimal) -> int:
    return int(rate.to_integral_value(rounding=ROUND_HALF_UP))


def _strict_int(form: Any, name: str, low: int, high: int) -> Optional[int]:
    """Liczba z listy strony: brak = ``None``, poza zakresem albo tekst = 422."""
    raw = _text(form.get(name), name, SHORT_MAX)
    if raw is None:
        return None
    message = f"Podaj liczbę od {low} do {high}."
    try:
        value = Decimal(raw.replace(" ", "").replace(",", "."))
    except InvalidOperation:
        raise field_error(name, message, raw) from None
    if not value.is_finite() or value < low or value > high:
        raise field_error(name, message, raw)
    return _whole(value)


def _choice(form: Any, name: str, allowed: tuple[str, ...]) -> Optional[str]:
    raw = _text(form.get(name), name, SHORT_MAX)
    if raw is None:
        return None
    if raw.lower() not in allowed:
        raise field_error(name, "Nieznana wartość pola.", raw)
    return raw.lower()


def _modes(values: list[Any], *, strict: bool) -> tuple[str, ...]:
    """Powtarzane ``work_mode``: wartości techniczne albo dawna etykieta strony.

    Bez raportu nieznana etykieta tylko przepada (dawny formularz); przy
    ``report=1`` to błąd strony — 422.
    """
    picked: set[str] = set()
    for value in values:
        label = _text(value, "work_mode", SHORT_MAX)
        if label is None:
            continue
        mode = _WORK_MODES.get(label.lower())
        if mode is None:
            if strict:
                raise field_error("work_mode", "Nieznany tryb pracy.", label)
            continue
        picked |= set(_MODE_ORDER) if mode == "any" else {mode}
    return tuple(m for m in _MODE_ORDER if m in picked)


def _office_cities(values: list[Any]) -> tuple[str, ...]:
    """Miasta biura jak ``office_cities`` profilu: przycięte, bez powtórek."""
    seen: set[str] = set()
    cities: list[str] = []
    for value in values:
        city = _text(value, "office_city", OFFICE_CITY_MAX)
        if city is None or city.casefold() in seen:
            continue
        seen.add(city.casefold())
        cities.append(city)
    if len(cities) > MAX_OFFICE_CITIES:
        raise field_error("office_city", f"Podaj najwyżej {MAX_OFFICE_CITIES} miast.")
    return tuple(cities)


def _report_flag(form: Any, source: str) -> bool:
    raw = _text(form.get("report"), "report", 5)
    if raw is None or raw == "0":
        return False
    if raw != "1":
        raise field_error("report", "Nieznana wartość pola.", raw)
    if source != "baza":
        raise field_error("report", "Raport jest tylko w formularzu bazy.", source)
    return True


def _report_conditions(
    *,
    rate: Optional[Decimal],
    raw_rate: Optional[str],
    current_rate: Optional[int],
    contract: Optional[str],
    modes: tuple[str, ...],
    office_days_max: Optional[int],
    office_cities: tuple[str, ...],
    start: Optional[str],
) -> ReportConditions:
    if rate is None or rate > REPORT_RATE_MAX:
        if raw_rate is None:
            raise field_error("rate", "Podaj oczekiwaną stawkę (zł/h netto).")
        raise field_error(
            "rate", f"Podaj stawkę od 1 do {REPORT_RATE_MAX} zł/h.", raw_rate
        )
    fields: dict[str, Any] = {
        "rate": _whole(rate),
        "current_rate": current_rate,
        "modes": modes,
        "office_days_max": office_days_max,
        "office_cities": office_cities,
        "start": start,
    }
    if contract is not None:
        fields["contract"] = contract
    return ReportConditions(**fields)


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

    report = _report_flag(form, source)
    mode_values = list(form.getlist("work_mode"))
    modes = _modes(mode_values, strict=report)
    current_rate = _strict_int(form, "current_rate", 1, REPORT_RATE_MAX)
    contract = _choice(form, "contract", CONTRACTS)
    office_days_max = _strict_int(form, "office_days_max", 0, OFFICE_DAYS_MAX)
    office_cities = _office_cities(list(form.getlist("office_city")))
    start = _choice(form, "start", STARTS)

    mode_labels = [
        label
        for label in (_text(v, "work_mode", SHORT_MAX) for v in mode_values)
        if label is not None
    ]
    raw = {
        "rate": _text(form.get("rate"), "rate", SHORT_MAX),
        "available_from": _text(
            form.get("available_from"), "available_from", SHORT_MAX
        ),
        "city": _text(form.get("city"), "city", SHORT_MAX),
        "work_mode": ", ".join(mode_labels) or None,
    }
    rate_hourly = _rate(raw["rate"])
    conditions = (
        _report_conditions(
            rate=rate_hourly,
            raw_rate=raw["rate"],
            current_rate=current_rate,
            contract=contract,
            modes=modes,
            office_days_max=office_days_max,
            office_cities=office_cities,
            start=start,
        )
        if report
        else None
    )
    return WebsiteApplication(
        source=source,
        email=email,
        first_name=first_name,
        last_name=last_name,
        offer_slug=offer_slug,
        offer_title=offer_title,
        linkedin=_text(form.get("linkedin"), "linkedin", LINKEDIN_MAX),
        consents=tuple(consents),
        rate_hourly=rate_hourly,
        availability_date=_iso_date(raw["available_from"]),
        city=raw["city"],
        work_mode=(
            _WORK_MODES.get(mode_labels[0].lower()) if len(mode_labels) == 1 else None
        ),
        raw=raw,
        modes=modes,
        current_rate=current_rate,
        contract=contract,
        office_days_max=office_days_max,
        office_cities=office_cities,
        start=start,
        conditions=conditions,
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
    if app.current_rate is not None:
        parts.append(f"obecna stawka: {app.current_rate} zł/h")
    if app.contract is not None:
        parts.append(f"forma: {app.contract}")
    if app.office_days_max is not None:
        parts.append(f"najwięcej dni w biurze: {app.office_days_max}")
    if app.office_cities:
        parts.append(f"miasta biura: {', '.join(app.office_cities)}")
    if app.start is not None:
        parts.append(f"start: {app.start}")
    if not parts:
        return None
    line = "; ".join(parts)
    return line[0].upper() + line[1:] + "."


def queue_message(app: WebsiteApplication, *, duplicate: bool, has_cv: bool) -> str:
    """Opis wpisu w kolejce „Zgłoszenia” — rekruter widzi go na karcie."""
    head = f"Strona WWW, {_where(app)}."
    if duplicate and app.report:
        body = (
            "Ten adres był już w bazie — CV nie zmienia profilu, a warunki "
            "z formularza zapisaliśmy w profilu (bez pól, które rekruter zmienił "
            "w ostatnich 14 dniach). Zdecyduj: połącz, scal, utwórz albo odrzuć."
        )
    elif duplicate:
        body = (
            "Ten adres był już w bazie — profil bez zmian. Zdecyduj: połącz, "
            "scal, utwórz albo odrzuć."
        )
    else:
        body = "Nowa osoba — profil założony automatycznie" + (
            ", CV w profilu." if has_cv else ", bez CV (podany LinkedIn)."
        )
        body += " „Połącz” zamyka wpis."
    report = (
        "Prośba o raport kompetencji — wyślemy go w 24 godziny." if app.report else None
    )
    details = _details_line(app)
    return " ".join(part for part in (head, body, report, details) if part)


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
        "work_modes": list(app.modes),
        # Obecna stawka nie jest oczekiwaniem — klucz inny niż
        # ``expected_rate_hourly``, który czyta historia stawek.
        "current_rate_hourly": app.current_rate,
        "contract": app.contract,
        "office_days_max": app.office_days_max,
        "office_cities": list(app.office_cities),
        "start": app.start,
        "report": app.report,
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
    terms: Optional[dict] = None
    if app.conditions is not None:
        # Decyzja Artura 25.11.2026: osoba w bazie też dostaje raport, a jej
        # warunki idą do profilu przez writery (zmiany rekrutera z 14 dni
        # zostają). CV dalej czeka w zgłoszeniu i profilu nie zmienia.
        terms = await apply_terms(
            db,
            existing,
            app.terms(),
            now=datetime.now(timezone.utc),
            protect=True,
        )
        await create_report_for_application(
            db, existing, submission, app.conditions, app.email
        )
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
                "report": app.report,
                **({"terms": terms} if terms is not None else {}),
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
        preferences={},
        **rate_fields,
    )
    db.add(candidate)
    await db.flush()
    candidate_id = candidate.id
    # Tryb, dni, miasta, forma i start przez writery profilu (jak formularz
    # warunków); stawka jest już w konstruktorze.
    terms = await apply_terms(
        db, candidate, app.terms(), now=now, protect=False, write_rate=False
    )
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
    submission = _submission(
        app,
        matched_candidate_id=candidate_id,
        duplicate=False,
        has_cv=cv is not None,
    )
    db.add(submission)
    if app.conditions is not None:
        await db.flush()
        await create_report_for_application(
            db, candidate, submission, app.conditions, app.email
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
                "report": app.report,
                "terms": terms,
            },
        )
    )
    return candidate_id


def require_cv_or_linkedin(app: WebsiteApplication, has_cv: bool) -> None:
    """Oferta i raport wymagają CV; „baza” bez raportu przyjmuje sam LinkedIn."""
    if has_cv:
        return
    if app.report:
        raise field_error("cv", "Dołącz CV — bez niego nie przygotujemy raportu.")
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
