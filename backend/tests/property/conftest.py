"""Bounded, reproducible generation in CI; shrinking/replay remain enabled."""

import os

from hypothesis import settings

settings.register_profile("nexus-ci", max_examples=100, deadline=None, derandomize=True)
if os.environ.get("CI"):
    settings.load_profile("nexus-ci")
