"""Freeze exactly the assets selected with a generated CV, before editing it."""

import hashlib
import json
from pathlib import Path

from app.services.cv_generator_b2b.standalone_service import TEMPLATE_PATH


class CvAssetsError(ValueError):
    pass


def default_template() -> bytes:
    return Path(TEMPLATE_PATH).read_bytes()


def generated_assets(generated):
    template = default_template()
    payload = generated.render_payload
    screenshot = payload.get("consent_screenshot")
    consent = None
    if screenshot:
        key = screenshot.get("storage_key") if isinstance(screenshot, dict) else None
        if not key:
            raise CvAssetsError(
                "Brak wskazanego załącznika zgody. Wybierz kompletne CV."
            )
        from app.services import object_storage

        try:
            consent = object_storage.download_cv(key)
        except Exception as error:
            raise CvAssetsError(
                "Nie można pobrać załącznika zgody. Wybór CV zatrzymany; ponów próbę."
            ) from error
        if not consent:
            raise CvAssetsError("Załącznik zgody jest pusty. Wybór CV zatrzymany.")
    metadata = {
        "source_generated_id": generated.id,
        "source_payload_sha256": hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        "client_id": generated.client_id,
        "client_rule_version": generated.client_rule_version,
        "template_sha256": hashlib.sha256(template).hexdigest(),
        "consent_sha256": hashlib.sha256(consent).hexdigest() if consent else None,
    }
    return template, consent, metadata
