"""Read approved-version evidence without model calls or historical fallback."""

import hashlib

from app.models.cv_version_map import CvVersionMap
from app.services.cv_editor_review import editor_claims, EditorReviewInputError
from app.services.cv_generator_b2b.requirement_map import validated_cached_items


async def approved_map_view(db, version):
    job = await db.get(CvVersionMap, version.id)
    if job is None:
        return "not_requested", []
    digest = hashlib.sha256(version.content_html.encode()).hexdigest()
    if job.content_sha256 != version.content_sha256 or digest != version.content_sha256:
        return "unavailable", []
    if job.status != "complete":
        status = (
            job.status
            if job.status in {"queued", "running", "failed", "interrupted"}
            else "unavailable"
        )
        return status, []
    result = job.result
    if (
        not isinstance(result, dict)
        or result.get("snapshot_sha256") != job.input_sha256
        or result.get("content_sha256") != digest
    ):
        return "unavailable", []
    try:
        paragraphs = editor_claims(version.content_html)
    except EditorReviewInputError:
        return "unavailable", []
    return "complete", validated_cached_items(
        {"language": version.language, "why_points": paragraphs}, result
    )
