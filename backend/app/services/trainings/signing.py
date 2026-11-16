"""Podpis umowy szkoleniowej: trener, potem reprezentant B2B Network.

Te same reguły co podpis umowy B2B w NEXUSIE (``podpis-umowy-b2b-w-nexusie.md``):

* każdy podpis kwalifikowany (umowa przenosi prawa autorskie, § 17 wzoru),
  rozstrzyga ``b2b_esign.verdict.judge`` z walidatorem z ``B2B_ESIGN_VALIDATOR``;
* wgrany plik zaczyna się bajtami poprzedniej wersji (``verdict.builds_on``):
  trener podpisuje zamrożony PDF umowy, firma plik podpisany przez trenera;
* walidacja (do 30 s) bez blokady wiersza, potem ``SELECT … FOR UPDATE``
  i ponowne sprawdzenie stanu i odcisku;
* za firmę wystarczy podpis kwalifikowany JEDNEJ osoby z listy
  ``company_signer_ids`` (``b2b_esign/settings.py``), a wgrać plik może tylko
  osoba z tej listy.

Komunikaty, które widzi trener, nie mają myślnika „—” (reguła z drogi B2B).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_config
from app.models.training import Training
from app.models.user import User
from app.services.b2b_esign import settings as esign_settings
from app.services.b2b_esign.qualified import QualifiedValidator
from app.services.b2b_esign.service import MAX_UPLOAD_BYTES, Validator
from app.services.b2b_esign.verdict import (
    MSG_NOT_PDF,
    MSG_NOT_SIGNED,
    Fingerprint,
    Verdict,
    judge,
    upload_problem,
)
from app.services.signing.provider import ValidationReport
from app.services.signing.validation import ValidationService
from app.services.trainings import agreement
from app.services.trainings.errors import TrainingError

MSG_NOT_FOUND = "Nie ma takiego szkolenia."
MSG_TOO_BIG = "Plik jest za duży, może mieć najwyżej 20 MB."
MSG_NOT_FOR_TRAINER = "Ta umowa nie czeka na Twój podpis."
MSG_NO_AGREEMENT = "Umowa nie jest jeszcze gotowa do podpisu."
MSG_NO_PARTNER = "W umowie brakuje imienia i nazwiska trenera. Wygeneruj ją ponownie."
MSG_FILE_GONE = (
    "Nie znaleźliśmy pliku umowy w NEXUSIE. Skontaktuj się z osobą z B2B Network."
)
MSG_RACE = "Stan umowy zmienił się w trakcie sprawdzania podpisu. Odśwież stronę."
MSG_NOT_SIGNER = (
    "Za B2B Network podpisuje osoba z listy reprezentantów w ustawieniach podpisu umów."
)
MSG_WAITS_FOR_TRAINER = "Umowa czeka jeszcze na podpis trenera."
MSG_NOT_FOR_COMPANY = "Ta umowa nie czeka na podpis B2B Network."

#: Kod wyroku walidacji → (status HTTP, kod dla frontu).
_VERDICT_ERRORS: dict[str, tuple[int, str]] = {
    "no_validator": (503, "no_validator"),
    "no_signature": (422, "not_signed"),
    "missing_signer": (422, "missing_signer"),
    "same_person": (422, "same_person"),
}


def default_validator() -> Validator:
    """pyHanko z listą zaufanych UE albo EU DSS, jak ``api/b2b_esign._validator``."""
    if app_config.B2B_ESIGN_VALIDATOR.strip().lower() == "dss":
        return ValidationService()
    return QualifiedValidator()


# ── Czyste kroki ─────────────────────────────────────────────────────────────


def check_pdf(data: bytes) -> None:
    if len(data) > MAX_UPLOAD_BYTES:
        raise TrainingError(413, MSG_TOO_BIG, "too_big")
    if not data.startswith(b"%PDF-"):
        raise TrainingError(415, MSG_NOT_PDF, "not_pdf")


def check_builds_on(data: bytes, previous: Fingerprint) -> None:
    """Plik to poprzednia wersja + dopisany podpis; ten sam plik = brak podpisu."""
    problem = upload_problem(data, previous)
    if problem is None:
        return
    code = "not_signed" if problem == MSG_NOT_SIGNED else "not_built_on"
    raise TrainingError(422, problem, code)


def verdict_error(verdict: Verdict) -> TrainingError:
    status, code = _VERDICT_ERRORS.get(verdict.code or "", (422, "not_qualified"))
    return TrainingError(status, verdict.message or MSG_NOT_SIGNED, code)


async def validate_signature(
    data: bytes,
    validator: Validator,
    *,
    required_signers: list[str],
    any_of_signers: Sequence[str] = (),
) -> ValidationReport:
    report = await validator.validate(data)
    verdict = judge(
        report,
        authoritative=validator.authoritative,
        required_signers=required_signers,
        any_of_signers=any_of_signers,
    )
    if not verdict.accepted:
        raise verdict_error(verdict)
    return report


def representative_names(
    signer_ids: Sequence[int], names: Mapping[int, str], *, fallback: str
) -> list[str]:
    """Imiona i nazwiska reprezentantów w kolejności z ustawień; bez żadnego
    znanego nazwiska — osoba, która wgrywa plik (jak droga B2B)."""
    found = [names[uid] for uid in signer_ids if (names.get(uid) or "").strip()]
    return found or [fallback]


def trainer_name(training: Training) -> str:
    name = str((training.partner or {}).get("full_name") or "").strip()
    if not name:
        raise TrainingError(409, MSG_NO_PARTNER, "partner_missing")
    return name


def fingerprint_of(
    relative: str, *, expected_sha256: Optional[str] = None
) -> Fingerprint:
    """Odcisk pliku z dysku; ``expected_sha256`` = odcisk zapisany w bazie."""
    try:
        found = Fingerprint.of(agreement.read_file(relative))
    except FileNotFoundError as error:
        raise TrainingError(409, MSG_FILE_GONE, "file_missing") from error
    if expected_sha256 is not None and found.sha256 != expected_sha256:
        raise TrainingError(409, MSG_RACE, "agreement_changed")
    return found


def _signed_name(prefix: str, data: bytes) -> str:
    return f"{prefix}-{hashlib.sha256(data).hexdigest()[:16]}.pdf"


async def _lock(db: AsyncSession, training_id: int) -> Training:
    locked = await db.scalar(
        select(Training)
        .where(Training.id == training_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None:
        raise TrainingError(404, MSG_NOT_FOUND, "not_found")
    return locked


# ── Trener ───────────────────────────────────────────────────────────────────


async def trainer_upload(
    db: AsyncSession,
    training_id: int,
    data: bytes,
    *,
    now: datetime,
    validator: Optional[Validator] = None,
) -> Training:
    """Plik umowy podpisany przez trenera. Nie commituje zapisu (commit przed
    walidacją zamyka tylko transakcję do odczytu — jak w drodze B2B).

    Uprawnienie trenera do tego szkolenia sprawdza wołający."""
    check_pdf(data)
    training = await db.get(Training, training_id)
    if training is None:
        raise TrainingError(404, MSG_NOT_FOUND, "not_found")
    if training.status != "accepted" or training.trainer_signed_at is not None:
        raise TrainingError(409, MSG_NOT_FOR_TRAINER, "wrong_status")
    if not training.agreement_pdf_path or not training.agreement_pdf_sha256:
        raise TrainingError(409, MSG_NO_AGREEMENT, "wrong_status")
    name = trainer_name(training)
    frozen = fingerprint_of(
        training.agreement_pdf_path, expected_sha256=training.agreement_pdf_sha256
    )
    check_builds_on(data, frozen)
    # Walidacja trwa do 30 s: bez otwartej transakcji i blokady. ``commit``
    # (nic nie zmieniono), nie ``rollback`` — patrz ``b2b_esign.service``.
    await db.commit()
    await validate_signature(
        data, validator or default_validator(), required_signers=[name]
    )

    locked = await _lock(db, training_id)
    if (
        locked.status != "accepted"
        or locked.trainer_signed_at is not None
        or locked.agreement_pdf_sha256 != frozen.sha256
    ):
        raise TrainingError(409, MSG_RACE, "race")
    locked.trainer_signed_pdf_path = agreement.store_file(
        locked.id, _signed_name("podpisana-przez-trenera", data), data
    )
    locked.trainer_signed_at = now
    locked.status = "trainer_signed"
    await db.flush()
    return locked


# ── Reprezentant B2B Network ─────────────────────────────────────────────────


async def is_company_signer(db: AsyncSession, user: User) -> bool:
    current = await esign_settings.load(db)
    return user.id in current.company_signer_ids


async def _names(db: AsyncSession, ids: Sequence[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(list(ids))))
    return {uid: name for uid, name in rows.all()}


async def company_upload(
    db: AsyncSession,
    training_id: int,
    data: bytes,
    *,
    user: User,
    now: datetime,
    validator: Optional[Validator] = None,
) -> Training:
    """Plik podpisany przez trenera i reprezentanta → umowa ``signed``."""
    check_pdf(data)
    user_id, user_name = user.id, user.name
    current = await esign_settings.load(db)
    if user_id not in current.company_signer_ids:
        raise TrainingError(403, MSG_NOT_SIGNER, "not_signer")
    training = await db.get(Training, training_id)
    if training is None:
        raise TrainingError(404, MSG_NOT_FOUND, "not_found")
    if training.status == "accepted":
        raise TrainingError(409, MSG_WAITS_FOR_TRAINER, "wrong_status")
    if training.status != "trainer_signed" or not training.trainer_signed_pdf_path:
        raise TrainingError(409, MSG_NOT_FOR_COMPANY, "wrong_status")
    name = trainer_name(training)
    signed_path = training.trainer_signed_pdf_path
    previous = fingerprint_of(signed_path)
    check_builds_on(data, previous)
    signer_ids = current.company_signer_ids
    representatives = representative_names(
        signer_ids, await _names(db, signer_ids), fallback=user_name
    )
    await db.commit()  # jak wyżej: bez transakcji na czas walidacji
    await validate_signature(
        data,
        validator or default_validator(),
        required_signers=[name],
        # Za firmę wystarczy podpis jednej osoby z listy, niekoniecznie tej,
        # która wgrywa plik (decyzja Artura 26.10.2026 w drodze B2B).
        any_of_signers=representatives,
    )

    locked = await _lock(db, training_id)
    if (
        locked.status != "trainer_signed"
        or locked.trainer_signed_pdf_path != signed_path
    ):
        raise TrainingError(409, MSG_RACE, "race")
    locked.company_signed_pdf_path = agreement.store_file(
        locked.id, _signed_name("podpisana-przez-obie-strony", data), data
    )
    locked.company_signed_at = now
    locked.company_signed_by = user_id
    locked.status = "signed"
    await db.flush()
    return locked
