"""Szkolenie od zamówienia do biblioteki: stany, walidacja i widoki dla ról.

Kolejność dla trenera z umową B2B (decyzje Artura 13.11.2026):

1. TCM zakłada zamówienie (``draft``) i wysyła je trenerowi (``ordered``).
2. Trener uzupełnia agendę, materiały własne i wycenę A–E (``quoted``).
3. TCM przyjmuje wycenę (``accepted``) albo odsyła z uwagą (``returned``).
4. Umowa z Zał. 1 i Zał. 2, podpis kwalifikowany trenera, potem reprezentanta
   (``trainer_signed`` → ``signed``; ``agreement.py``, ``signing.py``).
5. Trener przekazuje pliki z Zał. 1 pkt 4; TCM przyjmuje albo zwraca do poprawy
   z terminem 3 dni roboczych (§ 11 ust. 4). Komplet przyjęty = ``invoice_ready_at``.
6. Finanse oznaczają zapłatę (``paid_at``). Dopiero wtedy przechodzą prawa (§ 8 ust. 3),
   więc dopiero wtedy szkolenie trenera B2B może wejść do biblioteki.

Szkolenie prowadzone przez pracownika nie ma umowy B2B: po wysłaniu jest od razu
``signed`` i do biblioteki wchodzi bez zapłaty.

Funkcje nie robią commita; transakcję kończy trasa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.contract import Contract
from app.models.training import (
    Training,
    TrainingAttendance,
    TrainingFeedback,
    TrainingFile,
    TrainingRegistration,
    TrainingTranscript,
)
from app.models.user import User
from app.services.candidate_followups import add_business_days
from app.services.trainings.errors import TrainingError
from app.services.trainings_schema import (
    AGENDA_MAX,
    DELIVERABLE_KEYS,
    DESCRIPTION_MAX,
    NOTE_MAX,
    TEXT_MAX,
    TITLE_MAX,
)

#: Zał. 1 pkt 4 — etykiety i domyślne formaty, które TCM może zmienić w zamówieniu.
DELIVERABLE_LABELS: dict[str, str] = {
    "materials": "Materiały dla uczestników",
    "presentation": "Prezentacja",
    "audio": "Pliki audio",
    "other": "Inne pliki",
}
DEFAULT_FORMATS: dict[str, str] = {
    "materials": "PDF",
    "presentation": "PPTX do edycji i PDF dla uczestników",
    "audio": "gotowy plik MP3 albo M4A, jeden na część",
    "other": "",
}
#: Pozycje wynagrodzenia A–E (§ 7 ust. 3, Zał. 1 pkt 6) i element, od którego zależą.
FEES: tuple[tuple[str, str, Optional[str]], ...] = (
    ("fee_prep", "A. Przygotowanie programu i materiałów szkoleniowych", None),
    ("fee_delivery", "B. Przeprowadzenie szkolenia", None),
    ("fee_presentation", "C. Przygotowanie i przekazanie prezentacji", "presentation"),
    ("fee_audio", "D. Przygotowanie i przekazanie plików audio", "audio"),
    ("fee_rights", "E. Przeniesienie autorskich praw majątkowych", None),
)
FEE_MAX = Decimal("1000000")
FIX_DAYS = 3
EDITABLE_ORDER = ("draft", "ordered", "quoted", "returned")
CANCELLABLE = ("draft", "ordered", "quoted", "returned", "accepted", "trainer_signed")
OPEN_FOR_FILES = ("signed",)

STATUS_LABELS: dict[str, str] = {
    "draft": "Szkic zamówienia",
    "ordered": "Czeka na wycenę trenera",
    "quoted": "Wycena do decyzji",
    "returned": "Wycena odesłana do poprawy",
    "accepted": "Umowa do podpisu trenera",
    "trainer_signed": "Umowa czeka na podpis B2B Network",
    "signed": "Umowa podpisana",
    "cancelled": "Anulowane",
}

#: Szkolenie pracownika nie ma umowy: po wysłaniu jest ``signed``, ale „Umowa podpisana”
#: myliło TCM na liście (analiza 13.11.2026), więc etykieta zależy od prowadzącego.
EMPLOYEE_READY_LABEL = "Gotowe do szkolenia"

NOT_FOUND = "Nie ma takiego szkolenia."
WRONG_STATUS = "To szkolenie jest już na innym etapie. Odśwież stronę."


def _clean(value: Optional[str], limit: int) -> str:
    return (value or "").replace("\x00", "").strip()[:limit]


def _iso(value: Optional[datetime | date]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def status_label(training: Training) -> str:
    if training.status == "signed" and training.trainer_kind == "employee":
        return EMPLOYEE_READY_LABEL
    return STATUS_LABELS[training.status]


def _wrong_status() -> TrainingError:
    return TrainingError(409, WRONG_STATUS, "wrong_status")


# ── Odczyt ───────────────────────────────────────────────────────────────────


async def get(db: AsyncSession, training_id: int, *, lock: bool = False) -> Training:
    query = select(Training).where(Training.id == training_id)
    if lock:
        query = query.with_for_update()
    training = await db.scalar(query)
    if training is None:
        raise TrainingError(404, NOT_FOUND, "not_found")
    return training


async def for_trainer(
    db: AsyncSession,
    training_id: int,
    contract_ids: Iterable[int],
    *,
    lock: bool = False,
) -> Training:
    """Szkolenie tego trenera; cudze i szkic wyglądają jak brak szkolenia."""

    training = await get(db, training_id, lock=lock)
    if (
        training.trainer_contract_id not in tuple(contract_ids)
        or training.status == "draft"
    ):
        raise TrainingError(404, NOT_FOUND, "not_found")
    return training


async def files_of(db: AsyncSession, training_id: int) -> list[TrainingFile]:
    return list(
        (
            await db.scalars(
                select(TrainingFile)
                .where(TrainingFile.training_id == training_id)
                .order_by(TrainingFile.uploaded_at, TrainingFile.id)
            )
        ).all()
    )


def fee_total(training: Training) -> Optional[Decimal]:
    values = [getattr(training, key) for key, _label, _needs in FEES]
    if all(value is None for value in values):
        return None
    return sum((value or Decimal(0) for value in values), Decimal(0))


def deliverable_keys(training: Training) -> list[str]:
    return [item["key"] for item in training.deliverables if isinstance(item, dict)]


def _required_keys(training: Training) -> list[str]:
    return [
        item["key"]
        for item in training.deliverables
        if isinstance(item, dict) and item.get("required", True)
    ]


async def contract_person_name(db: AsyncSession, contract_id: int) -> str:
    row = (
        await db.execute(
            select(Candidate.name, Candidate.lastname)
            .join(Contract, Contract.candidate_id == Candidate.id)
            .where(Contract.id == contract_id)
        )
    ).first()
    return " ".join(part for part in row if part).strip() if row else ""


async def trainer_name(db: AsyncSession, training: Training) -> str:
    if training.trainer_user_id:
        return (
            await db.scalar(
                select(User.name).where(User.id == training.trainer_user_id)
            )
            or ""
        )
    if training.partner.get("full_name"):
        return str(training.partner["full_name"])
    if training.trainer_contract_id:
        return await contract_person_name(db, training.trainer_contract_id)
    return ""


def _file_row(item: TrainingFile) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "deliverable_key": item.deliverable_key,
        "status": item.status,
        "file_name": item.file_name,
        "content_type": item.content_type,
        "size_bytes": item.size_bytes,
        "uploaded_at": _iso(item.uploaded_at),
        "review_note": item.review_note or None,
        "reviewed_at": _iso(item.reviewed_at),
        "fix_due_on": _iso(item.fix_due_on),
        "for_participants": item.for_participants,
    }


def handover(training: Training, files: list[TrainingFile]) -> list[dict[str, Any]]:
    """Pozycje Zał. 1 pkt 4 z najnowszym plikiem każdej i jej stanem."""

    rows = []
    for item in training.deliverables:
        if not isinstance(item, dict):
            continue
        key = item["key"]
        current = [
            f
            for f in files
            if f.kind == "deliverable"
            and f.deliverable_key == key
            and f.status != "replaced"
        ]
        statuses = {f.status for f in current}
        if not current:
            state = "missing"
        elif "returned" in statuses:
            state = "returned"
        elif statuses == {"accepted"}:
            state = "accepted"
        else:
            state = "submitted"
        rows.append(
            {
                "key": key,
                "label": item.get("label") or DELIVERABLE_LABELS[key],
                "format": item.get("format", ""),
                "due_days": item.get("due_days"),
                "required": item.get("required", True),
                "state": state,
                "files": [_file_row(f) for f in current],
            }
        )
    return rows


def _fees(training: Training) -> dict[str, Any]:
    return {
        "items": [
            {
                "key": key,
                "label": label,
                "needs": needs,
                "amount": str(getattr(training, key))
                if getattr(training, key) is not None
                else None,
            }
            for key, label, needs in FEES
        ],
        "total": str(fee_total(training)) if fee_total(training) is not None else None,
    }


def _order(training: Training) -> dict[str, Any]:
    return {
        "title": training.title,
        "topic": training.topic,
        "description": training.description,
        "session_date": _iso(training.session_date),
        "time_from": training.time_from,
        "time_to": training.time_to,
        "duration_minutes": training.duration_minutes,
        "platform": training.platform,
        "expected_participants": training.expected_participants,
        "quote_due_on": _iso(training.quote_due_on),
        "participant_materials": training.participant_materials,
        "deliverables": training.deliverables,
        "knowledge_test": training.knowledge_test,
        "extra_terms": training.extra_terms,
        "seat_limit": training.seat_limit,
    }


def _quote(training: Training) -> dict[str, Any]:
    return {
        "agenda": training.agenda,
        "own_materials": training.own_materials,
        "third_party_materials": training.third_party_materials,
        "quote_note": training.quote_note,
        "return_note": training.return_note or None,
        "quoted_at": _iso(training.quoted_at),
    }


def _agreement(training: Training) -> dict[str, Any]:
    return {
        "number": training.agreement_number or None,
        "generated_at": _iso(training.agreement_generated_at),
        "trainer_signed_at": _iso(training.trainer_signed_at),
        "company_signed_at": _iso(training.company_signed_at),
    }


def _payment(training: Training) -> dict[str, Any]:
    return {
        "invoice_ready_at": _iso(training.invoice_ready_at),
        "paid_at": _iso(training.paid_at),
    }


def chapters(training: Training) -> list[dict[str, Any]]:
    """Rozdziały nagrania z agendy: początek modułu = suma minut poprzednich."""

    start = 0
    rows = []
    for item in training.agenda:
        if not isinstance(item, dict):
            continue
        rows.append({"title": item.get("title", ""), "start_minute": start})
        start += int(item.get("minutes") or 0)
    return rows


def can_publish(training: Training) -> bool:
    if training.status != "signed":
        return False
    if training.trainer_kind == "employee":
        return True
    return training.paid_at is not None


async def staff_view(
    db: AsyncSession, training: Training, *, show_fees: bool
) -> dict[str, Any]:
    # Trasa robi commit przed widokiem, a po nim atrybuty wygasają (async = bez
    # leniwego doczytania), więc najpierw świeży odczyt wiersza.
    await db.refresh(training)
    files = await files_of(db, training.id)
    registrations = await db.scalar(
        select(func.count())
        .select_from(TrainingRegistration)
        .where(TrainingRegistration.training_id == training.id)
    )
    attendance = await db.scalar(
        select(func.count())
        .select_from(TrainingAttendance)
        .where(TrainingAttendance.training_id == training.id)
    )
    return {
        "id": training.id,
        "status": training.status,
        "status_label": status_label(training),
        "trainer_kind": training.trainer_kind,
        "trainer_contract_id": training.trainer_contract_id,
        "trainer_user_id": training.trainer_user_id,
        "trainer_name": await trainer_name(db, training),
        "application_id": training.application_id,
        "join_url": training.join_url,
        "order": _order(training),
        "quote": _quote(training),
        "fees": _fees(training) if show_fees else None,
        "agreement": _agreement(training),
        "payment": _payment(training),
        "handover": handover(training, files),
        "files": [_file_row(f) for f in files],
        "registrations": registrations or 0,
        "attendance": attendance or 0,
        "teams": {
            "status": training.teams_status or None,
            "error": training.teams_error or None,
            "synced_at": _iso(training.teams_synced_at),
            "recording": training.recording_status or None,
        },
        "shared_registered_at": _iso(training.shared_registered_at),
        "feedback": await feedback_summary(db, training.id, with_comments=True),
        "transcript": await db.get(TrainingTranscript, training.id) is not None,
        "published_at": _iso(training.published_at),
        "can_publish": can_publish(training),
        "chapters": chapters(training),
        "cancelled_at": _iso(training.cancelled_at),
        "cancel_reason": training.cancel_reason or None,
        "created_at": _iso(training.created_at),
        "updated_at": _iso(training.updated_at),
    }


async def trainer_view(db: AsyncSession, training: Training) -> dict[str, Any]:
    """Widok trenera w panelu: jego kwoty tak, uwagi wewnętrzne i zapisy nie."""

    await db.refresh(training)
    files = await files_of(db, training.id)
    return {
        "id": training.id,
        "status": training.status,
        "status_label": status_label(training),
        "order": _order(training),
        "quote": _quote(training),
        "fees": _fees(training),
        "agreement": _agreement(training),
        "payment": _payment(training),
        "handover": handover(training, files),
        "invoices": [_file_row(f) for f in files if f.kind == "invoice"],
        # Link do spotkania trener dostaje po podpisie umowy, bo dopiero wtedy prowadzi
        # (do 13.11.2026 panel pisał „link damy my”, a linku nie było nigdzie).
        "join_url": (training.join_url or None)
        if training.status == "signed"
        else None,
        "registrations": await db.scalar(
            select(func.count())
            .select_from(TrainingRegistration)
            .where(TrainingRegistration.training_id == training.id)
        )
        or 0,
        "recording_ready": any(
            f.kind == "recording" and f.status == "accepted" for f in files
        ),
        "feedback": await feedback_summary(db, training.id, with_comments=True),
        "can_quote": training.status in ("ordered", "returned"),
        "can_sign": training.status == "accepted"
        and training.agreement_pdf_path is not None,
        "can_deliver": training.status in OPEN_FOR_FILES,
        "can_invoice": training.invoice_ready_at is not None
        and training.paid_at is None,
    }


def list_row(training: Training, *, name: str, show_fees: bool) -> dict[str, Any]:
    return {
        "id": training.id,
        "title": training.title,
        "status": training.status,
        "status_label": status_label(training),
        "trainer_kind": training.trainer_kind,
        "trainer_contract_id": training.trainer_contract_id,
        "trainer_name": name,
        "session_date": _iso(training.session_date),
        "total": str(fee_total(training))
        if show_fees and fee_total(training) is not None
        else None,
        "invoice_ready_at": _iso(training.invoice_ready_at),
        "paid_at": _iso(training.paid_at),
        "published_at": _iso(training.published_at),
        "can_publish": can_publish(training),
    }


# ── Zamówienie (TCM) ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OrderInput:
    title: str
    topic: str = ""
    description: str = ""
    session_date: Optional[date] = None
    time_from: str = ""
    time_to: str = ""
    duration_minutes: Optional[int] = None
    platform: str = "Microsoft Teams"
    join_url: str = ""
    expected_participants: Optional[int] = None
    quote_due_on: Optional[date] = None
    participant_materials: str = ""
    deliverables: tuple[dict[str, Any], ...] = ()
    knowledge_test: bool = False
    extra_terms: str = ""
    seat_limit: Optional[int] = None


def _time(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    parts = value.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise TrainingError(422, "Godzinę podaj jako GG:MM, np. 16:00.", "bad_time")
    hours, minutes = int(parts[0]), int(parts[1])
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise TrainingError(422, "Godzinę podaj jako GG:MM, np. 16:00.", "bad_time")
    return f"{hours:02d}:{minutes:02d}"


def normalize_deliverables(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows = []
    for item in items:
        key = item.get("key")
        if key not in DELIVERABLE_KEYS or key in seen:
            raise TrainingError(
                422,
                "Każdy rodzaj pliku do przekazania może wystąpić raz.",
                "bad_deliverables",
            )
        seen.add(key)
        due = item.get("due_days")
        if due is not None and not (0 <= int(due) <= 60):
            raise TrainingError(
                422,
                "Termin przekazania podaj w dniach od szkolenia (0–60).",
                "bad_deliverables",
            )
        label = _clean(item.get("label"), TITLE_MAX) or DELIVERABLE_LABELS[key]
        if key == "other" and not _clean(item.get("label"), TITLE_MAX):
            raise TrainingError(422, "Nazwij „Inne pliki”.", "bad_deliverables")
        rows.append(
            {
                "key": key,
                "label": label,
                "required": bool(item.get("required", True)),
                "format": _clean(item.get("format"), TITLE_MAX) or DEFAULT_FORMATS[key],
                "due_days": int(due) if due is not None else None,
            }
        )
    order = {key: index for index, key in enumerate(DELIVERABLE_KEYS)}
    return sorted(rows, key=lambda row: order[row["key"]])


def _apply_order(training: Training, data: OrderInput) -> None:
    title = _clean(data.title, TITLE_MAX)
    if not title:
        raise TrainingError(422, "Podaj nazwę szkolenia.", "title_required")
    if data.duration_minutes is not None and not (15 <= data.duration_minutes <= 2_400):
        raise TrainingError(
            422, "Czas szkolenia podaj w minutach (15–2400).", "bad_duration"
        )
    if data.expected_participants is not None and not (
        1 <= data.expected_participants <= 10_000
    ):
        raise TrainingError(
            422, "Liczba uczestników musi być dodatnia.", "bad_participants"
        )
    if data.seat_limit is not None and not (1 <= data.seat_limit <= 10_000):
        raise TrainingError(422, "Limit miejsc musi być dodatni.", "bad_seats")
    join_url = _clean(data.join_url, 1_000)
    if training.teams_event_id:
        # Spotkanie założył NEXUS (0697): link należy do niego, formularz go nie nadpisze.
        join_url = training.join_url
    if join_url and not join_url.startswith("https://"):
        raise TrainingError(
            422, "Link do spotkania musi zaczynać się od https://.", "bad_url"
        )
    moved = (training.session_date, training.time_from, training.time_to) != (
        data.session_date,
        _time(data.time_from),
        _time(data.time_to),
    )
    if moved:
        # Nowy termin = nowe przypomnienia (przegląd kodu 13.11.2026).
        training.reminder_day_at = None
        training.reminder_soon_at = None
    training.title = title
    training.topic = _clean(data.topic, TITLE_MAX)
    training.description = _clean(data.description, DESCRIPTION_MAX)
    training.session_date = data.session_date
    training.time_from = _time(data.time_from)
    training.time_to = _time(data.time_to)
    training.duration_minutes = data.duration_minutes
    training.platform = _clean(data.platform, TITLE_MAX) or "Microsoft Teams"
    training.join_url = join_url
    training.expected_participants = data.expected_participants
    training.quote_due_on = data.quote_due_on
    training.participant_materials = _clean(data.participant_materials, TEXT_MAX)
    training.deliverables = normalize_deliverables(data.deliverables)
    training.knowledge_test = data.knowledge_test
    training.extra_terms = _clean(data.extra_terms, TEXT_MAX)
    training.seat_limit = data.seat_limit


async def create(
    db: AsyncSession,
    data: OrderInput,
    *,
    actor: User,
    trainer_contract_id: Optional[int],
    trainer_user_id: Optional[int],
    application_id: Optional[int],
) -> Training:
    if (trainer_contract_id is None) == (trainer_user_id is None):
        raise TrainingError(
            422,
            "Wybierz trenera: konsultanta z umową albo pracownika.",
            "trainer_required",
        )
    if (
        trainer_contract_id is not None
        and await db.get(Contract, trainer_contract_id) is None
    ):
        raise TrainingError(422, "Nie ma takiego kontraktu.", "contract_not_found")
    if trainer_user_id is not None:
        user = await db.get(User, trainer_user_id)
        if user is None or not user.is_active:
            raise TrainingError(422, "Nie ma takiej osoby w NEXUSIE.", "user_not_found")
    training = Training(
        trainer_kind="consultant" if trainer_contract_id is not None else "employee",
        trainer_contract_id=trainer_contract_id,
        trainer_user_id=trainer_user_id,
        application_id=application_id,
        status="draft",
        created_by=actor.id,
        partner={},
        deliverables=[],
        agenda=[],
    )
    _apply_order(training, data)
    db.add(training)
    await db.flush()
    return training


async def update_order(
    db: AsyncSession, training_id: int, data: OrderInput
) -> Training:
    training = await get(db, training_id, lock=True)
    # Szkolenie pracownika nie ma umowy, więc można je przełożyć także po wysłaniu
    # (0697: spotkanie i zaproszenia przesuwają się same). Termin szkolenia trenera
    # B2B stoi w podpisanym Zał. 1, dlatego po umowie zostaje zablokowany.
    reschedulable = training.status == "signed" and training.trainer_kind == "employee"
    if training.status not in EDITABLE_ORDER and not reschedulable:
        raise _wrong_status()
    _apply_order(training, data)
    await db.flush()
    return training


async def send_order(db: AsyncSession, training_id: int, *, now: datetime) -> Training:
    """Szkic → u trenera. Szkolenie pracownika nie ma umowy, więc od razu ``signed``."""

    training = await get(db, training_id, lock=True)
    if training.status != "draft":
        raise _wrong_status()
    if training.trainer_kind == "employee":
        training.status = "signed"
    else:
        if not training.deliverables:
            raise TrainingError(
                422,
                "Zaznacz, jakie pliki trener przekaże (Zał. 1 pkt 4).",
                "deliverables_required",
            )
        training.status = "ordered"
    training.ordered_at = now
    await db.flush()
    return training


async def cancel(
    db: AsyncSession, training_id: int, *, reason: str, now: datetime
) -> Training:
    training = await get(db, training_id, lock=True)
    if training.status not in CANCELLABLE:
        raise _wrong_status()
    training.status = "cancelled"
    training.cancelled_at = now
    training.cancel_reason = _clean(reason, NOTE_MAX)
    await db.flush()
    return training


# ── Wycena (trener) ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class QuoteInput:
    agenda: tuple[dict[str, Any], ...]
    fees: dict[str, Optional[Decimal]]
    own_materials: str = ""
    third_party_materials: str = ""
    quote_note: str = ""


def normalize_agenda(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        title = _clean(item.get("title"), TITLE_MAX)
        minutes = item.get("minutes")
        if not title:
            continue
        if minutes is None or not (5 <= int(minutes) <= 600):
            raise TrainingError(
                422, "Czas każdego modułu podaj w minutach (5–600).", "bad_agenda"
            )
        rows.append({"title": title, "minutes": int(minutes)})
    if not rows:
        raise TrainingError(
            422, "Dodaj przynajmniej jeden moduł agendy.", "agenda_required"
        )
    if len(rows) > AGENDA_MAX:
        raise TrainingError(
            422, f"Agenda może mieć najwyżej {AGENDA_MAX} modułów.", "bad_agenda"
        )
    return rows


def check_fees(
    training: Training, fees: dict[str, Optional[Decimal]]
) -> dict[str, Optional[Decimal]]:
    """Pozycja C tylko z prezentacją, D tylko z audio; A, B i E zawsze."""

    keys = set(deliverable_keys(training))
    clean: dict[str, Optional[Decimal]] = {}
    for key, label, needs in FEES:
        value = fees.get(key)
        if needs is not None and needs not in keys:
            if value not in (None, Decimal(0)):
                raise TrainingError(
                    422,
                    f"Pozycja „{label}” nie dotyczy tego zamówienia. Zostaw ją pustą.",
                    "fee_not_ordered",
                )
            clean[key] = None
            continue
        if value is None:
            raise TrainingError(422, f"Wpisz kwotę: {label}.", "fee_required")
        if value < 0 or value >= FEE_MAX:
            raise TrainingError(
                422, f"Kwota „{label}” jest poza zakresem.", "fee_range"
            )
        clean[key] = value.quantize(Decimal("0.01"))
    return clean


async def submit_quote(
    db: AsyncSession,
    training_id: int,
    contract_ids: Iterable[int],
    data: QuoteInput,
    *,
    now: datetime,
) -> Training:
    training = await for_trainer(db, training_id, contract_ids, lock=True)
    if training.status not in ("ordered", "returned"):
        raise _wrong_status()
    training.agenda = normalize_agenda(data.agenda)
    for key, value in check_fees(training, data.fees).items():
        setattr(training, key, value)
    training.own_materials = _clean(data.own_materials, TEXT_MAX)
    training.third_party_materials = _clean(data.third_party_materials, TEXT_MAX)
    training.quote_note = _clean(data.quote_note, TEXT_MAX)
    training.status = "quoted"
    training.quoted_at = now
    await db.flush()
    return training


async def return_quote(db: AsyncSession, training_id: int, *, note: str) -> Training:
    training = await get(db, training_id, lock=True)
    if training.status != "quoted":
        raise _wrong_status()
    clean = _clean(note, TEXT_MAX)
    if not clean:
        raise TrainingError(422, "Napisz trenerowi, co poprawić.", "note_required")
    training.status = "returned"
    training.return_note = clean
    await db.flush()
    return training


async def accept_quote(
    db: AsyncSession, training_id: int, *, actor: User, now: datetime
) -> Training:
    training = await get(db, training_id, lock=True)
    if training.status != "quoted":
        raise _wrong_status()
    training.status = "accepted"
    training.accepted_at = now
    training.accepted_by = actor.id
    training.return_note = ""
    await db.flush()
    return training


# ── Pliki ────────────────────────────────────────────────────────────────────


async def _supersede(db: AsyncSession, training_id: int, key: str) -> None:
    previous = (
        await db.scalars(
            select(TrainingFile).where(
                TrainingFile.training_id == training_id,
                TrainingFile.kind == "deliverable",
                TrainingFile.deliverable_key == key,
                TrainingFile.status.in_(("submitted", "returned")),
            )
        )
    ).all()
    for item in previous:
        item.status = "replaced"


async def check_deliverable(
    db: AsyncSession, training_id: int, contract_ids: Iterable[int], key: str
) -> Training:
    """Przed zapisem pliku: czy to szkolenie trenera i czy ta pozycja jest w Zał. 1."""

    training = await for_trainer(db, training_id, contract_ids)
    if training.status not in OPEN_FOR_FILES:
        raise TrainingError(
            409, "Pliki przekażesz po podpisaniu umowy przez obie strony.", "not_signed"
        )
    if key not in deliverable_keys(training):
        raise TrainingError(422, "Tego pliku nie ma w zamówieniu.", "not_ordered")
    rows = handover(training, await files_of(db, training_id))
    if any(row["key"] == key and row["state"] == "accepted" for row in rows):
        raise TrainingError(409, "Ta pozycja jest już przyjęta.", "already_accepted")
    return training


async def add_deliverable(
    db: AsyncSession,
    training: Training,
    *,
    key: str,
    stored: Any,
    file_name: str,
    contract_id: int,
    now: datetime,
) -> TrainingFile:
    await _supersede(db, training.id, key)
    item = TrainingFile(
        training_id=training.id,
        kind="deliverable",
        deliverable_key=key,
        status="submitted",
        file_name=file_name[:255],
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
        storage=stored.storage,
        storage_key=stored.storage_key,
        sp_drive_id=stored.sp_drive_id,
        uploaded_by_contract_id=contract_id,
        uploaded_at=now,
        for_participants=key in ("materials", "audio"),
    )
    db.add(item)
    await db.flush()
    return item


async def add_file(
    db: AsyncSession,
    training: Training,
    *,
    kind: str,
    stored: Any,
    file_name: str,
    now: datetime,
    user_id: Optional[int] = None,
    contract_id: Optional[int] = None,
) -> TrainingFile:
    item = TrainingFile(
        training_id=training.id,
        kind=kind,
        deliverable_key=None,
        status="accepted" if kind in ("recording", "internal") else "submitted",
        file_name=file_name[:255],
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
        storage=stored.storage,
        storage_key=stored.storage_key,
        sp_drive_id=stored.sp_drive_id,
        uploaded_by_user_id=user_id,
        uploaded_by_contract_id=contract_id,
        uploaded_at=now,
        for_participants=kind == "recording",
    )
    db.add(item)
    await db.flush()
    return item


async def _refresh_invoice_ready(
    db: AsyncSession, training: Training, now: datetime
) -> None:
    rows = handover(training, await files_of(db, training.id))
    required = set(_required_keys(training))
    done = {row["key"] for row in rows if row["state"] == "accepted"}
    if required and required <= done:
        if training.invoice_ready_at is None:
            training.invoice_ready_at = now
    elif training.paid_at is None:
        training.invoice_ready_at = None


async def review_file(
    db: AsyncSession,
    training_id: int,
    file_id: int,
    *,
    accept: bool,
    note: str,
    actor: User,
    now: datetime,
) -> Training:
    training = await get(db, training_id, lock=True)
    item = await db.scalar(
        select(TrainingFile)
        .where(TrainingFile.id == file_id, TrainingFile.training_id == training_id)
        .with_for_update()
    )
    if item is None or item.kind != "deliverable":
        raise TrainingError(404, "Nie ma takiego pliku.", "file_not_found")
    if item.status not in ("submitted", "accepted", "returned"):
        raise _wrong_status()
    clean = _clean(note, NOTE_MAX)
    if not accept and not clean:
        raise TrainingError(422, "Napisz trenerowi, co poprawić.", "note_required")
    item.status = "accepted" if accept else "returned"
    item.review_note = clean
    item.reviewed_by = actor.id
    item.reviewed_at = now
    # § 11 ust. 4: wezwanie do poprawy z terminem nie krótszym niż 3 dni robocze.
    item.fix_due_on = None if accept else add_business_days(now, FIX_DAYS)
    await db.flush()
    await _refresh_invoice_ready(db, training, now)
    await db.flush()
    return training


async def set_for_participants(
    db: AsyncSession, training_id: int, file_id: int, *, value: bool
) -> TrainingFile:
    item = await db.scalar(
        select(TrainingFile).where(
            TrainingFile.id == file_id, TrainingFile.training_id == training_id
        )
    )
    # Plik TCM („wewnętrzny”) może pójść do uczestników po świadomym zaznaczeniu:
    # bez tego szkolenie pracownika nie miało jak dać ludziom materiałów (13.11.2026).
    if item is None or item.kind == "invoice":
        raise TrainingError(404, "Nie ma takiego pliku.", "file_not_found")
    item.for_participants = value
    await db.flush()
    return item


async def mark_paid(
    db: AsyncSession, training_id: int, *, actor: User, now: datetime, paid: bool
) -> Training:
    training = await get(db, training_id, lock=True)
    if training.trainer_kind != "consultant" or training.status != "signed":
        raise _wrong_status()
    if paid:
        if training.invoice_ready_at is None:
            raise TrainingError(
                409, "Zapłatę oznaczysz po przyjęciu wszystkich plików.", "not_ready"
            )
        training.paid_at = now
        training.paid_marked_by = actor.id
    else:
        if training.published_at is not None:
            raise TrainingError(
                409,
                "Szkolenie jest w bibliotece. Najpierw wycofaj je z biblioteki.",
                "published",
            )
        training.paid_at = None
        training.paid_marked_by = None
    await db.flush()
    return training


async def publish(
    db: AsyncSession, training_id: int, *, actor: User, now: datetime, publish_it: bool
) -> Training:
    """Druga osoba zatwierdza: kto wgrał nagranie, ten go nie publikuje."""

    training = await get(db, training_id, lock=True)
    if not publish_it:
        training.published_at = None
        training.published_by = None
        await db.flush()
        return training
    if not can_publish(training):
        raise TrainingError(
            409,
            "Szkolenie trenera z umową B2B wejdzie do biblioteki po zapłacie, "
            "bo dopiero wtedy przechodzą prawa autorskie (§ 8 ust. 3 umowy).",
            "not_paid",
        )
    files = await files_of(db, training_id)
    visible = [f for f in files if f.for_participants and f.status != "replaced"]
    if not visible:
        raise TrainingError(
            422,
            "Zaznacz przynajmniej jeden plik dla uczestników.",
            "nothing_to_publish",
        )
    if any(
        f.kind == "recording" and f.uploaded_by_user_id == actor.id for f in visible
    ):
        raise TrainingError(
            403,
            "Nagranie zatwierdza druga osoba, nie ta, która je wgrała.",
            "four_eyes",
        )
    training.published_at = now
    training.published_by = actor.id
    await db.flush()
    return training


# ── Biblioteka i zapisy ──────────────────────────────────────────────────────

#: Plik w bibliotece: zaznaczony „dla uczestników” i przyjęty. Plik od trenera, którego
#: TCM nie przyjął albo zwrócił do poprawy, nie wychodzi do wszystkich (przegląd
#: bezpieczeństwa 13.11.2026); nagranie i pliki TCM powstają jako przyjęte.
_LIBRARY_FILE = (
    TrainingFile.for_participants.is_(True),
    TrainingFile.status == "accepted",
)


async def library(
    db: AsyncSession,
    *,
    today: date,
    user_id: Optional[int] = None,
    contract_ids: tuple[int, ...] = (),
) -> dict[str, Any]:
    mine_query = select(TrainingRegistration.training_id)
    if user_id is not None:
        mine_query = mine_query.where(TrainingRegistration.user_id == user_id)
    else:
        mine_query = mine_query.where(
            TrainingRegistration.contract_id.in_(contract_ids or (0,))
        )
    registered = set((await db.scalars(mine_query)).all())
    published = (
        await db.scalars(
            select(Training)
            .where(
                Training.status == "signed",
                (Training.published_at.is_not(None))
                | (
                    Training.shared_registered_at.is_not(None)
                    & Training.id.in_(registered or {0})
                ),
            )
            .order_by(Training.session_date.desc().nulls_last(), Training.id.desc())
            .limit(200)
        )
    ).all()
    upcoming = (
        await db.scalars(
            select(Training)
            .where(
                Training.status == "signed",
                Training.session_date.is_not(None),
                Training.session_date >= today,
            )
            .order_by(Training.session_date, Training.time_from, Training.id)
            .limit(50)
        )
    ).all()
    seats = dict(
        (
            await db.execute(
                select(TrainingRegistration.training_id, func.count())
                .where(
                    TrainingRegistration.training_id.in_(
                        [t.id for t in upcoming] or [0]
                    )
                )
                .group_by(TrainingRegistration.training_id)
            )
        ).all()
    )
    file_rows = (
        await db.scalars(
            select(TrainingFile).where(
                TrainingFile.training_id.in_([t.id for t in published] or [0]),
                *_LIBRARY_FILE,
            )
        )
    ).all()
    by_training: dict[int, list[TrainingFile]] = {}
    for item in file_rows:
        by_training.setdefault(item.training_id, []).append(item)
    return {
        "recordings": [
            {
                "id": t.id,
                "title": t.title,
                "topic": t.topic,
                "description": t.description,
                "session_date": _iso(t.session_date),
                "duration_minutes": t.duration_minutes,
                "trainer_kind": t.trainer_kind,
                # „registered” = nagranie tylko dla zapisanych (przed zapłatą trenera B2B).
                "scope": "library" if t.published_at is not None else "registered",
                "registered": t.id in registered,
                "chapters": chapters(t),
                "files": [
                    {
                        "id": f.id,
                        "kind": f.kind,
                        "file_name": f.file_name,
                        "content_type": f.content_type,
                        "size_bytes": f.size_bytes,
                    }
                    for f in by_training.get(t.id, [])
                ],
            }
            for t in published
        ],
        "live": [
            {
                "id": t.id,
                "title": t.title,
                "topic": t.topic,
                "session_date": _iso(t.session_date),
                "time_from": t.time_from,
                "time_to": t.time_to,
                "platform": t.platform,
                "description": t.description,
                "trainer_kind": t.trainer_kind,
                "seat_limit": t.seat_limit,
                "taken": int(seats.get(t.id, 0)),
                "registered": t.id in registered,
                # Prowadzący nie zapisuje się na własne szkolenie; link ma w karcie.
                "leading": (user_id is not None and t.trainer_user_id == user_id)
                or (
                    t.trainer_contract_id is not None
                    and t.trainer_contract_id in contract_ids
                ),
                "join_url": t.join_url
                if t.id in registered
                or (user_id is not None and t.trainer_user_id == user_id)
                or (
                    t.trainer_contract_id is not None
                    and t.trainer_contract_id in contract_ids
                )
                else None,
                "invited": t.teams_status == "created",
            }
            for t in upcoming
        ],
    }


async def library_file(db: AsyncSession, file_id: int) -> TrainingFile:
    """Plik z biblioteki: tylko opublikowane szkolenie i plik dla uczestników."""

    row = (
        await db.execute(
            select(TrainingFile)
            .join(Training, Training.id == TrainingFile.training_id)
            .where(
                TrainingFile.id == file_id,
                *_LIBRARY_FILE,
                Training.published_at.is_not(None),
                Training.status == "signed",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise TrainingError(404, "Nie ma takiego pliku.", "file_not_found")
    return row


async def register(
    db: AsyncSession,
    training_id: int,
    *,
    today: date,
    user_id: Optional[int] = None,
    contract_id: Optional[int] = None,
    join: bool,
) -> Optional[str]:
    """Zapis albo wypis. Zwraca identyfikator zaproszenia w kalendarzu, które trzeba
    odwołać po wypisie (``teams.uninvite_event``), bo wiersz zapisu już znika."""
    # Blokada wiersza: dwa równoległe zapisy nie przekroczą limitu miejsc.
    training = await get(db, training_id, lock=True)
    if (
        training.status != "signed"
        or training.session_date is None
        or training.session_date < today
    ):
        raise TrainingError(409, "Na to szkolenie nie można się już zapisać.", "closed")
    query = select(TrainingRegistration).where(
        TrainingRegistration.training_id == training_id
    )
    if user_id is not None:
        query = query.where(TrainingRegistration.user_id == user_id)
    else:
        query = query.where(TrainingRegistration.contract_id == contract_id)
    existing = await db.scalar(query)
    if join and existing is None and training.seat_limit:
        taken = await db.scalar(
            select(func.count())
            .select_from(TrainingRegistration)
            .where(TrainingRegistration.training_id == training_id)
        )
        if (taken or 0) >= training.seat_limit:
            raise TrainingError(
                409, "Na to szkolenie nie ma już wolnych miejsc.", "no_seats"
            )
    if join and existing is None:
        db.add(
            TrainingRegistration(
                training_id=training_id, user_id=user_id, contract_id=contract_id
            )
        )
    removed_invite: Optional[str] = None
    if not join and existing is not None:
        removed_invite = existing.invite_event_id
        await db.delete(existing)
    await db.flush()
    return removed_invite


async def trainer_trainings(
    db: AsyncSession, contract_ids: Iterable[int]
) -> list[dict[str, Any]]:
    rows = (
        await db.scalars(
            select(Training)
            .where(
                Training.trainer_contract_id.in_(tuple(contract_ids) or (0,)),
                Training.status != "draft",
            )
            .order_by(Training.session_date.desc().nulls_first(), Training.id.desc())
        )
    ).all()
    return [list_row(t, name="", show_fees=True) for t in rows]


# ── Nagranie dla zapisanych, oceny, transkrypt (0697) ──────────────────────


async def shared_file(db: AsyncSession, file_id: int) -> TrainingFile:
    """Plik szkolenia udostępnionego zapisanym; tę samą bramkę sprawdza bilet ``reg``."""

    row = (
        await db.execute(
            select(TrainingFile)
            .join(Training, Training.id == TrainingFile.training_id)
            .where(
                TrainingFile.id == file_id,
                *_LIBRARY_FILE,
                Training.shared_registered_at.is_not(None),
                Training.status == "signed",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise TrainingError(404, "Nie ma takiego pliku.", "file_not_found")
    return row


async def is_registered(
    db: AsyncSession,
    training_id: int,
    *,
    user_id: Optional[int] = None,
    contract_ids: Iterable[int] = (),
) -> bool:
    query = select(TrainingRegistration.id).where(
        TrainingRegistration.training_id == training_id
    )
    if user_id is not None:
        query = query.where(TrainingRegistration.user_id == user_id)
    else:
        query = query.where(
            TrainingRegistration.contract_id.in_(tuple(contract_ids) or (0,))
        )
    return await db.scalar(query.limit(1)) is not None


async def viewer_file(
    db: AsyncSession,
    file_id: int,
    *,
    user_id: Optional[int] = None,
    contract_ids: Iterable[int] = (),
) -> tuple[TrainingFile, str]:
    """Plik z biblioteki (``lib``) albo z nagrania dla zapisanych (``reg``)."""

    try:
        return await library_file(db, file_id), "lib"
    except TrainingError:
        item = await shared_file(db, file_id)
        if not await is_registered(
            db, item.training_id, user_id=user_id, contract_ids=contract_ids
        ):
            raise
        return item, "reg"


async def share_registered(
    db: AsyncSession, training_id: int, *, actor: User, now: datetime, share: bool
) -> Training:
    """Nagranie dla zapisanych przed zapłatą (decyzja Artura 13.11.2026).

    Przed zapłatą firma ma licencję na to szkolenie (§ 8 ust. 4 umowy), więc
    nagranie widzą tylko zapisani na nie; cała biblioteka dalej czeka na zapłatę.
    Ta sama zasada czterech oczu co przy publikacji."""

    training = await get(db, training_id, lock=True)
    if not share:
        training.shared_registered_at = None
        training.shared_registered_by = None
        await db.flush()
        return training
    if training.status != "signed":
        raise _wrong_status()
    files = await files_of(db, training_id)
    recordings = [
        f
        for f in files
        if f.kind == "recording" and f.for_participants and f.status == "accepted"
    ]
    if not recordings:
        raise TrainingError(
            422, "To szkolenie nie ma jeszcze nagrania.", "no_recording"
        )
    if any(f.uploaded_by_user_id == actor.id for f in recordings):
        raise TrainingError(
            403,
            "Nagranie zatwierdza druga osoba, nie ta, która je wgrała.",
            "four_eyes",
        )
    training.shared_registered_at = now
    training.shared_registered_by = actor.id
    await db.flush()
    return training


async def rate(
    db: AsyncSession,
    training_id: int,
    *,
    today: date,
    rating: int,
    comment: str,
    user_id: Optional[int] = None,
    contract_id: Optional[int] = None,
) -> None:
    """Ocena 1–5 po szkoleniu, tylko od zapisanego. Druga ocena poprawia pierwszą."""

    training = await get(db, training_id)
    if (
        training.status != "signed"
        or training.session_date is None
        or training.session_date > today
    ):
        raise TrainingError(409, "Ocenisz szkolenie po jego terminie.", "too_early")
    if not 1 <= rating <= 5:
        raise TrainingError(422, "Ocena to liczba od 1 do 5.", "bad_rating")
    contract_ids = (contract_id,) if contract_id is not None else ()
    if not await is_registered(
        db, training_id, user_id=user_id, contract_ids=contract_ids
    ):
        raise TrainingError(
            403, "Ocenić mogą osoby zapisane na szkolenie.", "not_registered"
        )
    query = select(TrainingFeedback).where(TrainingFeedback.training_id == training_id)
    query = (
        query.where(TrainingFeedback.user_id == user_id)
        if user_id is not None
        else query.where(TrainingFeedback.contract_id == contract_id)
    )
    row = await db.scalar(query)
    if row is None:
        row = TrainingFeedback(
            training_id=training_id, user_id=user_id, contract_id=contract_id
        )
        db.add(row)
    row.rating = rating
    row.comment = _clean(comment, 1_000)
    await db.flush()


async def feedback_summary(
    db: AsyncSession, training_id: int, *, with_comments: bool
) -> dict[str, Any]:
    rows = (
        await db.scalars(
            select(TrainingFeedback)
            .where(TrainingFeedback.training_id == training_id)
            .order_by(TrainingFeedback.created_at.desc())
        )
    ).all()
    average = round(sum(r.rating for r in rows) / len(rows), 1) if rows else None
    out: dict[str, Any] = {"count": len(rows), "average": average}
    if with_comments:
        # Bez nazwisk: trener i TCM widzą treść, nie autora.
        out["comments"] = [r.comment for r in rows if r.comment][:50]
    return out


async def my_rating(
    db: AsyncSession,
    training_id: int,
    *,
    user_id: Optional[int] = None,
    contract_id: Optional[int] = None,
) -> Optional[int]:
    query = select(TrainingFeedback.rating).where(
        TrainingFeedback.training_id == training_id
    )
    query = (
        query.where(TrainingFeedback.user_id == user_id)
        if user_id is not None
        else query.where(TrainingFeedback.contract_id == contract_id)
    )
    return await db.scalar(query)


def _vtt_lines(vtt: str) -> list[tuple[int, str]]:
    """``(sekunda, tekst)`` z VTT; nazwy mówców (``<v Imię>``) wypadają."""

    import re  # noqa: PLC0415

    cue = re.compile(r"^(\d{1,2}:)?(\d{2}):(\d{2})\.\d{3}\s+-->")
    tag = re.compile(r"<[^>]+>")
    out: list[tuple[int, str]] = []
    second: Optional[int] = None
    for raw in vtt.splitlines():
        line = raw.strip()
        match = cue.match(line)
        if match:
            hours = int((match.group(1) or "0:")[:-1])
            second = hours * 3600 + int(match.group(2)) * 60 + int(match.group(3))
            continue
        if not line or line == "WEBVTT" or second is None or line.isdigit():
            continue
        text = tag.sub("", line).strip()
        if text:
            out.append((second, text))
    return out


async def transcript_search(
    db: AsyncSession, training_id: int, needle: str, *, limit: int = 30
) -> dict[str, Any]:
    """Miejsca w nagraniu, w których padło szukane słowo (bez rozróżniania wielkości liter)."""

    row = await db.get(TrainingTranscript, training_id)
    if row is None or not row.vtt:
        return {"available": False, "hits": []}
    lines = _vtt_lines(row.vtt)
    query = needle.strip().casefold()
    hits = (
        [
            {"second": second, "text": text[:300]}
            for second, text in lines
            if query in text.casefold()
        ][:limit]
        if query
        else []
    )
    return {"available": True, "hits": hits}
