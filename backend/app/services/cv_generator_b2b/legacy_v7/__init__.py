"""CV generation exactly as it ran at 2bc6b14f (prompt v7), on live infrastructure.

Between 09-08 and 09-10 the generator was rebuilt (#1444 and follow-ups): a
separate AI extraction of "source facts", an editorial call that never sees the
raw CV, a new English system prompt, AI rewrites of long bullets, technology
bolding in every mode and a final AI factual review. Users reported different
CVs, so generation runs the pre-rebuild flow by default. The rebuilt pipeline
stays in the code and is selected with ``CV_GENERATION_PIPELINE=v10``.

This module must stay import-light: ``standalone_service`` reads the flag, and
the pipeline itself imports ``standalone_service``.
"""

from __future__ import annotations

import os

_REBUILT_PIPELINE_VALUES = {"v10", "source_facts", "new", "current"}


def legacy_pipeline_enabled() -> bool:
    """Default ON. ``CV_GENERATION_PIPELINE=v10`` selects the rebuilt pipeline."""

    value = os.getenv("CV_GENERATION_PIPELINE", "legacy").strip().lower()
    return value not in _REBUILT_PIPELINE_VALUES
