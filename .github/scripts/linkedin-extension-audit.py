"""Read configured extension flags and bounded route counts; never emit raw logs.

This diagnostic only GETs Coolify metadata. A zero count in retained container
logs does not establish absence of historical clients or authorize retirement.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re

spec = importlib.util.spec_from_file_location(
    "cv_ops", Path(__file__).with_name("cv-quality-ops.py")
)
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)

KEYS = frozenset(
    {
        "LINKEDIN_EXTENSION_IDS",
        "LINKEDIN_EXTENSION_ENABLED",
        "LINKEDIN_EXTENSION_TTL_DAYS",
        "LINKEDIN_EXTENSION_DAILY_READ_LIMIT",
    }
)
LOG_LIMIT = 10000
_TIME = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})"
)
_ACCESS = re.compile(
    r'"(?P<method>GET|POST|DELETE|PUT|PATCH|OPTIONS|HEAD) '
    r"(?P<path>/api/(?:candidates/from-linkedin|"
    r"extension/(?:[a-z0-9_$/-]|%[0-9A-Fa-f]{2}){1,160}))"
    r'(?:\?[^\s"]*)? HTTP/[0-9.]+" (?P<status>[1-5][0-9]{2})(?:\s|$)'
)


def configured_envs(envs):
    if not isinstance(envs, list) or any(not isinstance(row, dict) for row in envs):
        raise ops.OpsError("invalid_env_response")
    projected = []
    for row in envs:
        key = row.get("key")
        if key not in KEYS:
            continue
        value = row.get("value")
        item = {
            "key": key,
            "is_runtime": row.get("is_runtime") is True,
            "is_buildtime": row.get("is_buildtime") is True,
            "is_preview": row.get("is_preview") is True,
        }
        if key == "LINKEDIN_EXTENSION_IDS":
            parts = (
                [p.strip() for p in value.split(",") if p.strip()]
                if isinstance(value, str)
                else []
            )
            valid = [p for p in parts if re.fullmatch(r"[a-p]{32}", p)]
            item.update(
                {
                    "public_extension_ids": sorted(set(valid)),
                    "invalid_id_count": len(parts) - len(valid),
                    "value_is_string": isinstance(value, str),
                }
            )
        elif key == "LINKEDIN_EXTENSION_ENABLED":
            normalized = value.lower().strip() if isinstance(value, str) else None
            item["configured_enabled"] = (
                True
                if normalized in {"1", "true", "on", "yes"}
                else False
                if normalized in {"0", "false", "off", "no"}
                else None
            )
        else:
            item["configured_integer"] = (
                int(value)
                if isinstance(value, str) and re.fullmatch(r"[0-9]{1,8}", value)
                else None
            )
        projected.append(item)
    return {
        "source": "coolify_configured_envs_not_effective_runtime",
        "missing_keys": sorted(KEYS - {row["key"] for row in projected}),
        "entries": projected,
    }


def timestamp(line):
    match = _TIME.search(line)
    if match:
        try:
            return (
                datetime.fromisoformat(match.group().replace("Z", "+00:00"))
                .astimezone(timezone.utc)
                .isoformat()
            )
        except ValueError:
            pass
    return None


def access_record(line):
    """Handle production JSON or development text without exporting either."""
    start = line.find("{")
    if start >= 0:
        try:
            record = json.loads(line[start:])
        except (ValueError, TypeError):
            record = None
        if isinstance(record, dict):
            # Uvicorn emits its request as an escaped JSON message in production.
            # Count that source only: http_outcome is a second log record of the
            # same request and counting both would double the traffic.
            if record.get("name") != "uvicorn.access":
                return None
            message = record.get("message")
            return _ACCESS.search(message) if isinstance(message, str) else None
    return _ACCESS.search(line)


def project_logs(logs):
    if not isinstance(logs, str):
        raise ops.OpsError("invalid_log_response")
    lines = logs.splitlines()
    observed = []
    legacy_times = []
    legacy = Counter()
    extension = Counter()
    access_lines = 0
    for line in lines:
        at = timestamp(line)
        if at:
            observed.append(at)
        match = access_record(line)
        if not match:
            continue
        access_lines += 1
        if match["path"] == "/api/candidates/from-linkedin":
            if match["method"] == "POST":
                legacy[match["status"]] += 1
                if at:
                    legacy_times.append(at)
        else:
            extension[match["status"]] += 1
    return {
        "requested_lines": LOG_LIMIT,
        "count_source": "uvicorn_access_log_records",
        "returned_lines": len(lines),
        "retained_window_may_be_truncated": len(lines) >= LOG_LIMIT,
        "timestamped_line_count": len(observed),
        "first_observed_at_utc": min(observed, default=None),
        "last_observed_at_utc": max(observed, default=None),
        "recognized_extension_access_lines": access_lines,
        "legacy_post_count": sum(legacy.values()),
        "legacy_post_status_counts": dict(sorted(legacy.items())),
        "legacy_first_at_utc": min(legacy_times, default=None),
        "legacy_last_at_utc": max(legacy_times, default=None),
        "extension_status_counts": dict(sorted(extension.items())),
        "historical_nonuse_established": False,
    }


def main():
    api = ops.Api(os.environ)
    app = ops.checked(os.environ.get("APP_UUID"), r"[A-Za-z0-9-]{1,80}")
    envs = api.request("GET", f"/api/v1/applications/{app}/envs")
    response = api.request(
        "GET",
        f"/api/v1/applications/{app}/logs?lines={LOG_LIMIT}"
        "&service_name=backend&show_timestamps=true",
    )
    if not isinstance(response, dict):
        raise ops.OpsError("invalid_log_response")
    print(
        json.dumps(
            {
                "configuration": configured_envs(envs),
                "logs": project_logs(response.get("logs")),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except ops.OpsError as exc:
        print(json.dumps({"error": str(exc)}))
        raise SystemExit(2) from None
