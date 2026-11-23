"""Jednorazowe poprawki danych dwóch kontraktów, po których rozliczenia z poczty nie znajdowały osoby.

Przegląd 24 przypadków „bez dokumentu w poczcie” z próby IX–X 2026 (decyzja
Artura z 23.11.2026: skrypt naprawy w PR-ze):

- Kontrakt 479 (ERSTE) nie ma ``candidate_email``, kartoteka też nie ma adresu.
  Konsultant wysyła raport ze skrzynki u klienta ``imie.nazwisko@erste.pl``
  (rozliczenia@, IX i X). Adres składamy z imienia i nazwiska w kartotece, więc
  w repo nie ma żadnych danych osoby; zgodność z nadawcą maila sprawdzona na
  archiwum rozliczenia@.
- Kontrakt 627 (Bosch): w kartotece imię bez jednej litery. Adres w kartotece,
  Gmail i skrzynka u klienta mają pełne imię. Nowe imię bierzemy z pierwszego
  członu adresu ``imie.nazwisko@…`` i tylko wtedy, gdy różni się od zapisanego
  dokładnie jedną dopisaną literą, a drugi człon to nazwisko z kartoteki.

Kontrakty przypięte do trójki (kontrakt, kandydat, klient), stan produkcji
z 23.11.2026. Pominięcie z kodem powodu, gdy dane już ktoś zmienił. Zmiana idzie
do historii (``activities``), paragon pod kluczem ``REPAIR_MARKER`` niesie
wyłącznie liczby, ID i kody powodów.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, NamedTuple, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.contract import Contract

logger = logging.getLogger(__name__)

REPAIR_MARKER = "settlement_identity_data_repair_2026_11_23"

ERSTE_CLIENT_ID = 103
BOSCH_CLIENT_ID = 19
ERSTE_MAILBOX_DOMAIN = "erste.pl"

_ASCII_WORD = re.compile(r"^[A-Za-z]+$")


class Target(NamedTuple):
    contract_id: int
    candidate_id: int
    client_id: int


CONTRACT_EMAIL_TARGET = Target(479, 204927, ERSTE_CLIENT_ID)
FIRST_NAME_TARGET = Target(627, 443352, BOSCH_CLIENT_ID)


def client_mailbox_address(name: str, lastname: str, domain: str) -> Optional[str]:
    """``imie.nazwisko@domena`` małymi literami; ``None`` przy znakach spoza ASCII."""

    first, last = (name or "").strip(), (lastname or "").strip()
    if not (_ASCII_WORD.match(first) and _ASCII_WORD.match(last)):
        return None
    return f"{first}.{last}@{domain}".lower()


def first_name_from_email(name: str, lastname: str, email: str) -> Optional[str]:
    """Imię z adresu ``imie.nazwisko@…``, gdy zapisane imię różni się o jedną brakującą literę."""

    local = (email or "").split("@", 1)[0].lower()
    parts = local.split(".")
    stored = (name or "").strip().lower()
    if len(parts) != 2 or parts[1] != (lastname or "").strip().lower():
        return None
    candidate = parts[0]
    if not _ASCII_WORD.match(candidate) or len(candidate) != len(stored) + 1:
        return None
    if not any(
        candidate[:i] + candidate[i + 1 :] == stored for i in range(len(candidate))
    ):
        return None
    return candidate.capitalize()


async def _locked_contract(
    db: AsyncSession, target: Target
) -> tuple[Optional[Contract], Optional[str]]:
    contract = await db.scalar(
        select(Contract).where(Contract.id == target.contract_id).with_for_update()
    )
    if contract is None:
        return None, "contract_missing"
    if (
        contract.candidate_id != target.candidate_id
        or contract.client_id != target.client_id
    ):
        return None, "identity_mismatch"
    return contract, None


async def _fill_contract_email(db: AsyncSession, target: Target) -> dict[str, Any]:
    result: dict[str, Any] = {
        "contract_id": target.contract_id,
        "step": "candidate_email",
        "skipped": None,
    }
    contract, skipped = await _locked_contract(db, target)
    if contract is None:
        result["skipped"] = skipped
        return result
    if (contract.candidate_email or "").strip():
        result["skipped"] = "already_set"
        return result
    candidate = await db.get(Candidate, target.candidate_id)
    address = client_mailbox_address(
        candidate.name, candidate.lastname, ERSTE_MAILBOX_DOMAIN
    )
    if address is None:
        result["skipped"] = "name_not_ascii"
        return result
    contract.candidate_email = address
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action="updated",
            user_id=None,
            details={"candidate_email": address, "source": REPAIR_MARKER},
        )
    )
    return result


async def _fix_first_name(db: AsyncSession, target: Target) -> dict[str, Any]:
    result: dict[str, Any] = {
        "contract_id": target.contract_id,
        "step": "candidate_name",
        "skipped": None,
    }
    contract, skipped = await _locked_contract(db, target)
    if contract is None:
        result["skipped"] = skipped
        return result
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == target.candidate_id).with_for_update()
    )
    new_name = first_name_from_email(
        candidate.name, candidate.lastname, candidate.email or ""
    )
    if new_name is None:
        result["skipped"] = "no_typo_pattern"
        return result
    old_name = candidate.name
    candidate.name = new_name
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate.id,
            action="updated",
            user_id=None,
            details={
                "name": {"old": old_name, "new": new_name},
                "source": REPAIR_MARKER,
            },
        )
    )
    return result


async def run_settlement_identity_data_repair(
    db: AsyncSession,
    *,
    email_target: Target = CONTRACT_EMAIL_TARGET,
    name_target: Target = FIRST_NAME_TARGET,
    marker: str = REPAIR_MARKER,
) -> Optional[dict[str, Any]]:
    """Wykonaj obie poprawki; ``None`` = już wykonane. Wołający commituje."""

    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    if await db.get(AppSetting, marker) is not None:
        return None
    results = [
        await _fill_contract_email(db, email_target),
        await _fix_first_name(db, name_target),
    ]
    summary = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "requested": len(results),
        "fixed": sum(1 for r in results if r["skipped"] is None),
        "results": results,
    }
    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    logger.info(
        "settlement identity data repair: %s/%s", summary["fixed"], len(results)
    )
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already applied"
    skipped = [
        f"{r['contract_id']}:{r['step']}:{r['skipped']}"
        for r in summary["results"]
        if r["skipped"] is not None
    ]
    return f"fixed {summary['fixed']}/{summary['requested']}" + (
        f"; skipped {', '.join(skipped)}" if skipped else ""
    )
