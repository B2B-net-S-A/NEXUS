"""„Zostań trenerem” ze strony B2B Network — zgłoszenie od kogokolwiek z rynku.

Decyzja Artura z 28.11.2026: trenerem może zgłosić się osoba spoza B2B, tylko
z firmą (rozliczenie fakturą), umowa szkoleniowa bez zmian. Serwer strony
wysyła formularz na ``POST /api/public/website-trainer-applications``
(``api/public_website_applications``), a zgłoszenie trafia na listę
„Kandydaci na trenerów” w Szkolenia → „Zgłoszenia trenerów”, gdzie decyduje TCM:
nowe → rozmowa → w bazie trenerów / odrzucone.

Jedno zgłoszenie na adres e-mail: ponowne wysłanie poprawia treść tego samego
wiersza (jak drugie wysłanie w panelu konsultanta), a zgłoszenie odrzucone
wraca do „nowych”, bo to nowa prośba tej osoby. Status rozmowy i bazy zostaje.

Potwierdzenie do nadawcy wysyła strona; NEXUS nie wysyła żadnego maila.
Odpowiedź nie mówi, czy adres był już na liście.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract import Contract, ContractStatus
from app.models.website_intake import MarketTrainerApplication
from app.services import website_forms as forms
from app.services import website_intake_schema as schema
from app.services.public_apply import field_error

logger = logging.getLogger(__name__)

#: Kontrakt, który działa — trener z rynku bywa naszym konsultantem.
_LIVE = (ContractStatus.active, ContractStatus.ending)


@dataclass(frozen=True)
class TrainerApplication:
    full_name: str
    email: str
    linkedin: Optional[str]
    topics: tuple[str, ...]
    other_topic: Optional[str]
    first_training: str
    experience: str
    sample_url: Optional[str]
    consents: tuple[str, ...]


def _topics(form: Any) -> tuple[str, ...]:
    picked: list[str] = []
    for value in form.getlist("topic"):
        if not isinstance(value, str):
            raise field_error("topic", "Pole musi być tekstem.")
        topic = value.strip()
        if not topic:
            continue
        if topic not in schema.TRAINER_TOPICS:
            raise field_error("topic", "Nieznany temat.", topic[:50])
        if topic in picked:
            raise field_error("topic", "Temat powtórzony.", topic)
        picked.append(topic)
    return tuple(picked)


def parse_form(form: Any) -> TrainerApplication:
    """Formularz multipart → zgłoszenie albo 422 przy polu (kształt FastAPI)."""
    full_name = forms.required(
        form, "full_name", schema.NAME_MAX, "Podaj imię i nazwisko."
    )
    email = forms.required_email(form, "email", schema.EMAIL_MAX, "Podaj adres e-mail.")
    topics = _topics(form)
    other_topic = forms.text(form, "other_topic", schema.TOPIC_MAX)
    if not topics and other_topic is None:
        raise field_error("topic", "Wybierz co najmniej jeden temat albo wpisz własny.")
    return TrainerApplication(
        full_name=full_name,
        email=email,
        linkedin=forms.text(form, "linkedin", schema.LINKEDIN_MAX),
        topics=topics,
        other_topic=other_topic,
        first_training=forms.required(
            form,
            "first_training",
            schema.FIRST_TRAINING_MAX,
            "Napisz, jakie szkolenie możesz poprowadzić.",
        ),
        experience=forms.required(
            form,
            "experience",
            schema.EXPERIENCE_MAX,
            "Opisz krótko swoje doświadczenie trenerskie.",
            multiline=True,
        ),
        sample_url=forms.http_url(form, "sample_url", schema.URL_MAX),
        consents=forms.consents(form, "consent", schema.CONSENT_MAX),
    )


def consent_rows(texts: tuple[str, ...]) -> list[dict[str, str]]:
    return [
        {"text": text, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
        for text in texts
    ]


async def live_contract(
    db: AsyncSession, email: str
) -> Optional[tuple[int, Optional[int]]]:
    """Najnowszy działający kontrakt pod tym adresem: (id, kandydat) albo ``None``."""
    row = (
        await db.execute(
            select(Contract.id, Contract.candidate_id)
            .where(
                func.lower(Contract.candidate_email) == email.lower(),
                Contract.status.in_(_LIVE),
            )
            .order_by(Contract.start_date.desc().nulls_last(), Contract.id.desc())
            .limit(1)
        )
    ).first()
    return (row.id, row.candidate_id) if row is not None else None


async def live_contract_id(db: AsyncSession, email: str) -> Optional[int]:
    """Najnowszy działający kontrakt pod tym adresem (konsultant B2B) albo ``None``."""
    found = await live_contract(db, email)
    return found[0] if found else None


def _fill(
    row: MarketTrainerApplication, app: TrainerApplication, now: datetime
) -> None:
    row.full_name = app.full_name
    row.linkedin = app.linkedin
    row.topics = list(app.topics)
    row.other_topic = app.other_topic
    row.first_training = app.first_training
    row.experience = app.experience
    row.sample_url = app.sample_url
    row.consents = consent_rows(app.consents)
    row.consented_at = now


async def _existing(db: AsyncSession, email: str) -> Optional[MarketTrainerApplication]:
    return await db.scalar(
        select(MarketTrainerApplication)
        .where(func.lower(MarketTrainerApplication.email) == email.lower())
        .with_for_update()
    )


def _resubmit(
    row: MarketTrainerApplication, app: TrainerApplication, now: datetime
) -> None:
    _fill(row, app, now)
    row.submissions = (row.submissions or 1) + 1
    if row.status == "rejected":
        row.status = "new"
        row.status_changed_by = None
        row.status_changed_at = now


async def submit(db: AsyncSession, app: TrainerApplication) -> dict:
    """Zapis zgłoszenia; commit w środku. Odpowiedź bez śladu powtórki."""
    now = datetime.now(timezone.utc)
    contract_id = await live_contract_id(db, app.email)
    row = await _existing(db, app.email)
    if row is None:
        row = MarketTrainerApplication(email=app.email, contract_id=contract_id)
        _fill(row, app, now)
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:
            # Dwa wysłania naraz z tego samego adresu: drugie poprawia pierwsze.
            row = await _existing(db, app.email)
            if row is None:  # pragma: no cover — unikat bez wiersza
                raise
            _resubmit(row, app, now)
    else:
        _resubmit(row, app, now)
    if contract_id is not None:
        row.contract_id = contract_id
    await db.commit()
    logger.info(
        "[website-trainer] application id=%s submissions=%s contract=%s",
        row.id,
        row.submissions,
        bool(row.contract_id),
    )
    return {"ok": True, "status": "received"}


# ── Lista „Kandydaci na trenerów” (TCM) ──────────────────────────────────────

#: nowe → rozmowa → w bazie trenerów / odrzucone (decyzja Artura 28.11.2026).
#: Odrzucone da się przywrócić, a trenera z bazy wycofać.
TRANSITIONS: dict[str, frozenset[str]] = {
    "new": frozenset({"interview", "rejected"}),
    "interview": frozenset({"accepted", "rejected"}),
    "accepted": frozenset({"rejected"}),
    "rejected": frozenset({"new"}),
}
LIST_LIMIT = 300


class StatusChangeError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def serialize(row: MarketTrainerApplication) -> dict[str, Any]:
    return {
        "id": row.id,
        "full_name": row.full_name,
        "email": row.email,
        "linkedin": row.linkedin,
        "topics": list(row.topics or []),
        "other_topic": row.other_topic,
        "first_training": row.first_training,
        "experience": row.experience,
        "sample_url": row.sample_url,
        "contract_id": row.contract_id,
        "status": row.status,
        "status_note": row.status_note,
        "status_changed_at": (
            row.status_changed_at.isoformat() if row.status_changed_at else None
        ),
        "submissions": row.submissions,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


async def list_applications(
    db: AsyncSession, *, status: Optional[str]
) -> list[dict[str, Any]]:
    stmt = select(MarketTrainerApplication)
    if status:
        stmt = stmt.where(MarketTrainerApplication.status == status)
    rows = await db.scalars(
        stmt.order_by(MarketTrainerApplication.updated_at.desc()).limit(LIST_LIMIT)
    )
    return [serialize(row) for row in rows]


async def set_status(
    db: AsyncSession,
    application_id: int,
    *,
    status: str,
    note: Optional[str],
    actor_user_id: int,
) -> MarketTrainerApplication:
    row = await db.scalar(
        select(MarketTrainerApplication)
        .where(MarketTrainerApplication.id == application_id)
        .with_for_update()
    )
    if row is None:
        raise StatusChangeError(404, "Nie ma takiego zgłoszenia.")
    if status not in TRANSITIONS.get(row.status, frozenset()):
        raise StatusChangeError(
            409, "Tego zgłoszenia nie da się przenieść do wybranego stanu."
        )
    row.status = status
    row.status_changed_by = actor_user_id
    row.status_changed_at = datetime.now(timezone.utc)
    if note is not None:
        row.status_note = note
    await db.flush()
    # ``updated_at`` liczy baza (``onupdate``): bez odświeżenia odczyt po flush
    # sięgnąłby po wygaszone pole poza kontekstem async.
    await db.refresh(row)
    return row
