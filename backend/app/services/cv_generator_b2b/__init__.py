"""CV Generator B2B — 1:1 port of artur-t-96/CV-Generator.

Standalone CV generation module that produces B2B Network-branded DOCX CVs
using Claude Sonnet 4 for content extraction and python-docx for rendering.

Two entrypoints:

  * :func:`standalone_service.generate_cv_for_candidate` — New mode (NEXUS-aware,
    pulls candidate CV + champion + notes from DB)
  * :func:`standalone_service.generate_cv_from_uploads` — Old mode (manual upload,
    1:1 with external CV-Generator)
"""

from app.services.cv_generator_b2b.standalone_service import (
    StandaloneGenerationError,
    UploadGenerationInput,
    generate_cv_for_candidate,
    generate_cv_from_uploads,
)

__all__ = [
    "StandaloneGenerationError",
    "UploadGenerationInput",
    "generate_cv_for_candidate",
    "generate_cv_from_uploads",
]
