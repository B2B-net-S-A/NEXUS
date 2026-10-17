"""Dane do rozliczeń osoby (etap 4, R6, makieta M7): NIP, wykaz VAT, rachunek, termin.

Kto (``can_view`` / ``can_edit``):

* **osoba** — widzi swoje dane (bez zmiany: numer rachunku „mailem od
  osoby” nie przechodzi bez Kadr albo Płac),
* **Kadry, Płace, admin** — widzą i zmieniają,
* **przełożony, zespół, reszta** — nie widzą nic (404, jak brak osoby).

Rachunek jest zaszyfrowany (``app/core/encryption.TokenCipher``) i zapisany
jako 26 cyfr NRB; w odpowiedziach, śladzie, logach i komunikatach błędów są
wyłącznie 4 ostatnie cyfry i źródło. Na B2B rachunek wybiera się z białej
listy VAT (``white_list.search`` + ``white_list.check`` z identyfikatorem
zapytania jako dowodem); rachunek wpisany ręcznie (wykaz wyłączony albo osoby
w nim nie ma) zapisuje się, ale zapłata wymaga drugiej osoby (R7, R10 —
``settlements_rules.problems_of``). Na zleceniu i UoP rachunek wpisują Kadry
z umowy. Zmiana NIP-u kasuje rachunek z wykazu (sprawdzenie dotyczyło
poprzedniego NIP-u) i dane z wykazu.

PESEL nie trafia do NEXUSA: identyfikator osoby w Symfonii to GUID albo numer
ewidencyjny, a 11 cyfr z poprawną sumą kontrolną PESEL-u jest odrzucane.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import date
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.encryption import TokenCipherNotConfigured, get_token_cipher
from app.core.scheduling import local_now
from app.models.hr_profile import EmployeeProfile
from app.models.hr_settlement import EmployeeBillingDetails
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.hr import audit, settlements, white_list
from app.services.hr.payroll_errors import PayrollError
from app.services.hr_settlement_schema import TERMS_MAX_DAYS

SYMFONIA_ID_RE = re.compile(r"^[A-Za-z0-9{}\-/._]{1,64}$")
_PESEL_WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
NOT_FOUND = "Nie ma takiej osoby."
CIPHER_MISSING = (
    "Szyfrowanie danych do przelewu nie jest skonfigurowane — rachunku nie zapisano."
)


class BillingError(PayrollError):
    """Błąd danych do rozliczeń — komunikat bez numeru rachunku."""


# ── Dostęp ────────────────────────────────────────────────────────────────────


def can_edit(user: User) -> bool:
    """Kadry, Płace i admin zmieniają dane do rozliczeń."""

    return (
        user.has_role(UserRole.admin)
        or has_permission(user, ProductAction.people_admin)
        or has_permission(user, ProductAction.payroll)
    )


def can_view(user: User, subject_id: int) -> bool:
    """Osoba, Kadry, Płace, admin — przełożony nie (dane wrażliwe, M7)."""

    return user.id == subject_id or can_edit(user)


# ── Numery ────────────────────────────────────────────────────────────────────


def looks_like_pesel(value: str) -> bool:
    """11 cyfr z poprawną sumą kontrolną PESEL-u."""

    if len(value) != 11 or not value.isdigit():
        return False
    total = sum(int(digit) * weight for digit, weight in zip(value, _PESEL_WEIGHTS))
    return (10 - total % 10) % 10 == int(value[10])


def clean_nip(raw: Optional[str]) -> Optional[str]:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return white_list.clean_nip(text)
    except white_list.WhiteListError as exc:
        raise BillingError(exc.message) from None


def clean_account(raw: str) -> str:
    if len(raw) > 64:
        raise BillingError(white_list.ERROR_MESSAGES["invalid_account"])
    try:
        return white_list.normalize_account(raw)
    except white_list.WhiteListError as exc:
        # Komunikat wykazu nie zawiera numeru; wyjątek źródłowy też nie idzie dalej.
        raise BillingError(exc.message) from None


def clean_symfonia_id(raw: Optional[str]) -> Optional[str]:
    text = (raw or "").strip()
    if not text:
        return None
    if looks_like_pesel(text):
        raise BillingError(
            "To wygląda na PESEL — PESEL zostaje w Symfonii. Wpisz identyfikator "
            "osoby z Symfonii (GUID albo numer ewidencyjny)."
        )
    if not SYMFONIA_ID_RE.match(text):
        raise BillingError(
            "Identyfikator z Symfonii: do 64 znaków — litery, cyfry, myślnik, kropka."
        )
    return text


def clean_terms(raw: Any) -> int:
    if isinstance(raw, bool):
        raise BillingError(f"Termin płatności: od 0 do {TERMS_MAX_DAYS} dni.")
    try:
        days = int(raw)
    except (TypeError, ValueError):
        raise BillingError(f"Termin płatności: od 0 do {TERMS_MAX_DAYS} dni.") from None
    if not 0 <= days <= TERMS_MAX_DAYS:
        raise BillingError(f"Termin płatności: od 0 do {TERMS_MAX_DAYS} dni.")
    return days


def _encrypt(account: str) -> str:
    try:
        return get_token_cipher().encrypt(account)
    except TokenCipherNotConfigured:
        raise BillingError(CIPHER_MISSING, 503) from None


def decrypt_account(details: Optional[EmployeeBillingDetails]) -> Optional[str]:
    """Rachunek do przelewu (26 cyfr NRB) — wyłącznie dla paczki przelewów."""

    if details is None or not details.account_encrypted:
        return None
    return get_token_cipher().decrypt(details.account_encrypted)


def account_fingerprint(account: str) -> str:
    """Skrót HMAC-SHA256 pełnego rachunku (64 znaki hex) — do porównań, nie do odczytu.

    Paczka przelewów pamięta go zamiast numeru: 4 ostatnie cyfry nie wykryją
    podmiany na rachunek z tą samą końcówką. Klucz pochodzi z tego samego
    sekretu co szyfrowanie rachunku (bez nowej zmiennej), z osobnym
    przeznaczeniem — skrót nie jest kluczem szyfru. Brak sekretu =
    ``TokenCipherNotConfigured``, jak przy odszyfrowaniu.
    """

    secret = settings.M365_TOKEN_ENCRYPTION_KEY
    if not secret:
        raise TokenCipherNotConfigured("brak klucza szyfrowania rachunków")
    key = hashlib.sha256(b"nexus-hr-payee-account:" + secret.encode()).digest()
    return hmac.new(key, account.encode(), hashlib.sha256).hexdigest()


def _set_account(
    details: EmployeeBillingDetails,
    account: Optional[str],
    *,
    source: Optional[str],
    request_id: Optional[str] = None,
) -> None:
    if account is None:
        details.account_encrypted = None
        details.account_last4 = None
        details.account_source = None
        details.account_check_request_id = None
        details.account_checked_at = None
        return
    details.account_encrypted = _encrypt(account)
    details.account_last4 = account[-4:]
    details.account_source = source
    details.account_check_request_id = request_id[:64] if request_id else None
    details.account_checked_at = local_now() if request_id else None


# ── Odczyt ────────────────────────────────────────────────────────────────────


async def profile_of(db: AsyncSession, user_id: int) -> Optional[EmployeeProfile]:
    return await db.scalar(
        select(EmployeeProfile).where(EmployeeProfile.user_id == user_id)
    )


async def require_subject(
    db: AsyncSession, user: User, user_id: int
) -> EmployeeProfile:
    """Kartoteka osoby, której dane czytamy; brak dostępu = 404 (nie zdradzamy)."""

    profile = await profile_of(db, user_id)
    if profile is None or not can_view(user, user_id):
        raise BillingError(NOT_FOUND, 404)
    return profile


async def get_details(
    db: AsyncSession, user_id: int
) -> Optional[EmployeeBillingDetails]:
    return await settlements.billing_of(db, user_id)


def payload(
    details: Optional[EmployeeBillingDetails],
    *,
    user_id: int,
    employment_type: Optional[str],
    editable: bool,
) -> dict[str, Any]:
    """Odpowiedź bez numeru rachunku — tylko 4 ostatnie cyfry i źródło."""

    return {
        "user_id": user_id,
        "employment_type": employment_type,
        "can_edit": editable,
        "nip": details.nip if details else None,
        "registry_name": details.registry_name if details else None,
        "vat_status": details.vat_status if details else None,
        "vat_checked_at": details.vat_checked_at.isoformat()
        if details and details.vat_checked_at
        else None,
        "account_last4": details.account_last4 if details else None,
        "account_source": details.account_source if details else None,
        "account_checked_at": details.account_checked_at.isoformat()
        if details and details.account_checked_at
        else None,
        "payment_terms_days": details.payment_terms_days if details else 14,
        "symfonia_id": details.symfonia_id if details else None,
        "updated_at": details.updated_at.isoformat()
        if details and details.updated_at
        else None,
        # Na B2B rachunek spoza wykazu VAT = zapłata wymaga drugiej osoby (R10).
        "needs_second_person": bool(
            employment_type == "b2b"
            and (details is None or details.account_source != "white_list")
        ),
    }


# ── Zapis ─────────────────────────────────────────────────────────────────────


async def _locked_or_new(db: AsyncSession, user_id: int) -> EmployeeBillingDetails:
    await db.execute(
        pg_insert(EmployeeBillingDetails)
        .values(user_id=user_id)
        .on_conflict_do_nothing(index_elements=[EmployeeBillingDetails.user_id])
    )
    details = await db.scalar(
        select(EmployeeBillingDetails)
        .where(EmployeeBillingDetails.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert details is not None
    return details


async def _assert_nip_free(db: AsyncSession, nip: str, user_id: int) -> None:
    owners = await settlements.users_with_nip(db, nip)
    if any(owner != user_id for owner in owners):
        raise BillingError(
            "Ten NIP ma już w danych do rozliczeń inna osoba — sprawdź, czyja to firma.",
            409,
        )


def _change_nip(details: EmployeeBillingDetails, nip: Optional[str]) -> bool:
    if nip == details.nip:
        return False
    details.nip = nip
    details.registry_name = None
    details.vat_status = None
    details.vat_checked_at = None
    if details.account_source == "white_list":
        _set_account(details, None, source=None)
    return True


def _audit(
    db: AsyncSession,
    details: EmployeeBillingDetails,
    *,
    actor_id: Optional[int],
    action: str,
    fields: list[str],
) -> None:
    # Bez numeru rachunku — tylko nazwy pól, 4 cyfry i źródło.
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=details.user_id,
        entity_type="employee_billing_details",
        entity_id=details.id,
        action=action,
        sensitivity="payroll",
        details={
            "fields": fields,
            "account_last4": details.account_last4,
            "account_source": details.account_source,
        },
    )


async def update_details(
    db: AsyncSession,
    *,
    actor: User,
    user_id: int,
    changes: dict[str, Any],
) -> EmployeeBillingDetails:
    """Zmiana NIP-u, terminu, identyfikatora z Symfonii albo rachunku ręcznego.

    ``changes`` niesie tylko pola, które się zmieniają: ``nip`` (pusty = usuń),
    ``payment_terms_days``, ``symfonia_id``, ``account`` (wpis ręczny),
    ``clear_account``.
    """

    await require_subject(db, actor, user_id)
    if not can_edit(actor):
        raise BillingError("Dane do rozliczeń zmieniają Kadry i Płace.", 403)
    details = await _locked_or_new(db, user_id)
    fields: list[str] = []
    money_relevant = False
    payee_changed = False
    if "nip" in changes:
        nip = clean_nip(changes["nip"])
        if nip is not None:
            await _assert_nip_free(db, nip, user_id)
        if _change_nip(details, nip):
            fields.append("nip")
            money_relevant = payee_changed = True
    if "payment_terms_days" in changes:
        days = clean_terms(changes["payment_terms_days"])
        if days != details.payment_terms_days:
            details.payment_terms_days = days
            fields.append("payment_terms_days")
            money_relevant = True
    if "symfonia_id" in changes:
        symfonia_id = clean_symfonia_id(changes["symfonia_id"])
        if symfonia_id != details.symfonia_id:
            details.symfonia_id = symfonia_id
            fields.append("symfonia_id")
    if changes.get("clear_account"):
        if details.account_encrypted is not None:
            _set_account(details, None, source=None)
            fields.append("account")
            money_relevant = payee_changed = True
    elif changes.get("account"):
        # Ręczny rachunek zawsze liczy się jako nowy odbiorca — nawet ten sam
        # numer wpisany drugi raz traci pochodzenie z białej listy.
        account = clean_account(str(changes["account"]))
        _set_account(details, account, source="manual")
        fields.append("account")
        money_relevant = payee_changed = True
    details.updated_by = actor.id
    await db.flush()
    if fields:
        _audit(db, details, actor_id=actor.id, action="billing_updated", fields=fields)
    if money_relevant:
        await settlements.billing_changed(db, user_id, payee_changed=payee_changed)
    await db.flush()
    return details


async def _vat_changed(
    db: AsyncSession, details: EmployeeBillingDetails, previous: Optional[str]
) -> None:
    """Status VAT decyduje, czy faktura może mieć VAT — przelicz rozliczenia."""

    if details.vat_status != previous:
        await settlements.billing_changed(db, details.user_id, payee_changed=False)


def _current_account(details: EmployeeBillingDetails) -> Optional[str]:
    try:
        return decrypt_account(details)
    except (TokenCipherNotConfigured, ValueError):
        return None


async def white_list_lookup(
    db: AsyncSession, *, actor: User, user_id: int, on_date: date
) -> dict[str, Any]:
    """„Pobierz z białej listy”: nazwa, status VAT i rachunki z wykazu (4 cyfry)."""

    await require_subject(db, actor, user_id)
    if not can_edit(actor):
        raise BillingError("Białą listę sprawdzają Kadry i Płace.", 403)
    details = await _locked_or_new(db, user_id)
    if not details.nip:
        raise BillingError("Najpierw wpisz NIP osoby.")
    try:
        entry = await white_list.search(
            db, details.nip, on_date, actor_id=actor.id, subject_user_id=user_id
        )
    except white_list.WhiteListError as exc:
        raise BillingError(exc.message, exc.http_status, code=exc.code) from None
    details.vat_checked_at = local_now()
    details.updated_by = actor.id
    previous_vat = details.vat_status
    if entry is None:
        details.registry_name = None
        details.vat_status = None
        await db.flush()
        await _vat_changed(db, details, previous_vat)
        return {"found": False, "accounts": [], "has_virtual_accounts": False}
    details.registry_name = (entry.name or "")[:255] or None
    details.vat_status = entry.vat_status
    current = decrypt_account(details) if details.account_encrypted else None
    await db.flush()
    await _vat_changed(db, details, previous_vat)
    return {
        "found": True,
        "name": details.registry_name,
        "vat_status": details.vat_status,
        "has_virtual_accounts": entry.has_virtual_accounts,
        "accounts": [
            {"ref": index, "last4": account[-4:], "selected": account == current}
            for index, account in enumerate(entry.accounts)
        ],
    }


async def select_white_list_account(
    db: AsyncSession, *, actor: User, user_id: int, ref: int, on_date: date
) -> EmployeeBillingDetails:
    """Rachunek z wykazu: wybór z listy + sprawdzenie (identyfikator zapytania = dowód)."""

    await require_subject(db, actor, user_id)
    if not can_edit(actor):
        raise BillingError("Rachunek z białej listy wybierają Kadry i Płace.", 403)
    details = await _locked_or_new(db, user_id)
    if not details.nip:
        raise BillingError("Najpierw wpisz NIP osoby.")
    try:
        entry = await white_list.search(
            db, details.nip, on_date, actor_id=actor.id, subject_user_id=user_id
        )
        if entry is None or not 0 <= ref < len(entry.accounts):
            raise BillingError(
                "Lista rachunków z wykazu się zmieniła — pobierz ją ponownie.", 409
            )
        account = entry.accounts[ref]
        result = await white_list.check(
            db,
            details.nip,
            account,
            on_date,
            actor_id=actor.id,
            subject_user_id=user_id,
        )
    except white_list.WhiteListError as exc:
        raise BillingError(exc.message, exc.http_status, code=exc.code) from None
    if not result.listed:
        raise BillingError(
            "Wykaz VAT nie potwierdził tego rachunku — pobierz listę ponownie.", 409
        )
    # Ponowne sprawdzenie tego samego rachunku z wykazu nie zmienia odbiorcy.
    same_payee = (
        details.account_source == "white_list" and _current_account(details) == account
    )
    _set_account(details, account, source="white_list", request_id=result.request_id)
    details.registry_name = (entry.name or "")[:255] or None
    details.vat_status = entry.vat_status
    details.vat_checked_at = local_now()
    details.updated_by = actor.id
    await db.flush()
    _audit(
        db,
        details,
        actor_id=actor.id,
        action="billing_account_selected",
        fields=["account"],
    )
    await settlements.billing_changed(db, user_id, payee_changed=not same_payee)
    await db.flush()
    return details


async def assign_nip(
    db: AsyncSession, *, user_id: int, nip: str, actor_id: Optional[int]
) -> EmployeeBillingDetails:
    """NIP z przypisanej ręcznie faktury (KSeF, nieznany NIP) — uzupełnia dane osoby."""

    clean = clean_nip(nip)
    if clean is None:
        raise BillingError("Brak NIP-u.")
    if await profile_of(db, user_id) is None:
        raise BillingError(NOT_FOUND, 404)
    await _assert_nip_free(db, clean, user_id)
    details = await _locked_or_new(db, user_id)
    if details.nip and details.nip != clean:
        raise BillingError(
            "Ta osoba ma w danych inny NIP — zmień go w „Danych do rozliczeń”.", 409
        )
    if _change_nip(details, clean):
        details.updated_by = actor_id
        await db.flush()
        _audit(
            db,
            details,
            actor_id=actor_id,
            action="billing_nip_assigned",
            fields=["nip"],
        )
        await settlements.billing_changed(db, user_id)
    await db.flush()
    return details


__all__ = [
    "BillingError",
    "account_fingerprint",
    "assign_nip",
    "can_edit",
    "can_view",
    "clean_account",
    "clean_nip",
    "clean_symfonia_id",
    "decrypt_account",
    "get_details",
    "looks_like_pesel",
    "payload",
    "require_subject",
    "select_white_list_account",
    "update_details",
    "white_list_lookup",
]
