"""Capability tokens in URL paths must not survive into logs.

Signature links, CV/champion/apply share links and CloudTalk webhooks carry
their secret in the URL path. The default uvicorn access log writes the full
path, so without redaction the raw token ships to Loki/Grafana and the
reverse-proxy log — meaning a log reader gains the same access the token grants.
The existing `token=value` redaction does not catch a path segment.

These are the transport half of the token-exposure work: they do not fix
plaintext-at-rest, but they close the "token in the access log" leak for every
path-borne token at once, with no schema change.
"""

from __future__ import annotations

from app.core.logging_config import redact_sensitive


def test_signature_link_token_is_masked() -> None:
    line = "GET /sign/aB3xK9mQqP7wZ2tokenvalue1234 HTTP/1.1 200"
    out = redact_sensitive(line)
    assert "aB3xK9m" not in out
    assert "[redacted-token]" in out
    # The prefix survives so the log still says which flow this was.
    assert "/sign/" in out


def test_share_link_variants_are_masked() -> None:
    for prefix in ("/cv/", "/champion-card/", "/apply/"):
        line = f"GET {prefix}Zx91aB3xK9mQp7wZ2v HTTP/1.1 200"
        out = redact_sensitive(line)
        assert "Zx91aB3xK9m" not in out, f"{prefix} token not masked"
        assert "[redacted-token]" in out


def test_webhook_token_is_masked() -> None:
    line = "POST /calls/webhook/9f8e7d6c5b4a3f2e1d0c HTTP/1.1 200"
    out = redact_sensitive(line)
    assert "9f8e7d6c5b4a3f2e1d0c" not in out
    assert "[redacted-token]" in out


def test_sign_subpaths_are_masked() -> None:
    # /sign/{token}/pdf and /sign/{token}/submit — the token is still the
    # segment right after /sign/.
    line = "GET /sign/aB3xK9mQp7wZ2vLongEnough/pdf HTTP/1.1 200"
    out = redact_sensitive(line)
    assert "aB3xK9mQp7wZ2v" not in out
    assert "/sign/" in out and "/pdf" in out


def test_ordinary_paths_are_not_touched() -> None:
    # Redaction must stay conservative: real resource ids and normal routes
    # must survive, or the access log becomes useless.
    for line in (
        "GET /api/candidates/12345 HTTP/1.1 200",
        "GET /api/jobs?page=2&page_size=100 HTTP/1.1 200",
        "GET /api/health HTTP/1.1 200",
        "POST /api/auth/login HTTP/1.1 200",
    ):
        assert redact_sensitive(line) == line, f"wrongly altered: {line}"


def test_short_segment_after_prefix_is_left_alone() -> None:
    # `/cv/list` or `/apply/new` — a short human-readable segment is not a
    # token (min length 8), so it must not be masked.
    assert redact_sensitive("GET /cv/list HTTP/1.1 200") == "GET /cv/list HTTP/1.1 200"
    assert (
        redact_sensitive("GET /apply/new HTTP/1.1 200") == "GET /apply/new HTTP/1.1 200"
    )
