"""CV Generator B2B — 1:1 port of artur-t-96/CV-Generator.

Standalone CV generation module that produces B2B Network-branded DOCX CVs
using Claude Sonnet 4 for content extraction and python-docx for rendering.

Public entrypoint: :func:`standalone_service.generate_cv_for_candidate`.
"""

from app.services.cv_generator_b2b.standalone_service import (
    StandaloneGenerationError,
    generate_cv_for_candidate,
)

__all__ = ["generate_cv_for_candidate", "StandaloneGenerationError"]
