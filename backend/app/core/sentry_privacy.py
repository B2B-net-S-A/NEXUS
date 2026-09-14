"""Outbound telemetry uses an allowlist: arbitrary application content is private."""

from __future__ import annotations

import re

_SAFE = re.compile(r"^[a-zA-Z0-9_./:{} -]{1,180}$")
_TAGS = {
    "operation",
    "failure_kind",
    "terminal",
    "sampling_policy",
    "integration",
    "job",
    "http.status_code",
    "http.method",
}
_TRACE = {"trace_id", "span_id", "parent_span_id", "op", "status", "origin"}
_IDS = re.compile(r"^[a-fA-F0-9-]{16,36}$")


def _scrub_stack(stack: dict) -> None:
    for frame in stack.get("frames", []):
        for key in ("vars", "pre_context", "context_line", "post_context"):
            frame.pop(key, None)


def scrub_event(event: dict, hint=None) -> dict | None:
    """Keep stack locations, SDK grouping and explicit diagnostics; omit free text."""
    tags = event.get("tags") or {}
    if (
        tags.get("sampling_policy") == "operation-in-progress"
        and tags.get("terminal") != "true"
    ):
        # Transaction timing is still useful; only intermediate errors are suppressed.
        if event.get("type") != "transaction":
            return None
    event.pop("user", None)
    event.pop("request", None)
    event.pop("extra", None)
    event.pop("logentry", None)
    if "message" in event:
        event["message"] = "Application failure (private details omitted)"
    tags = event.get("tags") or {}
    event["tags"] = {
        k: v for k, v in tags.items() if k in _TAGS and _SAFE.fullmatch(str(v))
    }
    contexts = event.get("contexts") or {}
    trace = contexts.get("trace") or {}
    correlation = contexts.get("correlation") or {}
    event["contexts"] = {
        "trace": {k: v for k, v in trace.items() if k in _TRACE},
        "correlation": {
            k: v
            for k, v in correlation.items()
            if k in {"request_id", "operation_id"} and _IDS.fullmatch(str(v))
        },
    }
    for value in (event.get("exception") or {}).get("values", []):
        value["value"] = str(value.get("type", "Error")) + " (private details omitted)"
        mechanism = value.get("mechanism") or {}
        value["mechanism"] = {
            k: v
            for k, v in mechanism.items()
            if k
            in {
                "type",
                "handled",
                "synthetic",
                "exception_id",
                "parent_id",
                "is_exception_group",
                "source",
            }
        }
        _scrub_stack(value.get("stacktrace") or {})
    _scrub_stack(event.get("stacktrace") or {})
    for thread in (event.get("threads") or {}).get("values", []):
        _scrub_stack(thread.get("stacktrace") or {})
    breadcrumbs = event.get("breadcrumbs") or {}
    if isinstance(breadcrumbs, dict):
        breadcrumbs["values"] = [
            {
                k: v
                for k, v in b.items()
                if k in {"timestamp", "category", "level", "type"}
            }
            for b in breadcrumbs.get("values", [])
        ]
    for span in event.get("spans", []):
        span.pop("data", None)
        span.pop("description", None)
    # URL-derived transaction names can contain capability tokens; SDK route
    # templates are retained, raw URL names are not.
    if (event.get("transaction_info") or {}).get("source") == "url":
        event["transaction"] = "unmatched-route"
    return event
