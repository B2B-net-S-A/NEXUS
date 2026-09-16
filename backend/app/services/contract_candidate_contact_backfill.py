"""Jednorazowa korekta: kontakt z generatora umów B2B na istniejące kontrakty.

Ticket „E-mail i telefon kandydata w widoku kontraktu" wymaga backfillu wg tej
samej kolejności źródeł, którą stosuje ekran. Kopiujemy tu **wyłącznie poziom
pierwszy** — dane wpisane w „Danych Partnera" generatora, czyli
``b2b_generated_contracts.render_payload->>'partner_email' | 'partner_phone'``.

Poziomu drugiego (profil kandydata) **świadomie nie materializujemy**: fallback
do profilu liczy się przy odczycie (``services/contract_candidate_contact``),
więc przepisanie go na kolumnę zamieniłoby żywe dane w kopię starzejącą się
w ciszy — i to na każdej umowie naraz.

Dopasowanie idzie **wyłącznie po ``b2b_generated_contracts.contract_id``**.
Szukanie dokumentu po ``candidate_id``/``job_id``, gdy link jest pusty, byłoby
zgadywaniem: ta sama osoba bywa u kilku klientów, a wpisanie cudzego numeru
telefonu na umowę jest gorsze niż jego brak (profil i tak pokrywa te wiersze
przy odczycie).

Wzorzec wykonania 1:1 z ``contract_hourly_rate_repair``: advisory lock na
markerze, ``lock_timeout``, marker w ``app_settings`` jako idempotencja,
paragon z samymi licznikami/ID (publiczny workflow „migration-receipts” go
drukuje) i osobny klucz szczegółów na wartości (PII).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.contract import Contract
from app.services.contract_candidate_contact import (
    EMAIL_MAX_LENGTH,
    PHONE_MAX_LENGTH,
    normalize_email,
    normalize_phone,
)

logger = logging.getLogger(__name__)

REPAIR_MARKER = "0318_contract_candidate_contact"
SOURCE = REPAIR_MARKER

_RECEIPT_SHAPED_KEY_RE = re.compile(r"\A[0-9]{4}_[a-z0-9_]+\Z")


def details_key(marker: str = REPAIR_MARKER) -> str:
    """Klucz szczegółów korekty — trzyma WARTOŚCI (e-mail, telefon).

    Paragon pod ``marker`` trafia do publicznego logu GitHub Actions przez
    workflow „migration-receipts”, więc mogą w nim być wyłącznie liczby, ID
    i kody powodów. Kontakt to dane osobowe, więc idzie pod klucz, który
    celowo NIE ma kształtu paragonu (``show_migration_receipts`` przepuszcza
    wyłącznie ``NNNN_nazwa``).
    """

    key = f"repair_details_{marker}"
    if _RECEIPT_SHAPED_KEY_RE.match(key) or len(key) > 100:
        raise ValueError(
            "Klucz szczegółów musi mieć ≤100 znaków i inny kształt niż paragon"
        )
    return key


DETAILS_KEY = details_key()

#: Kody powodów pominięcia — do paragonu, więc bez treści.
SKIP_NO_PAYLOAD = "no_render_payload"
SKIP_NO_CONTACT_IN_PAYLOAD = "no_contact_in_payload"
SKIP_ALREADY_SET = "already_set"


def _payload_contact(payload: Any) -> tuple[Optional[str], Optional[str]]:
    if not isinstance(payload, dict):
        return None, None
    email = normalize_email(payload.get("partner_email"))
    phone = normalize_phone(payload.get("partner_phone"))
    if email and len(email) > EMAIL_MAX_LENGTH:
        email = None
    if phone and len(phone) > PHONE_MAX_LENGTH:
        phone = None
    return email, phone


async def run_candidate_contact_backfill(
    db: AsyncSession,
    *,
    marker: str = REPAIR_MARKER,
    key_for_details: str = DETAILS_KEY,
    only_contract_ids: Optional[set[int]] = None,
) -> Optional[dict[str, Any]]:
    """Przepisz kontakt z generatora na umowy. ``None`` = już zrobione.

    Wołający commituje. ``only_contract_ids`` zawęża przebieg (testy na
    współdzielonej bazie).
    """

    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    # Stary kontener przy wdrożeniu trzyma blokady kontraktów; przekroczenie
    # = rollback, następny start ponawia (jak w korektach 0306, 0308 i 0309).
    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    if await db.get(AppSetting, marker) is not None:
        return None

    # Najnowszy dokument per umowa: przy kilku wygenerowanych umowach na ten sam
    # kontrakt obowiązuje ostatnia. ``ORDER BY id`` wystarcza — numeracja jest
    # rosnąca w obrębie roku, a nowszy rok ma wyższe id.
    query = (
        select(B2BGeneratedContract)
        .where(B2BGeneratedContract.contract_id.is_not(None))
        .order_by(B2BGeneratedContract.contract_id, B2BGeneratedContract.id)
    )
    if only_contract_ids is not None:
        query = query.where(
            B2BGeneratedContract.contract_id.in_(sorted(only_contract_ids))
        )
    latest_by_contract: dict[int, B2BGeneratedContract] = {}
    for row in (await db.scalars(query)).all():
        latest_by_contract[int(row.contract_id)] = row

    filled_email: list[int] = []
    filled_phone: list[int] = []
    skipped: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []

    for contract_id, generated in sorted(latest_by_contract.items()):
        contract = await db.get(Contract, contract_id)
        if contract is None:
            # FK jest RESTRICT, więc to nie powinno wystąpić — ale korekta ma
            # przejść w całości nawet na bazie, której ktoś dotknął ręcznie.
            skipped.append({"contract_id": contract_id, "reason": "contract_missing"})
            continue
        if generated.render_payload is None:
            skipped.append({"contract_id": contract_id, "reason": SKIP_NO_PAYLOAD})
            continue
        email, phone = _payload_contact(generated.render_payload)
        if not email and not phone:
            skipped.append(
                {"contract_id": contract_id, "reason": SKIP_NO_CONTACT_IN_PAYLOAD}
            )
            continue

        changed: dict[str, str] = {}
        if email and not (contract.candidate_email or "").strip():
            contract.candidate_email = email
            changed["candidate_email"] = email
            filled_email.append(contract_id)
        if phone and not (contract.candidate_phone or "").strip():
            contract.candidate_phone = phone
            changed["candidate_phone"] = phone
            filled_phone.append(contract_id)

        if not changed:
            skipped.append({"contract_id": contract_id, "reason": SKIP_ALREADY_SET})
            continue

        details.append(
            {
                "contract_id": contract_id,
                "generated_contract_id": int(generated.id),
                **changed,
            }
        )
        db.add(
            Activity(
                entity_type="contract",
                entity_id=contract_id,
                action="candidate_contact_backfilled",
                user_id=None,
                external_source=SOURCE,
                external_id=f"contact:{contract_id}",
                details={
                    "generated_contract_id": int(generated.id),
                    "fields": sorted(changed),
                },
            )
        )

    summary: dict[str, Any] = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "linked_documents_found": len(latest_by_contract),
        "contracts_email_filled": len(filled_email),
        "contracts_phone_filled": len(filled_phone),
        "email_contract_ids": filled_email,
        "phone_contract_ids": filled_phone,
        "skipped": skipped,
    }
    db.add(AppSetting(key=marker, value=summary))
    db.add(AppSetting(key=key_for_details, value={"filled": details}))
    await db.flush()
    logger.info(
        "candidate contact backfill: e-mail %s, phone %s (of %s linked documents)",
        len(filled_email),
        len(filled_phone),
        len(latest_by_contract),
    )
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    """Wyłącznie liczby i kody powodów — log kontenera idzie do Loki."""

    if summary is None:
        return "already done"
    reasons: dict[str, int] = {}
    for item in summary["skipped"]:
        reasons[item["reason"]] = reasons.get(item["reason"], 0) + 1
    tail = ", ".join(f"{name}={count}" for name, count in sorted(reasons.items()))
    return (
        f"filled e-mail on {summary['contracts_email_filled']} and phone on "
        f"{summary['contracts_phone_filled']} contracts "
        f"(of {summary['linked_documents_found']} linked documents)"
        + (f"; skipped: {tail}" if tail else "")
    )
