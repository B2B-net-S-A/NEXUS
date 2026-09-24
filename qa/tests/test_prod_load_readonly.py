"""Test obciążeniowy produkcji może tylko czytać — pilnuje tego źródło skryptu."""

import re
from pathlib import Path

SCRIPT = (Path(__file__).parents[1] / "load" / "prod-readonly.js").read_text()

# Trasy, które przy GET zapisują albo mają limit na IP (qa/README.md).
FORBIDDEN_PATHS = [
    "champion-profile",
    "order-groups",
    "saved-searches",
    "pipeline-scores",
    "/content",
    "/url",
    "ui-events",
    "/draft",
    "mark-viewed",
]


def test_script_sends_only_get_requests():
    assert not re.search(r"http\.(post|put|patch|del|request)\s*\(", SCRIPT)
    batch_methods = re.findall(r"\[\s*'([A-Z]+)'\s*,\s*API", SCRIPT)
    assert batch_methods == ["GET"]


def test_script_never_touches_routes_with_side_effects():
    for path in FORBIDDEN_PATHS:
        assert path not in SCRIPT, path


def test_script_refuses_to_run_without_explicit_confirmation():
    assert "__ENV.QA_CONFIRM !== 'nexus-prod-readonly'" in SCRIPT
    assert "abortOnFail: true" in SCRIPT
