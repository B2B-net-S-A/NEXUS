"""„Poleć inżyniera” ze strony B2B Network — polecenie od kogokolwiek.

Decyzja Artura z 28.11.2026: polecać może każdy. Konsultant dopisuje premię do
faktury, osoba spoza B2B dostaje ją na podstawie krótkiej umowy; premia to
1–5 tys. zł zależnie od profilu, więc kwotę wpisuje rekruter przy poleceniu
(``api/candidate_referrals``). Serwer strony wysyła formularz na
``POST /api/public/website-referrals`` (``api/public_website_applications``).

Co się dzieje z polecaną osobą:

* **nowa** — kandydat powstaje od razu ze źródłem „polecenie” i zdarzeniem
  źródła „Polecenie” (kto polecił), bez CV i bez zgód: zgoda z formularza jest
  zgodą polecającego na jego dane, a polecany wie o poleceniu tylko według
  oświadczenia polecającego. Wpis w kolejce „Zgłoszenia” wskazuje profil;
* **już w bazie** (ten sam e-mail albo profil LinkedIn) — profil bez zmian
  (P0-CAND-01), polecenie i wpis w kolejce wskazują istniejącego kandydata;
* **adres usunięty wcześniej na prośbę osoby** — profilu nie zakładamy z cudzego
  polecenia. Wpis w kolejce bez dopasowania, „Utwórz kandydata” pyta wtedy
  o potwierdzenie (``erased_email_conflict``).

Polecanej osobie NEXUS nic nie wysyła (żadnego maila, zaproszenia ani odczytu
CV): kontakt należy do rekrutera, który dzwoni za jej zgodą. Potwierdzenie do
polecającego wysyła strona. Odpowiedź nie mówi, czy osoba była w bazie.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.application_submission import (
    ApplicationSubmission,
    ApplicationSubmissionStatus,
)
from app.models.candidate import Candidate, CandidateSource, CandidateStatus
from app.models.candidate_source_event import CandidateSourceEvent, SourceChannel
from app.models.website_intake import CandidateReferral
from app.services import website_forms as forms
from app.services import website_intake_schema as schema
from app.services.candidate_name_rules import without_name_markers
from app.services.linkedin_url import normalize_linkedin_url
from app.services.public_apply import PLACEHOLDER_NAME, field_error
from app.services.website_trainer_applications import consent_rows, live_contract

logger = logging.getLogger(__name__)

SOURCE_LABEL = "polecenie"
VIA = "website_referral"
NOTE_MAX = 500  # ``candidate_source_events.note``


@dataclass(frozen=True)
class Referral:
    referrer_name: str
    referrer_email: str
    referred_name: str
    referred_email: Optional[str]
    referred_linkedin: Optional[str]
    referred_role: Optional[str]
    statement: str
    consents: tuple[str, ...]


def parse_form(form: Any) -> Referral:
    """Formularz multipart → polecenie albo 422 przy polu (kształt FastAPI)."""
    referrer_name = forms.required(
        form, "referrer_name", schema.NAME_MAX, "Podaj swoje imię i nazwisko."
    )
    referrer_email = forms.required_email(
        form, "referrer_email", schema.EMAIL_MAX, "Podaj swój adres e-mail."
    )
    referred_name = forms.required(
        form,
        "referred_name",
        schema.NAME_MAX,
        "Podaj imię i nazwisko polecanej osoby.",
    )
    contact = forms.required(
        form,
        "referred_contact",
        schema.LINKEDIN_MAX,
        "Podaj e-mail albo profil LinkedIn polecanej osoby.",
    )
    referred_email = forms.email(contact) if "@" in contact else None
    referred_linkedin = None if referred_email else normalize_linkedin_url(contact)
    if referred_email is None and referred_linkedin is None:
        raise field_error(
            "referred_contact",
            "Wpisz e-mail albo link do profilu, np. linkedin.com/in/ewa.",
            contact[:50],
        )
    if referred_email and referred_email.lower() == referrer_email.lower():
        raise field_error(
            "referred_contact",
            "To adres polecającego. Podaj kontakt do osoby polecanej.",
        )
    statement = forms.required(
        form,
        "knows",
        schema.CONSENT_MAX,
        "Brak oświadczenia, że polecana osoba wie o poleceniu.",
    )
    return Referral(
        referrer_name=referrer_name,
        referrer_email=referrer_email,
        referred_name=referred_name,
        referred_email=referred_email,
        referred_linkedin=referred_linkedin,
        referred_role=forms.text(form, "referred_role", schema.ROLE_MAX),
        statement=statement,
        consents=forms.consents(form, "consent", schema.CONSENT_MAX),
    )


def split_name(full_name: str) -> tuple[str, str]:
    """„Ewa Maria Nowak” → („Ewa Maria”, „Nowak”); jedno słowo → nazwisko „Nieznane”."""
    parts = without_name_markers(full_name).split()
    if len(parts) < 2:
        return (parts[0] if parts else PLACEHOLDER_NAME), PLACEHOLDER_NAME
    return " ".join(parts[:-1]), parts[-1]


async def _matching_candidate(db: AsyncSession, ref: Referral) -> Optional[Candidate]:
    if ref.referred_email:
        return await db.scalar(
            select(Candidate)
            .where(
                func.lower(func.btrim(Candidate.email)) == ref.referred_email.lower()
            )
            .order_by(Candidate.id)
            .limit(1)
        )
    slug = (ref.referred_linkedin or "").rsplit("/", 1)[-1].lower()
    if not slug:
        return None
    return await db.scalar(
        select(Candidate)
        .where(Candidate.linkedin_slug != "", Candidate.linkedin_slug == slug)
        .order_by(Candidate.id)
        .limit(1)
    )


async def _referrer_candidate_id(db: AsyncSession, email: str) -> Optional[int]:
    return await db.scalar(
        select(Candidate.id)
        .where(func.lower(func.btrim(Candidate.email)) == email.lower())
        .order_by(Candidate.id)
        .limit(1)
    )


async def _already_referred(
    db: AsyncSession, ref: Referral, candidate_id: Optional[int]
) -> bool:
    """Ten sam polecający już polecił tę osobę — drugie wysłanie nic nie dubluje."""
    same_person = []
    if candidate_id is not None:
        same_person.append(CandidateReferral.candidate_id == candidate_id)
    if ref.referred_email:
        same_person.append(
            func.lower(CandidateReferral.referred_email) == ref.referred_email.lower()
        )
    if ref.referred_linkedin:
        same_person.append(CandidateReferral.referred_linkedin == ref.referred_linkedin)
    found = await db.scalar(
        select(CandidateReferral.id)
        .where(
            func.lower(CandidateReferral.referrer_email) == ref.referrer_email.lower(),
            or_(*same_person),
        )
        .limit(1)
    )
    return found is not None


def source_note(ref: Referral) -> str:
    note = f"Polecenie ze strony WWW: {ref.referrer_name} ({ref.referrer_email})"
    return note[:NOTE_MAX]


def queue_message(
    ref: Referral, *, existing: bool, erased: bool, referrer_contract: bool
) -> str:
    """Opis wpisu w kolejce „Zgłoszenia” — rekruter widzi go na karcie."""
    who = "konsultant B2B" if referrer_contract else "osoba spoza B2B"
    head = f"Polecenie ze strony WWW od: {ref.referrer_name} ({ref.referrer_email}, {who})."
    if erased:
        body = (
            "Ten adres był usunięty na prośbę osoby, więc z polecenia nie "
            "założyliśmy profilu. Utwórz kandydata tylko po rozmowie z nią."
        )
    elif existing:
        body = "Polecona osoba jest już w bazie — profil bez zmian."
    else:
        body = "Nowa osoba — profil założony ze źródłem „polecenie”, bez CV."
    role = f"Czym się zajmuje: {ref.referred_role}." if ref.referred_role else None
    contact = (
        "Polecający oświadcza, że ta osoba wie o poleceniu i zgadza się na kontakt. "
        "Nie wysłaliśmy jej żadnego maila — pierwszy kontakt należy do Ciebie."
    )
    return " ".join(part for part in (head, body, role, contact) if part)


def _payload(ref: Referral, *, referral_id: int) -> dict[str, Any]:
    return {
        "via": VIA,
        "source": "polecenie",
        "referral_id": referral_id,
        "referrer": {"name": ref.referrer_name, "email": ref.referrer_email},
        "referred": {
            "name": ref.referred_name,
            "email": ref.referred_email,
            "linkedin": ref.referred_linkedin,
            "role": ref.referred_role,
        },
    }


async def _create_candidate(db: AsyncSession, ref: Referral) -> Optional[Candidate]:
    """Nowy kandydat albo ``None``, gdy ten sam adres zapisało w międzyczasie inne
    żądanie (dwa polecenia tej samej osoby naraz; unikat ``candidates.email``)."""
    from app.services.index_outbox_service import schedule_or_embed_candidate

    first, last = split_name(ref.referred_name)
    candidate = Candidate(
        name=first,
        lastname=last,
        email=ref.referred_email,
        linkedin=ref.referred_linkedin,
        source=SOURCE_LABEL,
        source_enum=CandidateSource.referral,
        status=CandidateStatus.active,
        created_by=None,
        preferences={},
    )
    try:
        async with db.begin_nested():
            db.add(candidate)
            await db.flush()
    except IntegrityError:
        return None
    # Savepoint — awaria intencji indeksu nie cofa polecenia.
    try:
        async with db.begin_nested():
            await schedule_or_embed_candidate(candidate.id, db)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "[website-referral] index intent failed candidate=%s: %s",
            candidate.id,
            type(exc).__name__,
        )
    return candidate


async def submit(db: AsyncSession, ref: Referral) -> dict:
    """Polecenie, kandydat i wpis w kolejce; commit w środku."""
    from app.services.candidate_erasure_leftovers import email_was_erased

    received = {"ok": True, "status": "received"}
    existing = await _matching_candidate(db, ref)
    if await _already_referred(db, ref, existing.id if existing else None):
        return received

    erased = (
        existing is None
        and ref.referred_email is not None
        and await email_was_erased(db, ref.referred_email.lower())
    )
    candidate = existing
    if candidate is None and not erased:
        candidate = await _create_candidate(db, ref)
        if candidate is None:
            existing = candidate = await _matching_candidate(db, ref)

    # Polecający konsultant: kontrakt (premia do faktury) i jego profil z kontraktu,
    # bo adres w kartotece kandydata bywa inny niż w kontrakcie.
    contract = await live_contract(db, ref.referrer_email)
    referrer_contract_id = contract[0] if contract else None
    referrer_candidate_id = (contract[1] if contract else None) or (
        await _referrer_candidate_id(db, ref.referrer_email)
    )
    now = datetime.now(timezone.utc)
    referral = CandidateReferral(
        referrer_name=ref.referrer_name,
        referrer_email=ref.referrer_email,
        referrer_candidate_id=referrer_candidate_id,
        referrer_contract_id=referrer_contract_id,
        referred_name=ref.referred_name,
        referred_email=ref.referred_email,
        referred_linkedin=ref.referred_linkedin,
        referred_role=ref.referred_role,
        candidate_id=candidate.id if candidate else None,
        was_in_database=existing is not None,
        statement_text=ref.statement,
        consents=consent_rows(ref.consents),
        consented_at=now,
    )
    db.add(referral)
    await db.flush()

    first, last = split_name(ref.referred_name)
    submission = ApplicationSubmission(
        invite_link_token_sha256=None,
        job_id=None,
        status=ApplicationSubmissionStatus.pending_review.value,
        submitted_first_name=first[:100],
        submitted_last_name=last[:100],
        submitted_email=ref.referred_email or "",
        submitted_linkedin=ref.referred_linkedin,
        submitted_message=queue_message(
            ref,
            existing=existing is not None,
            erased=erased,
            referrer_contract=referrer_contract_id is not None,
        ),
        matched_candidate_id=candidate.id if candidate else None,
        raw_payload=_payload(ref, referral_id=referral.id),
    )
    db.add(submission)
    await db.flush()
    referral.submission_id = submission.id

    if candidate is not None:
        db.add(
            CandidateSourceEvent(
                candidate_id=candidate.id,
                channel=SourceChannel.referral,
                note=source_note(ref),
                captured_at=now,
            )
        )
        db.add(
            Activity(
                entity_type="candidate",
                entity_id=candidate.id,
                action="referred_via_website",
                user_id=None,
                details={
                    "via": VIA,
                    "referral_id": referral.id,
                    "submission_id": submission.id,
                    "was_duplicate": existing is not None,
                },
            )
        )
    await db.commit()
    logger.info(
        "[website-referral] referral id=%s existing=%s erased=%s",
        referral.id,
        existing is not None,
        erased,
    )
    return received


# ── Lista poleceń (rekruter, Finanse) ────────────────────────────────────────

#: Premia 1–5 tys. zł zależnie od profilu (Artur, 28.11.2026). Baza pilnuje
#: tylko „> 0”, żeby zmiana widełek nie wymagała migracji.
BONUS_MIN = Decimal("1000")
BONUS_MAX = Decimal("5000")
LIST_LIMIT = 300

#: Rekruter: nowe → rozmowa → zaczął projekt (premia należna) / odrzucone.
#: „Wypłacona” ustawiają Finanse (``mark_paid``), potem polecenie jest zamknięte.
TRANSITIONS: dict[str, frozenset[str]] = {
    "new": frozenset({"contacted", "rejected"}),
    "contacted": frozenset({"started", "rejected"}),
    "started": frozenset({"contacted", "rejected"}),
    "rejected": frozenset({"new"}),
    "paid": frozenset(),
}


class ReferralChangeError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def serialize(row: CandidateReferral) -> dict[str, Any]:
    return {
        "id": row.id,
        "referrer_name": row.referrer_name,
        "referrer_email": row.referrer_email,
        "referrer_candidate_id": row.referrer_candidate_id,
        "referrer_contract_id": row.referrer_contract_id,
        "referred_name": row.referred_name,
        "referred_email": row.referred_email,
        "referred_linkedin": row.referred_linkedin,
        "referred_role": row.referred_role,
        "candidate_id": row.candidate_id,
        "submission_id": row.submission_id,
        "was_in_database": row.was_in_database,
        "statement_text": row.statement_text,
        "status": row.status,
        "bonus_amount": (
            str(row.bonus_amount) if row.bonus_amount is not None else None
        ),
        "status_note": row.status_note,
        "status_changed_at": (
            row.status_changed_at.isoformat() if row.status_changed_at else None
        ),
        "created_at": row.created_at.isoformat(),
    }


async def list_referrals(
    db: AsyncSession, *, status: Optional[str]
) -> list[dict[str, Any]]:
    stmt = select(CandidateReferral)
    if status:
        stmt = stmt.where(CandidateReferral.status == status)
    rows = await db.scalars(
        stmt.order_by(CandidateReferral.created_at.desc()).limit(LIST_LIMIT)
    )
    return [serialize(row) for row in rows]


async def _locked(db: AsyncSession, referral_id: int) -> CandidateReferral:
    row = await db.scalar(
        select(CandidateReferral)
        .where(CandidateReferral.id == referral_id)
        .with_for_update()
    )
    if row is None:
        raise ReferralChangeError(404, "Nie ma takiego polecenia.")
    return row


def check_bonus(amount: Optional[Decimal]) -> Optional[Decimal]:
    if amount is None:
        return None
    if not amount.is_finite() or amount < BONUS_MIN or amount > BONUS_MAX:
        raise ReferralChangeError(
            422, f"Premia za polecenie to od {BONUS_MIN:.0f} do {BONUS_MAX:.0f} zł."
        )
    return amount.quantize(Decimal("0.01"))


async def update_referral(
    db: AsyncSession,
    referral_id: int,
    *,
    changes: dict[str, Any],
    actor_user_id: int,
) -> CandidateReferral:
    """Status, kwota premii i notatka. Polecenie wypłacone jest zamknięte."""
    row = await _locked(db, referral_id)
    if row.status == "paid":
        raise ReferralChangeError(
            409, "Premia jest już wypłacona — polecenie jest zamknięte."
        )
    if "bonus_amount" in changes:
        row.bonus_amount = check_bonus(changes["bonus_amount"])
    status = changes.get("status")
    if status is not None and status != row.status:
        if status not in TRANSITIONS[row.status]:
            raise ReferralChangeError(
                409, "Tego polecenia nie da się przenieść do wybranego stanu."
            )
        row.status = status
        row.status_changed_by = actor_user_id
        row.status_changed_at = datetime.now(timezone.utc)
    if row.status == "started" and row.bonus_amount is None:
        raise ReferralChangeError(
            422, "Wpisz kwotę premii — należy się, gdy polecona osoba zaczęła projekt."
        )
    if changes.get("note") is not None:
        row.status_note = changes["note"]
    await db.flush()
    # ``updated_at`` liczy baza (``onupdate``): bez odświeżenia odczyt po flush
    # sięgnąłby po wygaszone pole poza kontekstem async.
    await db.refresh(row)
    return row


async def mark_paid(
    db: AsyncSession, referral_id: int, *, actor_user_id: int
) -> CandidateReferral:
    row = await _locked(db, referral_id)
    if row.status != "started" or row.bonus_amount is None:
        raise ReferralChangeError(
            409, "Wypłacić można tylko premię za osobę, która zaczęła projekt."
        )
    row.status = "paid"
    row.status_changed_by = actor_user_id
    row.status_changed_at = datetime.now(timezone.utc)
    await db.flush()
    # ``updated_at`` liczy baza (``onupdate``): bez odświeżenia odczyt po flush
    # sięgnąłby po wygaszone pole poza kontekstem async.
    await db.refresh(row)
    return row
