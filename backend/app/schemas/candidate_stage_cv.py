"""Pydantic schemas dla CV per rekrutacja.

Mirror `app/schemas/contract.py` (Contract Draft):

* `CVOriginalSnapshotResponse`     — GET /cv/original
* `CVBrandedResponse`              — GET /cv/branded (mirror ContractDraftResponse)
* `CVBrandedUpdate`                — PATCH /cv/branded (XOR: content_html | template+language)
* `CVBrandedFinalizeResponse`      — POST /cv/branded/finalize
* `CVShareTokenResponse`           — POST /cv/share-token
* `PublicCVView`                   — GET /api/public/cv/{token} (no PII)
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

BrandedStatusLiteral = Literal["none", "draft", "finalized"]
TemplateLiteral = Literal["standard", "blind"]
LanguageLiteral = Literal["pl", "en"]


class CVOriginalSnapshotResponse(BaseModel):
    candidate_stage_id: int
    candidate_id: int
    job_id: int
    has_snapshot: bool
    original_cv_filename: Optional[str] = None
    original_cv_language: Optional[str] = None
    original_snapshot_at: Optional[datetime] = None
    original_snapshot_source: Optional[str] = None
    download_url: Optional[str] = None


class CVBrandedResponse(BaseModel):
    candidate_stage_id: int
    status: BrandedStatusLiteral
    content_html: Optional[str] = None
    template: Optional[str] = None
    language: Optional[str] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[int] = None
    updated_by_name: Optional[str] = None
    finalized_at: Optional[datetime] = None
    finalized_by: Optional[int] = None
    finalized_by_name: Optional[str] = None
    snapshot_filename: Optional[str] = None
    rendered_from_default: bool = False


class CVBrandedUpdate(BaseModel):
    """PATCH body — exactly one of {content_html} or {template+language} must be set.

    * `content_html` → save edited Tiptap HTML.
    * `template` and/or `language` → re-render via `_generate_cv_html()` and
       overwrite `branded_draft_html` (UI confirms with user before swap).
    """

    content_html: Optional[str] = None
    template: Optional[TemplateLiteral] = None
    language: Optional[LanguageLiteral] = None

    @model_validator(mode="after")
    def _exclusive_branches(self) -> "CVBrandedUpdate":
        save_branch = self.content_html is not None
        rerender_branch = self.template is not None or self.language is not None
        if save_branch == rerender_branch:
            # Both set OR neither set — invalid.
            raise ValueError(
                "Provide exactly one of: 'content_html' (save) or 'template'/'language' (re-render)."
            )
        return self


class CVBrandedFinalizeResponse(BaseModel):
    candidate_stage_id: int
    status: BrandedStatusLiteral
    snapshot_filename: str
    snapshot_size_bytes: int


class CVShareTokenResponse(BaseModel):
    token: str
    expires_at: Optional[datetime] = None
    share_url_suffix: str = Field(
        ..., description="np. '/cv/abc123' — FE skleja z window.location.origin"
    )
    candidate_stage_cv_id: int


class PublicCVView(BaseModel):
    """Public view brandowanego CV — TYLKO non-PII fields.

    Test `test_public_cv_no_pii_leakage` asercją sprawdza, że response NIE
    zawiera `email`, `phone`, `lastname`, `last_name`. Trzymaj się tej zasady.
    """

    candidate_first_name: Optional[str] = None
    job_title: Optional[str] = None
    cv_html: str
    expires_at: Optional[datetime] = None
