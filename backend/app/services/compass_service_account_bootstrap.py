"""Provisioning klucza konta serwisowego dla integracji z COMPASSEM (Etap 2).

PO CO TO ISTNIEJE
-----------------
Kierunek Compass→NEXUS (pobranie kontraktorów) uwierzytelnia się kluczem konta
serwisowego (`X-API-Key`, scope `contractors:read`). Normalnie taki klucz wydaje
admin przez Ustawienia → Konta serwisowe. Gdy to UI jest niedostępne, a
integrację trzeba uruchomić kanałem CI/env, ten bootstrap zakłada konto i klucz
ze startu aplikacji — bramkowany zmienną `COMPASS_INTEGRATION_BOOTSTRAP_KEY`.

DLACZEGO WARTOŚĆ PODAJE OPERATOR, A NIE GENERUJEMY JEJ SAMI
----------------------------------------------------------
`generate_api_key()` zwraca sekret RAZ i nigdzie go nie utrwala — a przy
aktywacji przez env nie ma jak odczytać go z kontenera (brak dostępu do logów
i bazy). Dlatego operator PODAJE gotowy klucz na drucie, a my zapisujemy jego
skrót. Ten sam string ustawia po stronie Compassa `NEXUS_CONTRACTORS_API_KEY`,
więc obie strony trzymają identyczną wartość bez przekazywania jej przez log.

CZTERY WŁASNOŚCI, KTÓRE TRZYMAJĄ TO BEZPIECZNYM
----------------------------------------------
1. **Bramka na env.** Pusty `COMPASS_INTEGRATION_BOOTSTRAP_KEY` = pełny no-op.
   Po aktywacji zmienną się czyści — klucz żyje dalej w bazie (rewokowalny,
   audytowalny), a mechanizm zostaje bezczynny.
2. **Idempotentny.** Klucz identyfikuje `key_id` (jawny prefiks wartości).
   Jeśli wiersz o tym `key_id` już jest — no-op. Ponowny start nie duplikuje.
3. **Wąski scope.** Konto dostaje WYŁĄCZNIE `contractors:read` — ten sam
   scope, którego pilnują testy kontraktowe (`test_no_candidate_data_scope_exists`,
   `test_key_cannot_reach_domain_data`).
4. **Nie wywraca startu.** Zły format klucza albo błąd bazy → log + no-op,
   nigdy wyjątek z lifespanu. Sekret nie trafia do logu.
5. **Klucz raz wydany nie wraca po usunięciu** (runda 9, R9-N9-2). Do tej
   rundy skasowanie konta (albo samego wiersza klucza) kasowało też ślad
   idempotencji, więc następny start z tą samą — być może wyciekłą — wartością
   w env zakładał konto i klucz od nowa. Każdy `key_id` założony tym
   mechanizmem (i każdy klucz kasowany razem z kontem) trafia do nagrobka
   ``app_settings['service_account_retired_key_ids']``; bootstrap nie zakłada
   ponownie klucza z nagrobka, dopóki wiersza klucza nie ma. `key_id` to jawny
   prefiks wartości — sekretu nie zapisujemy.
"""

import hashlib
import json
import logging
from collections.abc import Iterable

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.service_account import (
    ServiceAccount,
    ServiceAccountKey,
    ServiceScope,
)
from app.services.service_account_auth import (
    ServiceKeyError,
    default_expires_at,
    parse_api_key,
)

logger = logging.getLogger(__name__)

_ACCOUNT_SLUG = "compass-integration"
_ACCOUNT_NAME = "Compass contractor sync"
_KEY_LABEL = "compass-integration-bootstrap"
_SCOPE = ServiceScope.contractors_read.value

# Runda 9 (R9-N9-2): nagrobek key_id kluczy, które kiedykolwiek istniały.
RETIRED_KEYS_SETTING = "service_account_retired_key_ids"

_RETIRE_UPSERT = text(
    """
    INSERT INTO app_settings (key, value, updated_at)
    VALUES (:key, CAST(:patch AS jsonb), NOW())
    ON CONFLICT (key) DO UPDATE SET
        value = app_settings.value || EXCLUDED.value,
        updated_at = NOW()
    """
)


async def retire_key_ids(db: AsyncSession, key_ids: Iterable[str]) -> None:
    """Zapisz ``key_id`` do nagrobka (scalenie JSONB, idempotentne).

    Nie commituje — wołający zapisuje razem ze swoją operacją.
    """
    patch = {str(k): True for k in key_ids if k}
    if not patch:
        return
    await db.execute(
        _RETIRE_UPSERT,
        {"key": RETIRED_KEYS_SETTING, "patch": json.dumps(patch)},
    )


async def _is_retired(db: AsyncSession, key_id: str) -> bool:
    row = (
        await db.execute(
            text(
                "SELECT (value -> CAST(:key_id AS text)) IS NOT NULL "
                "FROM app_settings WHERE key = :key"
            ),
            {"key": RETIRED_KEYS_SETTING, "key_id": key_id},
        )
    ).scalar_one_or_none()
    return bool(row)


def _sha256_hex(value: str) -> str:
    """Skrót sekretu — kontrakt bazy (patrz ``service_account_auth._sha256_hex``).

    Liczony tu wprost, a nie importem prywatnej funkcji; zgodność gwarantuje
    test, który uwierzytelnia zbootstrapowany klucz przez publiczny
    ``authenticate_api_key``.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def ensure_bootstrap_service_account(db: AsyncSession) -> str | None:
    """Idempotentnie zakłada konto+klucz z ``COMPASS_INTEGRATION_BOOTSTRAP_KEY``.

    Zwraca krótki status do logu: ``None`` gdy bramka wyłączona, w innym razie
    jeden z ``"created"`` / ``"exists"`` / ``"retired"`` / ``"malformed_key"`` /
    ``"error: …"``.
    """
    raw = (settings.COMPASS_INTEGRATION_BOOTSTRAP_KEY or "").strip()
    if not raw:
        return None

    try:
        key_id, secret = parse_api_key(raw)
    except ServiceKeyError:
        # Zły format nie może wywrócić startu ani wyciec do logu treścią.
        logger.warning(
            "compass_bootstrap: COMPASS_INTEGRATION_BOOTSTRAP_KEY ma zły format — pomijam"
        )
        return "malformed_key"

    try:
        existing = await db.execute(
            select(ServiceAccountKey).where(ServiceAccountKey.key_id == key_id)
        )
        if existing.scalar_one_or_none() is not None:
            # Klucz już istnieje — nic nie robimy. To jest gwarancja
            # idempotencji przy każdym kolejnym starcie z tą samą wartością.
            # Dopisujemy go do nagrobka (klucze założone przed rundą 9), żeby
            # po skasowaniu wiersza nie wrócił z env.
            await retire_key_ids(db, [key_id])
            await db.commit()
            return "exists"

        if await _is_retired(db, key_id):
            # Klucz kiedyś istniał i został usunięty — nie odtwarzamy go.
            logger.warning(
                "compass_bootstrap: klucz %s był usunięty — nie zakładam go ponownie; "
                "wyczyść COMPASS_INTEGRATION_BOOTSTRAP_KEY albo podaj nowy klucz",
                key_id,
            )
            return "retired"

        account = (
            await db.execute(
                select(ServiceAccount).where(ServiceAccount.slug == _ACCOUNT_SLUG)
            )
        ).scalar_one_or_none()
        if account is None:
            account = ServiceAccount(
                slug=_ACCOUNT_SLUG,
                name=_ACCOUNT_NAME,
                description="Auto-provisioned via COMPASS_INTEGRATION_BOOTSTRAP_KEY.",
                scopes=[_SCOPE],
                is_active=True,
            )
            db.add(account)
            await db.flush()
        elif _SCOPE not in (account.scopes or []):
            # Konto istnieje, ale bez potrzebnego scope — dołóż go, nie zabieraj
            # niczego innego (konto mogło już mieć inne uprawnienia).
            account.scopes = [*(account.scopes or []), _SCOPE]
            await db.flush()

        db.add(
            ServiceAccountKey(
                key_id=key_id,
                service_account_id=account.id,
                secret_sha256=_sha256_hex(secret),
                label=_KEY_LABEL,
                expires_at=default_expires_at(None),
            )
        )
        await retire_key_ids(db, [key_id])
        await db.commit()
        logger.info("compass_bootstrap: klucz konta serwisowego założony (%s)", key_id)
        return "created"
    except Exception as exc:  # noqa: BLE001 — provisioning nie może ubić startu
        await db.rollback()
        logger.warning(
            "compass_bootstrap: provisioning nieudany (%s)", type(exc).__name__
        )
        return f"error: {type(exc).__name__}"


__all__ = [
    "RETIRED_KEYS_SETTING",
    "ensure_bootstrap_service_account",
    "retire_key_ids",
]
