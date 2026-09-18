"""Source verification before freezing a manually edited CV artifact."""

import hashlib
import json
from dataclasses import dataclass

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
from app.services.cv_review_sources import (
    load_review_source,
    ReviewSourceUnavailable,
    ReviewSourceMissing,
)
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


@dataclass(frozen=True)
class PreparedApprovalReview:
    """Captured review input; execution must never read a mutable draft again."""

    content_html: str
    cv_text: str
    screening_notes: str
    identity: str
    generated_id: int
    source_sha256: str
    request_id: str
    presentation_json: str


async def review_for_approval(db, csv, content_html: str, user_id: int) -> dict:
    prepared = await prepare_approval_review(db, csv, content_html)
    if isinstance(prepared, dict):
        return prepared
    raise HTTPException(
        409,
        {
            "code": "cv_review_required",
            "message": "Uruchom kontrolę bieżącej treści CV przed zatwierdzeniem.",
        },
    )


def review_outcome(render_metadata) -> tuple[str | None, int | None]:
    """`(status, liczba_uwag)` zapisanej kontroli treści — dla odpowiedzi API.

    Czytane z metadanych ZAPISANEJ wersji, nie z żywego szkicu: to ma opisywać
    dokument, który właśnie powstał. `None` = kontrola nie biegła.
    """
    review = (render_metadata or {}).get("content_review")
    if not isinstance(review, dict):
        return None, None
    findings = review.get("findings")
    count = findings.get("count") if isinstance(findings, dict) else None
    return review.get("status"), count


async def prepare_approval_review(
    db, csv, content_html: str
) -> dict | PreparedApprovalReview:
    from app.services.cv_editor_privacy import check_editor_privacy

    check_editor_privacy(content_html, csv.branded_render_metadata)
    from app.services.cv_editor_rules import check_editor_rules

    presentation = check_editor_rules(content_html, csv.branded_render_metadata)
    provenance = approval_provenance(content_html, csv.branded_render_metadata)
    if provenance["generation_review_covers_content"]:
        return {
            "status": "verified",
            "method": "unchanged_generation",
            "presentation_review": presentation,
            "html_sha256": provenance["approved_editor_html_sha256"],
        }
    from app.services.cv_generator_b2b.final_review import final_review_enabled
    from app.services.cv_generator_b2b.source_facts import source_evidence_enforced

    enforced = source_evidence_enforced()
    if not enforced and not final_review_enabled():
        # Both off: privacy and client structure checks above still apply, but
        # no paid AI source review runs at all. The record says so honestly —
        # it is not "verified".
        return {
            "status": "unverified",
            "method": "evidence_enforcement_off",
            "presentation_review": presentation,
            "html_sha256": provenance["approved_editor_html_sha256"],
        }

    def degraded(reason: str) -> dict:
        """Advisory mode cannot refuse an approval over a missing source.

        Enforced mode still does: there the review is the guarantee. Here it is
        an aid, and an aid that blocks the recruiter is the defect this whole
        feature was designed to avoid.
        """
        return {
            "status": "unverified",
            "method": "advisory_source_unavailable",
            "reason": reason,
            "presentation_review": presentation,
            "html_sha256": provenance["approved_editor_html_sha256"],
        }

    generated_id = csv.generated_document_id
    if generated_id is None:
        if not enforced:
            return degraded("no_generated_source")
        raise HTTPException(
            409,
            {
                "code": "cv_source_regeneration_required",
                "message": "Wybierz wygenerowane CV z zapisanymi źródłami przed zatwierdzeniem.",
            },
        )
    try:
        editor_claims(content_html)
        source = await load_review_source(db, generated_id)
    except ReviewSourceMissing as exc:
        if not enforced:
            return degraded("source_missing")
        raise HTTPException(
            409,
            {"code": "cv_source_regeneration_required", "message": str(exc)},
        ) from exc
    except (EditorReviewInputError, ReviewSourceUnavailable) as exc:
        if not enforced:
            return degraded("source_unreadable")
        raise HTTPException(409, str(exc)) from exc
    html_sha256 = hashlib.sha256(content_html.encode()).hexdigest()
    prompt_sha256 = hashlib.sha256(VERIFICATION_PROMPT.encode()).hexdigest()
    expected_receipt = {
        "method": "edited_source_review",
        "generated_document_id": generated_id,
        "html_sha256": html_sha256,
        "source_snapshot_sha256": source.snapshot_sha256,
        "verifier_version": VERIFIER_VERSION,
        "editor_review_version": EDITOR_REVIEW_VERSION,
        "prompt_sha256": prompt_sha256,
        "response_schema_sha256": REVIEW_RESPONSE_SCHEMA_SHA256,
    }

    def matches(receipt):
        # Status is checked separately: an advisory review that FOUND problems
        # is still a completed review of exactly this content ("reviewed"), and
        # re-running it would charge the same model for the same verdict.
        return (
            isinstance(receipt, dict)
            and receipt.get("status") in {"verified", "reviewed"}
            and all(
                receipt.get(key) == value for key, value in expected_receipt.items()
            )
        )

    previous = (csv.branded_render_metadata or {}).get("content_review")
    if matches(previous):
        return {**previous, "reused": True, "presentation_review": presentation}
    from sqlalchemy import select
    from app.models.cv_approval_job import CvApprovalJob
    from app.models.cv_generated_draft import CvGeneratedDraft

    owner = (
        CvApprovalJob.generated_draft_id == csv.id
        if isinstance(csv, CvGeneratedDraft)
        else CvApprovalJob.candidate_stage_cv_id == csv.id
    )
    completed = await db.scalar(
        select(CvApprovalJob.result)
        .where(
            owner,
            CvApprovalJob.expected_revision == csv.edit_revision,
            CvApprovalJob.generated_document_id == generated_id,
            CvApprovalJob.status == "verified",
            CvApprovalJob.result["html_sha256"].as_string() == html_sha256,
        )
        .order_by(CvApprovalJob.id.desc())
        .limit(1)
    )
    if matches(completed):
        return {**completed, "reused": True, "presentation_review": presentation}
    try:
        # Reading the frozen file is local preflight, not an AI operation.
        # Reject unreadable inputs before consuming the user's review allowance.
        cv_text = await run_in_threadpool(
            extract_text_from_file, source.cv_bytes, source.cv_filename
        )
    except CVTextExtractionError as exc:
        raise HTTPException(422, "Nie można odczytać źródła do kontroli CV.") from exc
    return PreparedApprovalReview(
        content_html=content_html,
        cv_text=cv_text,
        screening_notes=source.screening_notes,
        identity=source.identity,
        generated_id=generated_id,
        source_sha256=source.snapshot_sha256,
        request_id=f"cv-approval:{csv.id}:{csv.edit_revision}",
        presentation_json=json.dumps(presentation, ensure_ascii=False),
    )


async def execute_approval_review(
    db, prepared: PreparedApprovalReview, user_id: int
) -> dict:
    """Meter and verify only captured input, without an ORM draft reference."""
    from app.services.cv_generator_b2b.source_facts import source_evidence_enforced

    enforced = source_evidence_enforced()

    def receipt(status: str, **extra) -> dict:
        return {
            "status": status,
            "method": "edited_source_review",
            "presentation_review": json.loads(prepared.presentation_json),
            "generated_document_id": prepared.generated_id,
            "editor_review_version": EDITOR_REVIEW_VERSION,
            "response_schema_sha256": REVIEW_RESPONSE_SCHEMA_SHA256,
            "html_sha256": hashlib.sha256(prepared.content_html.encode()).hexdigest(),
            "source_snapshot_sha256": prepared.source_sha256,
            "verifier_version": VERIFIER_VERSION,
            "prompt_sha256": hashlib.sha256(VERIFICATION_PROMPT.encode()).hexdigest(),
            **extra,
        }

    try:
        # The reviewer is the INDEPENDENT model (`cv_factual_verification`),
        # not the generator's — and it bills its own bucket, so the cost of
        # checking an edited CV is visible next to the cost of writing one.
        async with ai_feature(
            db, AIFeatureKey.cv_factual_verification, user_id=user_id
        ):
            report = await run_in_threadpool(
                verify_editor_content,
                prepared.content_html,
                cv_text=prepared.cv_text,
                screening_notes=prepared.screening_notes,
                identity=prepared.identity,
                request_id=prepared.request_id,
            )
    except AIQuotaExceeded as exc:
        raise HTTPException(
            503, "Kontrola CV jest niedostępna: " + (exc.reason or "limit AI")
        ) from exc
    except FactualVerificationError as exc:
        if enforced:
            raise HTTPException(
                422,
                "Nie zatwierdzono CV: treść po edycji nie została potwierdzona w źródłach. Sprawdź dodane lub zmienione informacje.",
            ) from exc
        # Advisory: the review COMPLETED and found problems. That is a result,
        # not a failure — it travels with the approved version so the recruiter
        # sees what to check before sending the CV out.
        return receipt(
            "reviewed",
            findings={
                "reason": exc.reason,
                "count": len(exc.paths),
                "paths": list(exc.paths),
                "statuses": dict(exc.statuses),
            },
        )
    except CVGeneratorAIError as exc:
        if enforced:
            raise HTTPException(
                503,
                "Kontrola zgodności CV jest chwilowo niedostępna. Nie zatwierdzono dokumentu.",
            ) from exc
        return receipt("unverified", method_detail="review_unavailable")
    except CVTextExtractionError as exc:
        if enforced:
            raise HTTPException(
                422, "Nie można odczytać źródła do kontroli CV."
            ) from exc
        return receipt("unverified", method_detail="source_unreadable")
    # Values from the report itself on the success path: they are what the
    # reviewer actually ran with, not what this module assumes it ran with.
    return receipt(
        "verified",
        verifier_version=report["version"],
        prompt_sha256=report["prompt_sha256"],
        reviewer_model=report.get("model"),
    )
