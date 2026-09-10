"""Resolve upload requirements identically for generation and approval."""

import logging

from app.services.cv_generator_b2b.standalone_service import UploadGenerationInput

logger = logging.getLogger(__name__)


def upload_requirements(
    payload: UploadGenerationInput, *, strict: bool = False
) -> list[dict[str, str]]:
    """Wymagania na kafelki dla trybu upload (brak joba).

    Pierwszeństwo mają RĘCZNE pola rekrutera; gdy puste, a wgrano plik
    championa — sekcje MUST-HAVE/NICE-TO-HAVE z niego. Champion jest tu
    parsowany DRUGI raz (pierwszy — w pipeline generacji): świadomie, to tani
    regex na DOCX, a przewlekanie list przez ``GenerationResult`` wiązałoby
    kontrakt wyniku generacji z feature'em kafelków. Zwraca [] gdy brak źródeł.
    """
    from app.services.cv_generator_b2b.requirement_map import (
        parse_manual_requirements,
    )

    requirements = parse_manual_requirements(
        payload.must_requirements, payload.nice_requirements
    )
    if not requirements and payload.champion_bytes:
        try:
            from app.services.cv_generator_b2b.champion_builder import (
                parse_champion_from_docx_bytes,
            )

            champ = parse_champion_from_docx_bytes(
                payload.champion_bytes,
                payload.champion_filename or "champion.docx",
            )
            requirements = parse_manual_requirements(
                ", ".join(champ.must_have), ", ".join(champ.nice_to_have)
            )
        except Exception as err:  # noqa: BLE001 — optional generation mapping
            if strict:
                raise ValueError("Champion requirements unavailable") from err
            logger.warning("[cv_b2b] champion parse for requirements failed")
    return requirements
