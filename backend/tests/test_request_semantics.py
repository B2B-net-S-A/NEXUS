"""Exact read-only POST classification shared by RBAC and impersonation."""

from app.services.request_semantics import (
    is_read_only_http_request,
    is_read_only_post_path,
)


def test_safe_methods_are_always_read_only() -> None:
    for method in ("GET", "HEAD", "OPTIONS"):
        assert is_read_only_http_request(method, "/api/jobs/17")


def test_audited_post_templates_match_exact_dynamic_paths() -> None:
    assert is_read_only_post_path("/api/search/candidates")
    assert is_read_only_post_path("/api/talent-radar/search")
    assert is_read_only_post_path("/api/jobs/17/classify-cc")
    assert is_read_only_post_path("/api/jobs/17/generate-criteria-preview")
    assert is_read_only_post_path("/api/candidates/bulk-cv-download")


def test_sibling_mutations_never_inherit_read_semantics() -> None:
    assert not is_read_only_http_request("POST", "/api/jobs/17/cc-override")
    assert not is_read_only_http_request("POST", "/api/talent-radar/search/delete")
    assert not is_read_only_http_request("POST", "/api/candidates/bulk-import")
    assert not is_read_only_http_request("DELETE", "/api/search/candidates")
