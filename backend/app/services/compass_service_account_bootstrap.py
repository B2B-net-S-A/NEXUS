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
"""

import hashlib
import logging

from sqlalchemy import select
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
    jeden z ``"created"`` / ``"exists"`` / ``"malformed_key"`` / ``"error: …"``.
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
            return "exists"

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
        await db.commit()
        logger.info("compass_bootstrap: klucz konta serwisowego założony (%s)", key_id)
        return "created"
    except Exception as exc:  # noqa: BLE001 — provisioning nie może ubić startu
        await db.rollback()
        logger.warning("compass_bootstrap: provisioning nieudany: %s", exc)
        return f"error: {type(exc).__name__}"


__all__ = ["ensure_bootstrap_service_account"]
