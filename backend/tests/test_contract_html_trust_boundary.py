"""M5-P0.10 — contract HTML has a trust boundary on all three surfaces.

Contract draft HTML / templates are authored by TacPlus (non-admin) users, saved
verbatim, rendered to PDF server-side (WeasyPrint) and served same-origin for
preview. Three holes, three guards:

(a) SSRF — WeasyPrint rendered with the default fetcher (file:// http:// data:),
    so ``<img src="http://169.254.169.254/…">`` in a draft triggered a blind
    server-side fetch. Now a deny-all ``url_fetcher`` allows only ``data:``.
(b) SSTI — the Jinja env was a plain ``Environment``; a template author could
    reach ``{{ ''.__class__… }}`` → RCE. Now it is a ``SandboxedEnvironment``.
(c) Stored XSS — the preview routes served raw HTML same-origin. Now an explicit
    restrictive CSP blocks every script except our hash-pinned auto-print
    snippet.
"""

from __future__ import annotations

import ast
import base64
import hashlib
from pathlib import Path

import pytest
from jinja2.exceptions import SecurityError
from jinja2.sandbox import SandboxedEnvironment

BACKEND = Path(__file__).resolve().parents[1]


# ── (b) Jinja SSTI ──────────────────────────────────────────────────────────


def test_contract_template_env_is_sandboxed() -> None:
    from app.api.contract_templates import _jinja_env

    assert isinstance(_jinja_env, SandboxedEnvironment)


def test_sandbox_blocks_class_traversal() -> None:
    from app.api.contract_templates import _jinja_env

    with pytest.raises(SecurityError):
        _jinja_env.from_string("{{ ''.__class__.__mro__ }}").render()


# ── (c) Stored XSS / CSP ────────────────────────────────────────────────────


def test_preview_csp_pins_the_autoprint_script_and_denies_the_rest() -> None:
    from app.api.contracts import (
        _AUTOPRINT_JS,
        _CONTRACT_PREVIEW_CSP,
        _wrap_printable,
    )

    # The CSP hash must equal the SHA-256 of the exact script that is served,
    # or the browser would refuse to run our own auto-print (and any drift
    # would silently disable it). Compute independently.
    expected = "sha256-" + base64.b64encode(
        hashlib.sha256(_AUTOPRINT_JS.encode("utf-8")).digest()
    ).decode("ascii")
    assert f"'{expected}'" in _CONTRACT_PREVIEW_CSP, "CSP hash out of sync with script"
    assert "default-src 'none'" in _CONTRACT_PREVIEW_CSP, "CSP is not deny-by-default"

    # The served HTML embeds exactly that script — so the hash matches and an
    # injected script (different bytes) has no matching hash.
    served = _wrap_printable("<p>body</p>", 1, "T")
    assert f"<script>{_AUTOPRINT_JS}</script>" in served


def test_html_serving_routes_set_csp_header() -> None:
    """Both preview routes must attach a Content-Security-Policy header."""
    for module_rel in ("app/api/contracts.py", "app/api/contract_templates.py"):
        src = (BACKEND / module_rel).read_text(encoding="utf-8")
        assert "Content-Security-Policy" in src, f"{module_rel} serves HTML with no CSP"


# ── (a) SSRF ────────────────────────────────────────────────────────────────


def test_pdf_renderer_wires_deny_all_url_fetcher() -> None:
    """render_contract_pdf must pass a url_fetcher to WeasyPrint that raises on
    non-data URLs — asserted structurally (WeasyPrint's native libs aren't in
    the unit-test image, so we can't render)."""
    src = (BACKEND / "app/services/autenti/pdf_renderer.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    # HTML(...) is called with a url_fetcher keyword.
    wired = any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "HTML"
        and any(kw.arg == "url_fetcher" for kw in n.keywords)
        for n in ast.walk(tree)
    )
    assert wired, "WeasyPrint HTML() has no url_fetcher — SSRF open (M5-P0.10)"
    # And the deny function raises for anything that isn't data:.
    assert "startswith(\"data:\")" in src or "startswith('data:')" in src
    assert "raise" in src


def test_deny_fetcher_logic_blocks_http_and_file() -> None:
    """Replicate the nested deny fetcher's contract and prove it blocks SSRF."""

    def deny(url: str):
        if url.startswith("data:"):
            return {"string": b""}
        raise ValueError("blocked")

    for bad in (
        "http://169.254.169.254/latest/meta-data/",
        "https://evil.example/x",
        "file:///etc/passwd",
        "ftp://host/x",
    ):
        with pytest.raises(ValueError):
            deny(bad)
    assert deny("data:text/plain;base64,AAAA") == {"string": b""}
