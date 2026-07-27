"""CI must exercise the token paths production actually runs.

Production has `M365_TOKEN_ENCRYPTION_KEY` set. CI did not. Several code paths
branch on it — `invite_links.create_invite_link` mints a v2 hash-at-rest row
when a cipher is available and silently falls back to a legacy plaintext-PK row
when `TokenCipherNotConfigured` is raised; the M365 OAuth store encrypts or
refuses. With the key absent, CI proved the legacy branch green while prod ran
the other one, and three `test_invite_links.py` preconditions that looked up a
link by its raw secret matched zero rows without saying so.

The key is now wired into the pytest step. These two tests keep it wired:

- the static one fails if the line is deleted, renamed, or its value stops
  being a usable Fernet key — a typo would otherwise put CI straight back on
  the legacy branch, silently and greenly;
- the runtime one fails if the process running this suite has a key that the
  cipher cannot use, whatever put it there.

Both are cheap. Neither needs a database.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

CI_YML = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"

_ENV_VAR = "M365_TOKEN_ENCRYPTION_KEY"
_VALUE_RE = re.compile(rf'^\s*{_ENV_VAR}:\s*"?([A-Za-z0-9_=-]+)"?\s*$', re.M)


def _pytest_step_block() -> str:
    """The `- name: Pytest …` step of ci.yml, up to the next step at its level.

    Read structurally rather than with one big regex so that re-indenting or
    reordering the workflow cannot make this test quietly stop looking at the
    step it is supposed to be checking.
    """
    lines = CI_YML.read_text(encoding="utf-8").splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if ln.strip().startswith("- name: Pytest")),
        None,
    )
    assert start is not None, f"no '- name: Pytest' step found in {CI_YML}"

    indent = len(lines[start]) - len(lines[start].lstrip())
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if not lines[j].strip():
            continue
        cur = len(lines[j]) - len(lines[j].lstrip())
        if cur == indent and lines[j].strip().startswith("- name:"):
            end = j
            break
    return "\n".join(lines[start:end])


def test_ci_pytest_step_declares_a_usable_token_encryption_key() -> None:
    block = _pytest_step_block()
    match = _VALUE_RE.search(block)
    assert match, (
        f"the pytest step in {CI_YML} does not set {_ENV_VAR}. Without it every "
        "token path that branches on a configured cipher takes the branch "
        "production does not take, and CI goes green on code prod never runs."
    )

    value = match.group(1)
    try:
        Fernet(value.encode("utf-8"))
    except (ValueError, TypeError) as exc:  # pragma: no cover — asserted below
        pytest.fail(
            f"{_ENV_VAR} in {CI_YML} is not a usable Fernet key ({exc}). An "
            "unusable value is worse than none: TokenCipherNotConfigured is "
            "caught and swallowed, so CI silently reverts to the legacy path "
            "while looking configured."
        )


def test_configured_key_yields_a_working_cipher() -> None:
    """Whatever this process was given, the cipher must actually work with it.

    Skipped when unset so a developer can still run the suite without the
    secret; the static test above is what holds the CI contract.
    """
    from app.core.encryption import TokenCipherNotConfigured, get_token_cipher

    if not os.getenv(_ENV_VAR):
        pytest.skip(f"{_ENV_VAR} not set in this environment")

    try:
        cipher = get_token_cipher()
    except TokenCipherNotConfigured as exc:
        pytest.fail(f"{_ENV_VAR} is set but unusable: {exc}")

    assert cipher.decrypt(cipher.encrypt("round-trip")) == "round-trip"
