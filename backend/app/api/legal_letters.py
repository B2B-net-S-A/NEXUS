"""Pismo na stronie kontraktu (asystent prawny, część F).

* ``POST /api/contracts/{id}/legal-letter/draft`` — szkic pisma: wzór
  Generatora wypełniony kodem albo zdania modelu (``legal_assistant``, F57)
  ze sprawdzonymi cytatami. Niczego nie zapisuje.
* ``POST /api/contracts/{id}/legal-letter/docx`` — to samo pismo jako DOCX
  (wzór: plik wzoru; model: tekst po poprawkach człowieka). Niczego nie
  zapisuje — do Dokumentów kontraktu plik idzie zwykłym „Dodaj plik”.
* ``POST /api/contracts/{id}/legal-letter/approve`` — „Zatwierdzam”: cytaty
  sprawdzone jeszcze raz z tekstem źródeł z bazy; cytat ``missing`` /
  ``mismatch`` albo pytanie o formę bez odpowiedzi = 409. Zamyka zadanie
  „szkic odpowiedzi na wypowiedzenie czeka”.

Bramka = pobranie dokumentu kontraktu (pismo czyta treść podpisanej umowy,
w tym stawki): sekcja Delivery, „Stawki i kwoty: podgląd”
(``AmountsViewUser``) i zakres klienta Delivery Leada
(``_assert_contract_document_client_access``). ``draft`` i ``docx`` są
odczytem (``READ_ONLY_POST_ROUTE_TEMPLATES``), jak „Popraw dokument” (część D);
``approve`` zapisuje stan zadania, więc wymaga zapisu w Delivery.
Reguła: ``docs/claude/asystent-prawny/pismo-na-kontrakcie-i-zadania-asystenta.md``.
"""

# UWAGA: bez `from __future__ import annotations` — PEP 563 + slowapi #579
# (ciało żądania trafiłoby do parametrów query → 422).

from datetime import date
from typing import Any, Literal, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import _assert_contract, _assert_contract_document_client_access
from app.api.legal import _check_out, _passage_out
from app.api.permission_access import AmountsViewUser
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.core.scheduling import business_today
from app.models.contract import Contract
from app.models.user import User
from app.services.legal import citations, letter_service, letters, tasks
from app.services.legal.tasks_schema import STATUS_DONE

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DISCLAIMER = (
    "Szkic asystenta nie jest poradą prawną. Pismo zatwierdza i wysyła człowiek."
)

LetterKindKey = Literal[
    "notice_reply",
    "termination_notice",
    "termination_agreement",
    "notice_withdrawal",
    "penalty_note",
    "client_letter",
]


class LetterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: LetterKindKey
    instruction: str = Field("", max_length=2000)
    delivered_on: Optional[date] = None
    termination_date: Optional[date] = None
    original_confirmed: bool = False
    penalty_amount: Optional[float] = Field(None, gt=0, le=10_000_000)
    payment_days: int = Field(letters.PENALTY_PAYMENT_DAYS, ge=1, le=60)

    def letter_request(self) -> letter_service.LetterRequest:
        return letter_service.LetterRequest(
            kind=self.kind,
            instruction=self.instruction,
            delivered_on=self.delivered_on,
            termination_date=self.termination_date,
            original_confirmed=self.original_confirmed,
            penalty_amount=self.penalty_amount,
            payment_days=self.payment_days,
        )


class LetterTextIn(LetterIn):
    #: Tekst pisma modelu po poprawkach człowieka; pismo ze wzoru serwer składa sam.
    text: str = Field("", max_length=60_000)


async def _readable_contract(
    db: AsyncSession, contract_id: int, user: User
) -> Contract:
    contract = await _assert_contract(db, contract_id, user)
    await _assert_contract_document_client_access(contract, user, db)
    return contract


def _counts(checks: list[citations.CitationCheck]) -> dict[str, int]:
    return {
        status: sum(1 for c in checks if c.status == status)
        for status in (
            citations.STATUS_OK,
            citations.STATUS_MISSING,
            citations.STATUS_MISMATCH,
        )
    }


def _warning_out(warning: Optional[letters.FormWarning]) -> Optional[dict[str, Any]]:
    if warning is None:
        return None
    return {
        "level": warning.level,
        "title": warning.title,
        "message": warning.message,
        "clause_ref": warning.clause_ref,
        "document_name": warning.document_name,
        "actions": list(warning.actions),
    }


def _task_key(contract: Contract, kind: letters.LetterKind) -> Optional[str]:
    signed_on = contract.agreement_termination_signed_on
    if (
        kind.closes_notice_task
        and contract.agreement_termination_party == letter_service.PARTNER_PARTY
        and contract.agreement_termination_mode == letter_service.PARTNER_NOTICE_MODE
        and signed_on is not None
    ):
        return tasks.notice_task_key(contract.id, signed_on)
    return None


def _letter_out(contract: Contract, letter: letter_service.Letter) -> dict[str, Any]:
    approval = letter.approval
    recipient = letter.recipient
    return {
        "kind": letter.kind.key,
        "label": letter.kind.label,
        "source": letter.kind.source,
        "editable": letter.kind.source == letters.SOURCE_MODEL,
        "template": letter.kind.template,
        "subject": letter.subject,
        "text": letter.text,
        "recipient": {
            "kind": recipient.kind,
            "name": recipient.name,
            "lines": list(recipient.lines),
            "email": recipient.email,
            "candidate_id": recipient.candidate_id,
        },
        "facts": [
            {"label": f.label, "value": f.value, "note": f.note, "tone": f.tone}
            for f in letter.facts
        ],
        "steps": list(letter.steps),
        "deadline_note": letter.deadline_note,
        "warning": _warning_out(letter.warning),
        "checks": [_check_out(c) for c in letter.checks],
        "counts": _counts(letter.checks),
        "blocked": approval.blocked,
        "block_reasons": list(approval.reasons),
        "issues": letter.issues,
        "lawyer_review": letter.lawyer_review,
        "passages": [_passage_out(p) for p in letter.passages],
        "notes": letter.notes,
        "model": letter.model,
        "error": letter.error,
        "task_key": _task_key(contract, letter.kind),
        "disclaimer": DISCLAIMER,
    }


def _unavailable(exc: letter_service.LetterUnavailable) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


def _blocked(review: letter_service.TextReview) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "message": "Pisma nie da się zatwierdzić: "
            + " ".join(review.approval.reasons),
            "reasons": list(review.approval.reasons),
            "checks": [_check_out(c) for c in review.checks],
        },
    )


@router.post("/contracts/{contract_id}/legal-letter/draft")
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def draft_contract_letter(
    request: Request,
    contract_id: int,
    body: LetterIn,
    current_user: AmountsViewUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Szkic pisma ze sprawdzonymi cytatami. ``request`` — wymóg slowapi."""
    contract = await _readable_contract(db, contract_id, current_user)
    try:
        letter = await letter_service.build_letter(
            db, contract, body.letter_request(), user_id=current_user.id
        )
    except letter_service.LetterUnavailable as exc:
        raise _unavailable(exc) from exc
    return _letter_out(contract, letter)


async def _review(
    db: AsyncSession, contract: Contract, body: LetterTextIn
) -> letter_service.TextReview:
    try:
        return await letter_service.review_text(
            db, contract, body.letter_request(), body.text
        )
    except letter_service.LetterUnavailable as exc:
        raise _unavailable(exc) from exc


@router.post("/contracts/{contract_id}/legal-letter/docx")
async def contract_letter_docx(
    contract_id: int,
    body: LetterTextIn,
    current_user: AmountsViewUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """DOCX zatwierdzalnego pisma; zablokowane pismo = 409 (jak „Zatwierdzam”)."""
    contract = await _readable_contract(db, contract_id, current_user)
    review = await _review(db, contract, body)
    if review.approval.blocked:
        raise _blocked(review)
    if (
        review.letter is not None
        and review.letter_kind.source == letters.SOURCE_TEMPLATE
    ):
        data = letter_service.render_template_letter(
            review.letter_kind,
            await letter_service.load_context(db, contract),
            review.letter.generator_values,
            docx=True,
        )
    else:
        data = letter_service.text_docx(review.text)
    filename = f"{review.letter_kind.label} — {business_today().isoformat()}.docx"
    return Response(
        content=bytes(data),
        media_type=DOCX_MIME,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "no-store",
        },
    )


@router.post("/contracts/{contract_id}/legal-letter/approve")
async def approve_contract_letter(
    contract_id: int,
    body: LetterTextIn,
    current_user: AmountsViewUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """„Zatwierdzam”: ostatnie sprawdzenie cytatów i zamknięcie zadania po wypowiedzeniu."""
    contract = await _readable_contract(db, contract_id, current_user)
    review = await _review(db, contract, body)
    if review.approval.blocked:
        raise _blocked(review)
    key = _task_key(contract, review.letter_kind)
    if key is not None:
        await tasks.close_task(
            db,
            key=key,
            kind=tasks.KIND_NOTICE_REPLY,
            status=STATUS_DONE,
            user_id=current_user.id,
            contract_id=contract.id,
            client_id=contract.client_id,
            letter_kind=review.letter_kind.key,
        )
        await db.commit()
    return {
        "approved": True,
        "task_key": key,
        "checks": [_check_out(c) for c in review.checks],
        "counts": _counts(review.checks),
        "text": review.text,
    }
