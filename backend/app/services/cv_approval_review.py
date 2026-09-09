"""Source verification before freezing a manually edited CV artifact."""

import hashlib

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from app.models.ai_feature import AIFeatureKey
from app.services.ai_quota import ai_feature, AIQuotaExceeded
from app.services.cv_approval_provenance import approval_provenance
from app.services.cv_editor_review import (
    editor_claims,
    verify_editor_content,
    EditorReviewInputError,
    EDITOR_REVIEW_VERSION,
)
from app.services.cv_review_sources import load_review_source, ReviewSourceUnavailable
from app.services.cv_generator_b2b.provider import CVGeneratorAIError
from app.services.cv_generator_b2b.factual_verification import (
    FactualVerificationError,
    VERIFIER_VERSION,
    VERIFICATION_PROMPT,
    REVIEW_RESPONSE_SCHEMA_SHA256,
)
from app.services.cv_generator_b2b.text_extractor import (
    extract_text_from_file,
    CVTextExtractionError,
)


async def review_for_approval(db, csv, content_html: str, user_id: int) -> dict:
    provenance = approval_provenance(content_html, csv.branded_render_metadata)
    if provenance["generation_review_covers_content"]:
        return {
            "status": "verified",
            "method": "unchanged_generation",
            "html_sha256": provenance["approved_editor_html_sha256"],
        }
    generated_id = csv.generated_document_id
    if generated_id is None:
        raise HTTPException(
            409, "Wybierz wygenerowane CV z zapisanymi źródłami przed zatwierdzeniem."
        )
    try:
        editor_claims(content_html)
        source = await load_review_source(db, generated_id)
    except (EditorReviewInputError, ReviewSourceUnavailable) as exc:
        raise HTTPException(409, str(exc)) from exc
    html_sha256 = hashlib.sha256(content_html.encode()).hexdigest()
    prompt_sha256 = hashlib.sha256(VERIFICATION_PROMPT.encode()).hexdigest()
    previous = (csv.branded_render_metadata or {}).get("content_review")
    if isinstance(previous, dict) and all(
        (
            previous.get("status") == "verified",
            previous.get("method") == "edited_source_review",
            previous.get("generated_document_id") == generated_id,
            previous.get("html_sha256") == html_sha256,
            previous.get("source_snapshot_sha256") == source.snapshot_sha256,
            previous.get("verifier_version") == VERIFIER_VERSION,
            previous.get("editor_review_version") == EDITOR_REVIEW_VERSION,
            previous.get("prompt_sha256") == prompt_sha256,
            previous.get("response_schema_sha256") == REVIEW_RESPONSE_SCHEMA_SHA256,
        )
    ):
        return {**previous, "reused": True}
    try:
        async with ai_feature(db, AIFeatureKey.cv_generator, user_id=user_id):
            cv_text = await run_in_threadpool(
                extract_text_from_file, source.cv_bytes, source.cv_filename
            )
            report = await run_in_threadpool(
                verify_editor_content,
                content_html,
                cv_text=cv_text,
                screening_notes=source.screening_notes,
                identity=source.identity,
                request_id=f"cv-approval:{csv.id}:{csv.edit_revision}",
            )
    except AIQuotaExceeded as exc:
        raise HTTPException(
            503, "Kontrola CV jest niedostępna: " + (exc.reason or "limit AI")
        ) from exc
    except FactualVerificationError as exc:
        raise HTTPException(
            422,
            "Nie zatwierdzono CV: treść po edycji nie została potwierdzona w źródłach. Sprawdź dodane lub zmienione informacje.",
        ) from exc
    except CVGeneratorAIError as exc:
        raise HTTPException(
            503,
            "Kontrola zgodności CV jest chwilowo niedostępna. Nie zatwierdzono dokumentu.",
        ) from exc
    except CVTextExtractionError as exc:
        raise HTTPException(422, "Nie można odczytać źródła do kontroli CV.") from exc
    return {
        "status": "verified",
        "method": "edited_source_review",
        "generated_document_id": generated_id,
        "editor_review_version": EDITOR_REVIEW_VERSION,
        "response_schema_sha256": REVIEW_RESPONSE_SCHEMA_SHA256,
        "html_sha256": hashlib.sha256(content_html.encode()).hexdigest(),
        "source_snapshot_sha256": source.snapshot_sha256,
        "verifier_version": report["version"],
        "prompt_sha256": report["prompt_sha256"],
    }
