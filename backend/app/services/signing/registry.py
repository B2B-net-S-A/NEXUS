"""Resolve a :class:`SignatureProvider` by name.

Providers are stateless — construct one per request. ``get_provider`` is the
single place that maps the ``document_signatures.provider`` discriminator (and
``settings.SIGNING_PROVIDER`` default) onto a concrete implementation.
"""

from __future__ import annotations

from app.services.signing.autenti_provider import AutentiProvider
from app.services.signing.mszafir_provider import MszafirOneShotProvider
from app.services.signing.provider import SignatureProvider, SigningProviderError
from app.services.signing.szafir_sdk_provider import SzafirSdkProvider
from app.services.signing.upload_validate_provider import UploadValidateProvider

_PROVIDERS = {
    "szafir_sdk": SzafirSdkProvider,
    "mszafir_oneshot": MszafirOneShotProvider,
    "upload_validate": UploadValidateProvider,
    "autenti": AutentiProvider,
}


def get_provider(name: str) -> SignatureProvider:
    """Return a provider instance for ``name`` (raises on unknown)."""
    key = (name or "").strip()
    factory = _PROVIDERS.get(key)
    if factory is None:
        raise SigningProviderError(
            f"unknown signing provider {name!r} (expected one of {sorted(_PROVIDERS)})"
        )
    return factory()


def known_providers() -> list[str]:
    return sorted(_PROVIDERS)
