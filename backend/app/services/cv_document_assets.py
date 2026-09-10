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
    template = getattr(generated, "template_content", None)
    if template is None:
        template = default_template()
    payload = generated.render_payload
    expected_template = (payload.get("artifact_provenance") or {}).get(
        "template_sha256"
    )
    if expected_template and hashlib.sha256(template).hexdigest() != expected_template:
        raise CvAssetsError(
            "Szablon zmienił się od wygenerowania CV. Pobierz zapisany DOCX; "
            "otwarcie edycji wymaga oryginalnego szablonu."
        )
    screenshot = payload.get("consent_screenshot")
    consent = getattr(generated, "consent_content", None)
    if screenshot and consent is None:
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
    provenance = payload.get("artifact_provenance") or {}
    if "consent_sha256" in provenance:
        actual = hashlib.sha256(consent).hexdigest() if consent else None
        if actual != provenance["consent_sha256"]:
            raise CvAssetsError("Nie można potwierdzić oryginalnego załącznika zgody.")
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


def approved_assets(version):
    """No live-template/storage fallback for a selected immutable approval."""
    template = version.template_content
    consent = version.consent_content
    metadata = dict(version.render_metadata or {})
    if not template:
        raise CvAssetsError(
            "Ta wersja nie ma zapisanych zasobów edycji. Pobierz zatwierdzony DOCX albo wybierz pierwotną generację jako nowy szkic."
        )
    if hashlib.sha256(template).hexdigest() != metadata.get("template_sha256"):
        raise CvAssetsError("Nie można potwierdzić szablonu zatwierdzonej wersji CV.")
    digest = hashlib.sha256(consent).hexdigest() if consent else None
    if digest != metadata.get("consent_sha256"):
        raise CvAssetsError(
            "Nie można potwierdzić załącznika zgody zatwierdzonej wersji CV."
        )
    return template, consent, metadata
