"""Bootstrap klucza konta serwisowego dla COMPASSA (Etap 2).

Najważniejszy test przechodzi przez PUBLICZNE ``authenticate_api_key`` — to on
gwarantuje, że skrót policzony w bootstrapie zgadza się z tym, którego oczekuje
warstwa auth. Test na samą kolumnę ``secret_sha256`` przeszedłby nawet przy
rozjeździe algorytmu.
"""

import secrets

import pytest

from app.core.database import AsyncSessionLocal
from app.models.service_account import ServiceScope
from app.services import compass_service_account_bootstrap as boot
from app.services.service_account_auth import (
    ServiceKeyError,
    authenticate_api_key,
)


def _wire_key() -> str:
    """Klucz na drucie w formacie z ``service_account_auth`` (nxs_v2_…)."""
    return f"nxs_v2_{secrets.token_hex(12)}_{secrets.token_urlsafe(32)}"


@pytest.mark.asyncio
async def test_bootstrapped_key_authenticates_with_contractors_scope(monkeypatch):
    key = _wire_key()
    monkeypatch.setattr(
        "app.core.config.settings.COMPASS_INTEGRATION_BOOTSTRAP_KEY", key
    )
    monkeypatch.setattr(
        boot.settings, "COMPASS_INTEGRATION_BOOTSTRAP_KEY", key, raising=False
    )

    async with AsyncSessionLocal() as db:
        assert await boot.ensure_bootstrap_service_account(db) == "created"

    # Dowód end-to-end: klucz przechodzi przez tę samą ścieżkę, którą chodzi
    # produkcyjny `X-API-Key`, i niesie scope `contractors:read`.
    async with AsyncSessionLocal() as db:
        principal, _row = await authenticate_api_key(db, key)
    assert ServiceScope.contractors_read.value in principal.scopes
    assert principal.slug == "compass-integration"


@pytest.mark.asyncio
async def test_is_idempotent(monkeypatch):
    key = _wire_key()
    monkeypatch.setattr(
        boot.settings, "COMPASS_INTEGRATION_BOOTSTRAP_KEY", key, raising=False
    )

    async with AsyncSessionLocal() as db:
        assert await boot.ensure_bootstrap_service_account(db) == "created"
    async with AsyncSessionLocal() as db:
        # Drugi start z tą samą wartością nie duplikuje klucza.
        assert await boot.ensure_bootstrap_service_account(db) == "exists"


@pytest.mark.asyncio
async def test_empty_env_is_a_noop(monkeypatch):
    monkeypatch.setattr(
        boot.settings, "COMPASS_INTEGRATION_BOOTSTRAP_KEY", "", raising=False
    )
    async with AsyncSessionLocal() as db:
        assert await boot.ensure_bootstrap_service_account(db) is None


@pytest.mark.asyncio
async def test_malformed_key_does_not_crash(monkeypatch):
    monkeypatch.setattr(
        boot.settings,
        "COMPASS_INTEGRATION_BOOTSTRAP_KEY",
        "nie-jest-kluczem",
        raising=False,
    )
    async with AsyncSessionLocal() as db:
        assert await boot.ensure_bootstrap_service_account(db) == "malformed_key"


@pytest.mark.asyncio
async def test_key_from_a_different_account_is_rejected(monkeypatch):
    """Wartość, której NIE zbootstrapowaliśmy, nie uwierzytelnia się.

    Sanity: bootstrap nie otwiera drzwi dowolnemu kluczowi, tylko temu jednemu.
    """
    provisioned = _wire_key()
    monkeypatch.setattr(
        boot.settings, "COMPASS_INTEGRATION_BOOTSTRAP_KEY", provisioned, raising=False
    )
    async with AsyncSessionLocal() as db:
        await boot.ensure_bootstrap_service_account(db)

    other = _wire_key()
    async with AsyncSessionLocal() as db:
        with pytest.raises(ServiceKeyError):
            await authenticate_api_key(db, other)


@pytest.mark.asyncio
async def test_deleted_account_is_not_recreated_from_env(monkeypatch):
    """Runda 9 (R9-N9-2): usunięte konto nie wraca przy kolejnym starcie.

    Do rundy 9 skasowanie konta kasowało też ślad idempotencji (wiersz klucza),
    więc start z tą samą, być może wyciekłą, wartością w env zakładał klucz od
    nowa. Teraz ``key_id`` siedzi w nagrobku i bootstrap odmawia.
    """
    from sqlalchemy import delete, select

    from app.models.service_account import ServiceAccountKey

    key = _wire_key()
    monkeypatch.setattr(
        boot.settings, "COMPASS_INTEGRATION_BOOTSTRAP_KEY", key, raising=False
    )
    async with AsyncSessionLocal() as db:
        assert await boot.ensure_bootstrap_service_account(db) == "created"

    from app.services.service_account_auth import parse_api_key

    key_id, _secret = parse_api_key(key)
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(ServiceAccountKey).where(ServiceAccountKey.key_id == key_id)
            )
        ).scalar_one()
        # Kasujemy sam klucz (jak kaskada z DELETE konta) — konto zostaje,
        # bo dzielą je inne testy na wspólnej bazie.
        await db.execute(
            delete(ServiceAccountKey).where(ServiceAccountKey.key_id == row.key_id)
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        assert await boot.ensure_bootstrap_service_account(db) == "retired"
    async with AsyncSessionLocal() as db:
        with pytest.raises(ServiceKeyError):
            await authenticate_api_key(db, key)
        still = (
            await db.execute(
                select(ServiceAccountKey).where(ServiceAccountKey.key_id == key_id)
            )
        ).scalar_one_or_none()
        assert still is None


def test_delete_account_route_retires_its_key_ids():
    """DELETE konta dopisuje key_id kasowanych kluczy do nagrobka (R9-N9-2)."""
    import inspect

    from app.api import service_accounts

    src = inspect.getsource(service_accounts.delete_account)
    assert "retire_key_ids" in src
    assert src.index("retire_key_ids") < src.index("db.delete(account)")
