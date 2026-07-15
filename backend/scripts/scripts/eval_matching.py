"""DEPRECATED shim — the canonical evaluator is ``scripts/eval_matching.py``.

This stale duplicate (one directory too deep) predated the fixed evaluator and
drifted out of sync. It now delegates to the real module so any lingering
``python -m scripts.scripts.eval_matching`` invocation keeps working while
emitting a clear warning. Do not add logic here.
"""

from __future__ import annotations

import sys
import warnings

warnings.warn(
    "scripts.scripts.eval_matching is deprecated; use scripts.eval_matching "
    "(python -m scripts.eval_matching).",
    DeprecationWarning,
    stacklevel=2,
)

from scripts.eval_matching import main  # noqa: E402,F401

if __name__ == "__main__":
    sys.exit(main())
