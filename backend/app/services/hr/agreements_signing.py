"""Podpis umów z ludźmi (etap 5, E5): Autenti albo ręcznie ze skanem.

Autenti — ta sama integracja co umowy B2B konsultantów i umowy ramowe
klientów (``services/autenti/client.py``: ``AutentiClient``, ``AutentiConfig``,
format procesu z ``client_contracts_sender``, wyłącznik ``AUTENTI_ENABLED``).
Drugiego klienta nie ma. Umowa z osobą zespołu nie jest kontraktem ani umową
klienta, więc nie ma wiersza w ``document_signatures`` (tam CHECK pozwala na
dokładnie jeden z trzech celów, a obsługa zdarzeń zakłada kontrakt
kandydata) — numer procesu i stan żyją w ``hr_agreements``:

* „Wyślij do podpisu” (tylko klik Kadr, ``send``): PDF z wzoru, proces
  w Autenti, wysłanie; wartości pól zamrażają się w umowie. Błąd Autenti =
  umowa zostaje szkicem z ``last_error`` (502), kolejna próba ma nowy klucz.
* Stan procesu odczytuje ``sync_process``: pętla co 15 minut (``run_once``,
  rezerwacja w ``hr_job_runs``) i — po wpięciu — webhook Autenti
  (``on_autenti_process``, gdy proces nie należy do ``document_signatures``).
  Webhook to tylko sygnał: prawdę mówi ``GET /document-processes/{id}``,
  więc powtórka zdarzenia niczego nie dubluje.
* Podpisana: pobranie podpisanego PDF-u, stan ``signed`` i przepisanie do
  kartoteki w tej samej transakcji (``agreements_effects.try_apply``).
  Odmowa osoby = ``rejected``; wycofanie albo termin w Autenti = z powrotem
  szkic z powodem.
* „Oznacz jako podpisaną” (``mark_signed``) — druga ścieżka, gdy Autenti nie
  jest ustawione albo osoba podpisała na papierze: skan (PDF, JPG, PNG), data
  podpisu i powód w śladzie; podpis i przepisanie razem albo nic.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.core.scheduling import DEFAULT_TZ, business_date, business_today
from app.models.hr_agreement import HrAgreement
from app.models.hr_profile import EmployeeProfile
from app.models.notification import NotificationType
from app.models.user import User
from app.services.autenti.client import (
    AutentiClient,
    AutentiConfig,
    AutentiError,
    AutentiNotFoundError,
)
from app.services.autenti.client_contracts_sender import _build_create_payload
from app.services.hr import agreements, audit, job_runs
from app.services.hr import agreements_document as document
from app.services.hr import agreements_effects as effects
from app.services.hr.agreements_errors import (
    AgreementConflict,
    AgreementError,
    AgreementUnavailable,
)
from app.services.hr.notify import notify_each
from app.services.hr.symfonia_files import split_name
from app.services.hr_agreements_schema import ERROR_MAX_LENGTH, NOTIFICATION_TYPES

logger = logging.getLogger(__name__)

JOB_KIND = "hr_agreements_signing"
#: Ile umów sprawdza jeden przebieg pętli (reszta w kolejnym).
BATCH_LIMIT = 50
SLOT_MINUTES = 15
PDF_MIME = "application/pdf"
SCAN_MAX_BYTES = 20 * 1024 * 1024
_ZONE = ZoneInfo(DEFAULT_TZ)

AUTENTI_OFF_DETAIL = (
    "Autenti nie jest ustawione — oznacz umowę jako podpisaną ręcznie, ze skanem."
)
SEND_FAILED_DETAIL = (
    "Autenti nie przyjęło umowy — spróbuj ponownie za chwilę albo oznacz ją jako "
    "podpisaną ręcznie, ze skanem."
)


def client_factory() -> AutentiClient:
    """Klient Autenti z env (testy podmieniają tę funkcję na fałszywego klienta)."""

    return AutentiClient(AutentiConfig.from_settings())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Powiadomienie osoby z Kadr ───────────────────────────────────────────────


def _update_type() -> Optional[NotificationType]:
    """Typ ``hr_agreement_update`` — dopóki koordynator nie dopisze go do enuma
    w ``models/notification.py``, dzwonka nie ma (stan umowy widać na ekranie)."""

    return getattr(NotificationType, NOTIFICATION_TYPES[0], None)


async def _notify_sender(
    db: AsyncSession, agreement: HrAgreement, *, title: str, message: str
) -> None:
    ntype = _update_type()
    if ntype is None:
        return
    # Bez numeru encji: dzienny odsiew powiadomień nie zna jej rodzaju, a jedna
    # umowa potrafi dać dwa dzwonki jednego dnia (podpis i nieudane przepisanie).
    await notify_each(
        db,
        [agreement.sent_by or agreement.created_by],
        title=title,
        message=message,
        ntype=ntype,
        link=f"/people/{agreement.user_id}#umowy",
        log_tag="agreements",
    )


async def _person_name(db: AsyncSession, user_id: int) -> str:
    return (await db.scalar(select(User.name).where(User.id == user_id))) or ""


def _error_text(exc: Exception) -> str:
    """Zdanie dla Kadr bez treści odpowiedzi Autenti (bywa w niej e-mail osoby)."""

    status = getattr(exc, "status", None)
    suffix = f" (Autenti: HTTP {status})" if status else ""
    return (SEND_FAILED_DETAIL + suffix)[:ERROR_MAX_LENGTH]


# ── Wysyłka, wycofanie, anulowanie ────────────────────────────────────────────


async def _signer(db: AsyncSession, agreement: HrAgreement) -> SimpleNamespace:
    person = await db.get(User, agreement.user_id)
    if person is None or not person.email:
        raise AgreementError(
            "Ta osoba nie ma adresu e-mail w NEXUSIE — Autenti go wymaga."
        )
    last_name, first_name = split_name(person.name or "")
    if not first_name or not last_name:
        raise AgreementError(
            "Autenti wymaga imienia i nazwiska osoby — popraw je w Ustawieniach → Osoby i role."
        )
    signature_type = app_settings.AUTENTI_DEFAULT_SIGNATURE_TYPE or "SES"
    phone = None
    if signature_type == "AdES":
        phone = await db.scalar(
            select(EmployeeProfile.phone).where(
                EmployeeProfile.user_id == agreement.user_id
            )
        )
        if not phone:
            raise AgreementError(
                "Podpis AdES wymaga telefonu osoby (SMS) — wpisz go w kartotece."
            )
    return SimpleNamespace(
        autenti_signature_type=signature_type,
        signer_email=person.email,
        signer_first_name=first_name,
        signer_last_name=last_name,
        signer_phone=phone,
    )


async def send(db: AsyncSession, agreement_id: int, *, actor: User) -> HrAgreement:
    """Szkic → wysłana (Autenti). Błąd Autenti = szkic z ``last_error`` i 502."""

    if not agreements.autenti_configured():
        raise AgreementUnavailable(AUTENTI_OFF_DETAIL)
    agreement = await agreements.get_agreement(db, agreement_id, lock=True)
    agreements.ensure_not_self(actor, agreement.user_id)
    if agreement.status != "draft":
        raise AgreementConflict("Do podpisu wysyła się tylko szkic umowy.")
    # Reguły mogły się zmienić od zapisu szkicu (minimalna stawka, zamknięty
    # miesiąc, kartoteka) — sprawdzamy jeszcze raz przed wysyłką.
    await agreements.validate_draft(
        db, user_id=agreement.user_id, values={}, current=agreement
    )
    signer = await _signer(db, agreement)
    fields = await document.context_for(db, agreement)
    content = await document.render_docx(db, agreement)
    pdf = await document.pdf_from_docx(content)
    name = await _person_name(db, agreement.user_id)

    agreement.send_attempts = (agreement.send_attempts or 0) + 1
    key = f"hr-agreement-{agreement.id}-{agreement.send_attempts}"
    try:
        async with client_factory() as client:
            process = await client.create_document_process(
                _build_create_payload(
                    signature=signer, title=agreements.title(agreement)
                ),
                idempotency_key=key,
            )
            process_id = str(process.get("id") or process.get("uuid") or "")
            if not process_id:
                raise AutentiError(500, "missing process id")
            await client.upload_file(
                process_id,
                pdf_bytes=pdf,
                filename=f"{document.file_stem(agreement, name)}.pdf",
                idempotency_key=f"{key}-upload",
            )
            await client.send(process_id, idempotency_key=f"{key}-send")
    except (AutentiError, RuntimeError) as exc:
        agreement.last_error = _error_text(exc)
        agreement.updated_by = actor.id
        audit.record(
            db,
            actor_user_id=actor.id,
            subject_user_id=agreement.user_id,
            entity_type="hr_agreement",
            entity_id=agreement.id,
            action="agreement_send_failed",
            details={
                "attempt": agreement.send_attempts,
                "status": getattr(exc, "status", None),
            },
        )
        message = agreement.last_error
        # Próba i powód zostają, choć trasa odpowiada błędem.
        await db.commit()
        raise AgreementError(message, status=502) from exc

    agreement.status = "sent"
    agreement.signing_channel = "autenti"
    agreement.autenti_process_id = process_id
    agreement.document_fields = fields
    agreement.sent_sha256 = hashlib.sha256(pdf).hexdigest()
    agreement.signer_email = signer.signer_email
    agreement.sent_at = _now()
    agreement.sent_by = actor.id
    agreement.last_error = None
    agreement.updated_by = actor.id
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=agreement.user_id,
        entity_type="hr_agreement",
        entity_id=agreement.id,
        action="agreement_sent",
        details={
            "channel": "autenti",
            "attempt": agreement.send_attempts,
            "signature_type": signer.autenti_signature_type,
            "sha256": agreement.sent_sha256,
        },
    )
    return agreement


def _back_to_draft(agreement: HrAgreement, reason: Optional[str]) -> None:
    agreement.status = "draft"
    agreement.signing_channel = None
    agreement.autenti_process_id = None
    agreement.document_fields = None
    agreement.sent_sha256 = None
    agreement.sent_at = None
    agreement.last_error = reason[:ERROR_MAX_LENGTH] if reason else None


async def _withdraw_in_autenti(process_id: Optional[str]) -> None:
    if not process_id:
        return
    if not agreements.autenti_configured():
        raise AgreementUnavailable(
            "Autenti jest wyłączone — umowy wysłanej do podpisu nie da się teraz wycofać."
        )
    try:
        async with client_factory() as client:
            await client.withdraw(process_id)
    except AutentiNotFoundError:
        # Proces już nie istnieje po stronie Autenti — nie ma czego wycofywać.
        return
    except (AutentiError, RuntimeError) as exc:
        raise AgreementError(
            "Nie udało się wycofać umowy z Autenti — spróbuj ponownie za chwilę.",
            status=502,
        ) from exc


async def withdraw(db: AsyncSession, agreement_id: int, *, actor: User) -> HrAgreement:
    """Wysłana → szkic (wycofanie w Autenti); potem poprawka, ponowna wysyłka albo podpis ręczny."""

    agreement = await agreements.get_agreement(db, agreement_id, lock=True)
    agreements.ensure_not_self(actor, agreement.user_id)
    if agreement.status != "sent":
        raise AgreementConflict("Wycofać można tylko umowę wysłaną do podpisu.")
    process_id = agreement.autenti_process_id
    await _withdraw_in_autenti(process_id)
    _back_to_draft(agreement, "Wycofana z Autenti przez Kadry.")
    agreement.updated_by = actor.id
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=agreement.user_id,
        entity_type="hr_agreement",
        entity_id=agreement.id,
        action="agreement_withdrawn",
        details={"process_id": process_id},
    )
    await db.flush()
    return agreement


async def cancel(
    db: AsyncSession, agreement_id: int, *, actor: User, reason: Any
) -> HrAgreement:
    """Szkic albo wysłana → anulowana (wysłaną najpierw wycofuje w Autenti)."""

    clean = agreements.clean_reason(reason, label="Powód anulowania")
    agreement = await agreements.get_agreement(db, agreement_id, lock=True)
    agreements.ensure_not_self(actor, agreement.user_id)
    if agreement.status not in ("draft", "sent"):
        raise AgreementConflict("Anulować można szkic albo umowę wysłaną do podpisu.")
    withdrawn_remotely = False
    if agreement.status == "sent" and agreements.autenti_configured():
        await _withdraw_in_autenti(agreement.autenti_process_id)
        withdrawn_remotely = True
    # Autenti wyłączone po wysyłce: anulowanie i tak przechodzi (inaczej umowa
    # utknęłaby jako wysłana), a ślad mówi, że procesu nie wycofano.
    agreement.status = "cancelled"
    agreement.cancelled_at = _now()
    agreement.cancelled_by = actor.id
    agreement.cancel_reason = clean
    agreement.updated_by = actor.id
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=agreement.user_id,
        entity_type="hr_agreement",
        entity_id=agreement.id,
        action="agreement_cancelled",
        details={"reason": clean, "withdrawn_in_autenti": withdrawn_remotely},
    )
    await db.flush()
    return agreement


# ── Podpis ręczny ze skanem ──────────────────────────────────────────────────


def scan_mime(content: bytes) -> str:
    """Skan podpisanej umowy: PDF, JPG albo PNG (po nagłówku pliku, nie po nazwie)."""

    if not content:
        raise AgreementError("Dołącz skan podpisanej umowy (PDF, JPG albo PNG).")
    if len(content) > SCAN_MAX_BYTES:
        raise AgreementError("Skan może mieć najwyżej 20 MB.")
    if content.startswith(b"%PDF-"):
        return PDF_MIME
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    raise AgreementError("Skan musi być plikiem PDF, JPG albo PNG.")


async def mark_signed(
    db: AsyncSession,
    agreement_id: int,
    *,
    actor: User,
    signed_on: date,
    reason: Any,
    content: bytes,
) -> HrAgreement:
    """Szkic → podpisana ręcznie; podpis i przepisanie do kartoteki razem albo nic."""

    clean = agreements.clean_reason(reason)
    mime = scan_mime(content)
    agreement = await agreements.get_agreement(db, agreement_id, lock=True)
    agreements.ensure_not_self(actor, agreement.user_id)
    if agreement.status == "sent":
        raise AgreementConflict(
            "Umowa czeka na podpis w Autenti — wycofaj ją, zanim oznaczysz podpis ręcznie."
        )
    if agreement.status != "draft":
        raise AgreementConflict("Jako podpisaną oznacza się tylko szkic umowy.")
    if signed_on > business_today():
        raise AgreementError("Data podpisu nie może być z przyszłości.")
    await agreements.validate_draft(
        db, user_id=agreement.user_id, values={}, current=agreement
    )
    fields = await document.context_for(db, agreement)
    agreement.status = "signed"
    agreement.signing_channel = "manual"
    agreement.document_fields = fields
    agreement.document_sha256 = hashlib.sha256(content).hexdigest()
    agreement.signed_on = signed_on
    agreement.signed_at = _now()
    agreement.signed_by = actor.id
    agreement.manual_reason = clean
    agreement.last_error = None
    agreement.updated_by = actor.id
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=agreement.user_id,
        entity_type="hr_agreement",
        entity_id=agreement.id,
        action="agreement_signed_manually",
        details={
            "reason": clean,
            "signed_on": signed_on.isoformat(),
            "sha256": agreement.document_sha256,
            "mime": mime,
        },
    )
    # Bez punktu zapisu: odmowa przepisania cofa też sam podpis (trasa 4xx).
    await effects.apply_signed(db, agreement, content=content, mime=mime, actor=actor)
    return agreement


# ── Stan procesu w Autenti ───────────────────────────────────────────────────


def _remote_state(info: dict[str, Any]) -> Optional[str]:
    status = str(info.get("status") or "").upper()
    if "COMPLETED" in status:
        return "signed"
    if "REJECTED" in status:
        return "rejected"
    if "WITHDRAWN" in status:
        return "withdrawn"
    if "EXPIRED" in status:
        return "expired"
    return None


async def _on_signed(
    db: AsyncSession, agreement: HrAgreement, client: AutentiClient
) -> str:
    pdf = await client.download_signed_file(agreement.autenti_process_id or "")
    if not pdf:
        raise AutentiError(0, "empty signed file")
    moment = _now()
    agreement.status = "signed"
    agreement.document_sha256 = hashlib.sha256(pdf).hexdigest()
    agreement.signed_at = moment
    agreement.signed_on = business_date(moment)
    agreement.last_error = None
    await db.flush()
    audit.record(
        db,
        actor_user_id=None,
        subject_user_id=agreement.user_id,
        entity_type="hr_agreement",
        entity_id=agreement.id,
        action="agreement_signed",
        details={"channel": "autenti", "sha256": agreement.document_sha256},
    )
    reason = await effects.try_apply(
        db, agreement, content=pdf, mime=PDF_MIME, actor=None
    )
    name = await _person_name(db, agreement.user_id)
    await _notify_sender(
        db,
        agreement,
        title=f"Umowa podpisana — {name}",
        message=(
            "Stawka, forma i dokument są już w kartotece."
            if reason is None
            else "Podpisana, ale nie przeszła do kartoteki — zobacz powód przy umowie."
        ),
    )
    return "signed" if reason is None else "apply_failed"


async def _retry_apply(
    db: AsyncSession,
    agreement: HrAgreement,
    client: AutentiClient,
    actor: Optional[User],
) -> str:
    pdf = await client.download_signed_file(agreement.autenti_process_id or "")
    if not pdf:
        raise AutentiError(0, "empty signed file")
    reason = await effects.try_apply(
        db, agreement, content=pdf, mime=PDF_MIME, actor=actor
    )
    return "applied" if reason is None else "apply_failed"


async def sync_process(
    db: AsyncSession, agreement: HrAgreement, client: AutentiClient
) -> str:
    """Stan umowy według Autenti (wywołujący trzyma blokadę wiersza i commituje)."""

    if agreement.status == "signed":
        if agreement.applied_at is not None or agreement.signing_channel != "autenti":
            return "unchanged"
        return await _retry_apply(db, agreement, client, None)
    if agreement.status != "sent" or not agreement.autenti_process_id:
        return "unchanged"
    try:
        info = await client.get_process(agreement.autenti_process_id)
    except AutentiNotFoundError:
        info = {"status": "DOCUMENT_PROCESS_WITHDRAWN"}
    state = _remote_state(info)
    if state == "signed":
        try:
            return await _on_signed(db, agreement, client)
        except AutentiError:
            agreement.last_error = (
                "Podpisana w Autenti — pobranie pliku nie wyszło, NEXUS ponowi próbę."
            )
            return "download_failed"
    name = await _person_name(db, agreement.user_id)
    if state == "rejected":
        agreement.status = "rejected"
        agreement.rejected_at = _now()
        audit.record(
            db,
            actor_user_id=None,
            subject_user_id=agreement.user_id,
            entity_type="hr_agreement",
            entity_id=agreement.id,
            action="agreement_rejected",
            details={"channel": "autenti"},
        )
        await _notify_sender(
            db,
            agreement,
            title=f"Umowa nie została podpisana — {name}",
            message="Osoba odmówiła podpisu w Autenti. Przygotuj nową umowę, jeśli trzeba.",
        )
        return "rejected"
    if state in ("withdrawn", "expired"):
        reason = (
            "Termin podpisu w Autenti minął — wyślij umowę ponownie albo oznacz ją "
            "jako podpisaną ręcznie."
            if state == "expired"
            else "Umowa została wycofana w Autenti — wyślij ją ponownie, jeśli trzeba."
        )
        process_id = agreement.autenti_process_id
        _back_to_draft(agreement, reason)
        audit.record(
            db,
            actor_user_id=None,
            subject_user_id=agreement.user_id,
            entity_type="hr_agreement",
            entity_id=agreement.id,
            action=f"agreement_{state}",
            details={"process_id": process_id},
        )
        await _notify_sender(
            db, agreement, title=f"Umowa wróciła do szkicu — {name}", message=reason
        )
        return state
    return "unchanged"


async def retry_apply(
    db: AsyncSession, agreement_id: int, *, actor: User
) -> HrAgreement:
    """„Przepisz ponownie” — podpisana w Autenti, nieprzepisana do kartoteki."""

    agreement = await agreements.get_agreement(db, agreement_id, lock=True)
    agreements.ensure_not_self(actor, agreement.user_id)
    if agreement.status != "signed" or agreement.applied_at is not None:
        raise AgreementConflict(
            "Ta umowa jest już w kartotece albo nie jest podpisana."
        )
    if agreement.signing_channel != "autenti":
        raise AgreementConflict(
            "Umowa podpisana ręcznie przechodzi do kartoteki od razu."
        )
    if not agreements.autenti_configured():
        raise AgreementUnavailable(
            "Autenti jest wyłączone — podpisanego pliku nie da się teraz pobrać."
        )
    try:
        async with client_factory() as client:
            await _retry_apply(db, agreement, client, actor)
    except (AutentiError, RuntimeError) as exc:
        raise AgreementError(
            "Nie udało się pobrać podpisanej umowy z Autenti — spróbuj za chwilę.",
            status=502,
        ) from exc
    return agreement


async def on_autenti_process(db: AsyncSession, process_id: str) -> bool:
    """Webhook Autenti dla procesu spoza ``document_signatures``: ``True`` = to umowa z osobą.

    Do wpięcia w ``autenti.webhook_handler.handle_event``, gdy proces nie ma
    wiersza podpisu. Odczytuje stan z Autenti i commituje; powtórzone
    zdarzenie nie zmienia niczego drugi raz.
    """

    agreement = await db.scalar(
        select(HrAgreement)
        .where(HrAgreement.autenti_process_id == process_id)
        .with_for_update()
    )
    if agreement is None:
        return False
    if not agreements.autenti_configured():
        return True
    agreement_id = agreement.id
    try:
        async with client_factory() as client:
            await sync_process(db, agreement, client)
        await db.commit()
    except Exception:  # noqa: BLE001 — pętla co 15 minut dociągnie stan
        await db.rollback()
        logger.exception("[agreements] webhook umowy %s nie wyszedł", agreement_id)
    return True


def _slot(moment: datetime) -> str:
    local = moment.astimezone(_ZONE)
    minute = local.minute - local.minute % SLOT_MINUTES
    return local.replace(minute=minute).strftime("%Y-%m-%dT%H:%M")


async def run_once(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> dict[str, Any]:
    """Przebieg pętli: stan wysłanych umów i ponowne przepisanie podpisanych.

    Wyłączone Autenti albo moduł = ``disabled``; każda umowa we własnej
    transakcji (blokada ``SKIP LOCKED`` — wysyłka z ekranu nie czeka).
    """

    if not agreements.autenti_configured():
        return {"status": "disabled", "reason": "autenti_off"}
    if not await agreements.load_enabled(db):
        return {"status": "disabled", "reason": "module_off"}
    moment = now or _now()
    run_id = await job_runs.claim(db, JOB_KIND, _slot(moment), moment)
    if run_id is None:
        return {"status": "skipped", "reason": "already_ran"}
    ids = list(
        (
            await db.scalars(
                select(HrAgreement.id)
                .where(
                    or_(
                        HrAgreement.status == "sent",
                        and_(
                            HrAgreement.status == "signed",
                            HrAgreement.applied_at.is_(None),
                            HrAgreement.signing_channel == "autenti",
                        ),
                    )
                )
                .order_by(HrAgreement.updated_at)
                .limit(BATCH_LIMIT)
            )
        ).all()
    )
    counts: dict[str, int] = {"checked": 0, "errors": 0}
    error: Optional[str] = None
    try:
        async with client_factory() as client:
            for agreement_id in ids:
                try:
                    agreement = await db.scalar(
                        select(HrAgreement)
                        .where(HrAgreement.id == agreement_id)
                        .with_for_update(skip_locked=True)
                        .execution_options(populate_existing=True)
                    )
                    if agreement is None:
                        continue
                    outcome = await sync_process(db, agreement, client)
                    await db.commit()
                    counts["checked"] += 1
                    counts[outcome] = counts.get(outcome, 0) + 1
                except Exception:  # noqa: BLE001 — jedna umowa nie zatrzymuje reszty
                    await db.rollback()
                    counts["errors"] += 1
                    logger.exception(
                        "[agreements] stan umowy %s nie wyszedł", agreement_id
                    )
    except (AutentiError, RuntimeError) as exc:
        error = f"Autenti: {exc.__class__.__name__}"
    await job_runs.finish(
        db,
        run_id,
        status="failed" if error else "done",
        counts=counts,
        error=error,
    )
    return {"status": "error" if error else "ok", **counts}


__all__ = [
    "AUTENTI_OFF_DETAIL",
    "JOB_KIND",
    "cancel",
    "client_factory",
    "mark_signed",
    "on_autenti_process",
    "retry_apply",
    "run_once",
    "scan_mime",
    "send",
    "sync_process",
    "withdraw",
]
