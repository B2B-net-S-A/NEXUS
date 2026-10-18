"""Co robi podpisana umowa (etap 5, E5) — przepisanie do kartoteki, jedno miejsce.

Po podpisie (Autenti albo ręcznie ze skanem), w jednej transakcji
i idempotentnie (``hr_agreements.applied_at``):

1. umowa (nie aneks): forma współpracy i potwierdzanie godzin w kartotece —
   zwykłą zmianą kartoteki (``people.update_profile``: reguły formy, ślad),
2. stawka od daty w historii stawek (``payroll_rates.set_rate``: 1. dzień
   miesiąca, zamknięty miesiąc płac = odmowa, minimalna stawka zlecenia,
   dzwonek osobie bez kwoty). Ta sama stawka co obowiązująca = bez zmiany,
3. dokument w e-teczce osoby (``documents.attach_generated`` modułu
   dokumentów osoby) z odnośnikiem do umowy,
4. UoP i zlecenie: znacznik „do Symfonii przy najbliższym eksporcie”
   (``symfonia_pending``) — nowa umowa do założenia w Symfonii; eksport
   Płac czyta ``pending_for_symfonia`` i po pobraniu paczki woła
   ``mark_symfonia_exported``. B2B do Symfonii nie idzie.

Odmowa któregoś kroku cofa wszystkie (punkt zapisu). Przy podpisie ręcznym
odmowa wraca do Kadr od razu (nic się nie zapisuje); przy podpisie w Autenti
umowa zostaje podpisana z ``apply_error`` i „Przepisz ponownie”.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.hr_agreement import HrAgreement
from app.models.user import User
from app.services.hr import audit, documents, payroll_rates, people
from app.services.hr.agreements import rate_from, title
from app.services.hr.agreements_errors import AgreementConflict, AgreementError
from app.services.hr.payroll_errors import PayrollError
from app.services.hr_agreements_schema import ERROR_MAX_LENGTH
from app.services.hr_foundation_schema import EmploymentType

logger = logging.getLogger(__name__)

#: Rodzaj i źródło dokumentu w e-teczce (słownik modułu dokumentów osoby, E4:
#: ``hr_documents_schema.DOCUMENT_KINDS``, ``GENERATED_SOURCES``).
DOCUMENT_KINDS: dict[str, str] = {"agreement": "contract", "annex": "annex"}
DOCUMENT_SOURCE = documents.SOURCE_AGREEMENT
#: Formy, których nowa umowa idzie do Symfonii (B2B rozlicza księgowość).
SYMFONIA_FORMS: frozenset[str] = frozenset(
    {EmploymentType.uop, EmploymentType.zlecenie}
)


async def attach_document(
    db: AsyncSession,
    agreement: HrAgreement,
    *,
    content: bytes,
    mime: str,
    actor_id: Optional[int],
) -> int:
    """Podpisana umowa w e-teczce osoby; zwraca identyfikator dokumentu.

    Idempotentne po źródle i numerze umowy (ponowne przepisanie zwraca ten sam
    dokument); odmowa e-teczki (np. typ pliku) = ``AgreementError``.
    """

    try:
        document = await documents.attach_generated(
            db,
            user_id=agreement.user_id,
            kind=DOCUMENT_KINDS[agreement.kind],
            title=title(agreement),
            content=content,
            mime=mime,
            source=DOCUMENT_SOURCE,
            source_ref=str(agreement.id),
            valid_until=agreement.end_date,
            actor_id=actor_id,
        )
    except documents.HrDocumentError as exc:
        raise AgreementError(exc.message, status=exc.status_code) from exc
    return int(document.id)


async def _actor(
    db: AsyncSession, agreement: HrAgreement, actor: Optional[User]
) -> User:
    if actor is not None:
        return actor
    for user_id in (agreement.sent_by, agreement.created_by):
        if user_id is not None:
            found = await db.get(User, user_id)
            if found is not None:
                return found
    raise AgreementError(
        "Nie ma osoby z Kadr, która przygotowała umowę — przepisz ją ręcznie "
        "(„Przepisz ponownie”)."
    )


async def _apply_form(db: AsyncSession, agreement: HrAgreement, actor: User) -> bool:
    if agreement.kind != "agreement":
        return False
    try:
        profile = await people.update_profile(
            db,
            user_id=agreement.user_id,
            values={
                "employment_type": agreement.employment_type,
                "timesheet_required": agreement.hours_confirmation,
            },
            actor=actor,
        )
    except LookupError as exc:
        raise AgreementError("Ta osoba nie ma kartoteki.") from exc
    except people.HrPeopleError as exc:
        raise AgreementError(str(exc)) from exc
    return profile.employment_type == agreement.employment_type


async def _apply_rate(db: AsyncSession, agreement: HrAgreement, actor: User) -> bool:
    day = rate_from(agreement.kind, agreement.start_date)
    current = payroll_rates.rate_on(
        await payroll_rates.history(db, agreement.user_id), day
    )
    if (
        current is not None
        and current.hourly_rate == agreement.hourly_rate
        and current.currency == agreement.currency
    ):
        return False
    if (
        agreement.kind == "agreement"
        and agreement.start_date.day != 1
        and current is not None
    ):
        raise AgreementError(
            f"Osoba ma już inną stawkę na {day:%m.%Y}, a umowa zaczyna się w połowie "
            "miesiąca — stawkę od 1. dnia miesiąca ustawiają Płace."
        )
    try:
        await payroll_rates.set_rate(
            db,
            user_id=agreement.user_id,
            hourly_rate=agreement.hourly_rate,
            currency=agreement.currency,
            effective_from=day,
            reason=f"{title(agreement)} (umowa nr {agreement.id})",
            actor_id=actor.id,
            today=business_today(),
        )
    except PayrollError as exc:
        raise AgreementError(exc.message, status=exc.status_code) from exc
    return True


async def apply_signed(
    db: AsyncSession,
    agreement: HrAgreement,
    *,
    content: bytes,
    mime: str,
    actor: Optional[User],
) -> bool:
    """Przepisanie podpisanej umowy; ``False`` = już przepisana (nic nie robi)."""

    if agreement.applied_at is not None:
        return False
    if agreement.status != "signed":
        raise AgreementConflict("Do kartoteki przechodzi tylko podpisana umowa.")
    by = await _actor(db, agreement, actor)
    form_changed = await _apply_form(db, agreement, by)
    rate_set = await _apply_rate(db, agreement, by)
    agreement.document_id = await attach_document(
        db, agreement, content=content, mime=mime, actor_id=by.id
    )
    agreement.symfonia_pending = agreement.employment_type in SYMFONIA_FORMS
    agreement.applied_at = datetime.now(timezone.utc)
    agreement.apply_error = None
    await db.flush()
    audit.record(
        db,
        actor_user_id=by.id,
        subject_user_id=agreement.user_id,
        entity_type="hr_agreement",
        entity_id=agreement.id,
        action="agreement_applied",
        sensitivity="payroll",
        details={
            "rate_from": rate_from(agreement.kind, agreement.start_date).isoformat(),
            "hourly_rate": str(agreement.hourly_rate),
            "currency": agreement.currency,
            "rate_set": rate_set,
            "form": agreement.employment_type
            if agreement.kind == "agreement"
            else None,
            "form_applied": form_changed,
            "document_id": agreement.document_id,
            "symfonia_pending": agreement.symfonia_pending,
        },
    )
    return True


async def try_apply(
    db: AsyncSession,
    agreement: HrAgreement,
    *,
    content: bytes,
    mime: str,
    actor: Optional[User],
) -> Optional[str]:
    """``apply_signed`` w punkcie zapisu; odmowa = ``apply_error`` (zwraca zdanie)."""

    agreement_id, user_id = agreement.id, agreement.user_id
    actor_id = actor.id if actor is not None else None
    try:
        async with db.begin_nested():
            await apply_signed(db, agreement, content=content, mime=mime, actor=actor)
        return None
    except AgreementError as exc:
        reason = exc.message
    except Exception:  # noqa: BLE001 — podpis zostaje, przepisanie do ponowienia
        logger.exception("[agreements] przepisanie umowy %s nie wyszło", agreement_id)
        reason = "Nie udało się przepisać umowy do kartoteki — spróbuj ponownie."
    # Wycofany punkt zapisu wygasza zmienione w nim obiekty — odśwież przed zapisem.
    await db.refresh(agreement)
    agreement.apply_error = reason[:ERROR_MAX_LENGTH]
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=user_id,
        entity_type="hr_agreement",
        entity_id=agreement_id,
        action="agreement_apply_failed",
        details={"reason": reason[:ERROR_MAX_LENGTH]},
    )
    await db.flush()
    return reason


# ── Symfonia (eksport Płac, R-C) ──────────────────────────────────────────────


async def pending_for_symfonia(db: AsyncSession) -> list[dict[str, Any]]:
    """Nowe umowy i aneksy UoP i zleceń do założenia w Symfonii (bez kwot w treści).

    Pozycja „do zrobienia ręcznie” w zestawieniu paczki dla Płac: kto, jaka
    umowa, od kiedy. Stawkę Płace widzą w NEXUSIE (historia stawek).
    """

    rows = (
        await db.execute(
            select(HrAgreement, User.name)
            .join(User, User.id == HrAgreement.user_id)
            .where(HrAgreement.symfonia_pending.is_(True))
            .order_by(User.name, HrAgreement.start_date)
        )
    ).all()
    return [
        {
            "agreement_id": agreement.id,
            "user_id": agreement.user_id,
            "name": name,
            "kind": agreement.kind,
            "employment_type": agreement.employment_type,
            "title": title(agreement),
            "start_date": agreement.start_date.isoformat(),
            "todo": (
                f"{name}: {title(agreement).lower()} — "
                + (
                    "wpisz zmianę stawki w umowie w Symfonii."
                    if agreement.kind == "annex"
                    else "załóż umowę w Symfonii (zgłoszenie ZUS) przed importem."
                )
            ),
        }
        for agreement, name in rows
    ]


async def mark_symfonia_exported(
    db: AsyncSession, agreement_ids: list[int], *, actor_id: Optional[int]
) -> int:
    """Znacznik zdjęty po pobraniu paczki dla Płac; zwraca liczbę umów."""

    if not agreement_ids:
        return 0
    result = await db.execute(
        update(HrAgreement)
        .where(
            HrAgreement.id.in_(agreement_ids),
            HrAgreement.symfonia_pending.is_(True),
        )
        .values(symfonia_pending=False, symfonia_exported_at=datetime.now(timezone.utc))
        .returning(HrAgreement.id)
    )
    exported = list(result.scalars().all())
    if exported:
        audit.record(
            db,
            actor_user_id=actor_id,
            subject_user_id=None,
            entity_type="hr_agreement",
            entity_id=None,
            action="agreements_exported_to_symfonia",
            details={"agreement_ids": exported},
        )
    return len(exported)


__all__ = [
    "DOCUMENT_KINDS",
    "DOCUMENT_SOURCE",
    "SYMFONIA_FORMS",
    "apply_signed",
    "attach_document",
    "mark_symfonia_exported",
    "pending_for_symfonia",
    "try_apply",
]
