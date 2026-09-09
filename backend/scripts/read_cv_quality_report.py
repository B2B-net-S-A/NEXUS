"""Read one existing synthetic evaluation receipt. No model or write path."""

import asyncio
import base64
import json
import re
import sys

from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting

TOP_FIELDS = (
    "runtime_sha",
    "run_identity",
    "corpus_sha256",
    "prompt_sha256",
    "requested_models",
    "cases_per_model",
    "complete",
)
RESULT_FIELDS = (
    "case_id",
    "requested_model",
    "actual_models",
    "operation_id",
    "expected_supported",
    "outcome",
    "passed",
    "elapsed_ms",
    "provider_calls",
    "metering_complete",
    "input_tokens",
    "output_tokens",
    "estimated_cost_usd",
)


def project(value, identity):
    """Only diagnostic metrics; never unknown keys or model/source text."""
    if not isinstance(value, dict) or value.get("run_identity") != identity:
        raise ValueError("invalid receipt")
    output = {key: value[key] for key in TOP_FIELDS}
    output["results"] = [
        {key: row[key] for key in RESULT_FIELDS} for row in value["results"]
    ]

    # Metric text consists only of IDs, digests, model names and enums.
    # Guard recursively before it crosses the application boundary.
    def check(item):
        if isinstance(item, str):
            if not re.fullmatch(r"[A-Za-z0-9_.:/+\-]{1,150}", item):
                raise ValueError("invalid metric")
        elif isinstance(item, dict):
            for child in item.values():
                check(child)
        elif isinstance(item, list):
            for child in item:
                check(child)
        elif item is not None and not isinstance(item, (bool, int)):
            raise ValueError("invalid metric type")

    check(output)
    output["replayed_receipt"] = True
    return output


async def read_receipt(identity, session_factory=AsyncSessionLocal):
    if not re.fullmatch(r"[1-9][0-9]{0,19}-[1-9][0-9]{0,2}", identity):
        raise ValueError("invalid identity")
    async with session_factory() as db:
        row = await db.get(AppSetting, "cv_quality_eval:" + identity)
        if row is None:
            return {"complete": False, "stop_reason": "receipt_missing", "results": []}
        return project(row.value, identity)


def main():
    try:
        value = asyncio.run(read_receipt(sys.argv[1]))
    except (ValueError, KeyError, TypeError, IndexError):
        value = {"complete": False, "stop_reason": "receipt_invalid", "results": []}
    except Exception:  # no exception details or credentials in remote task logs
        value = {"complete": False, "stop_reason": "receipt_read_failed", "results": []}
    rc = (
        0
        if value.get("complete")
        and all(row["passed"] and row["metering_complete"] for row in value["results"])
        else 2
    )
    print("===NEXUS-CV-QUALITY-PAYLOAD-BEGIN===")
    print(base64.b64encode(json.dumps(value).encode()).decode())
    print("===NEXUS-CV-QUALITY-PAYLOAD-END===")
    print(f"CV_QUALITY_EXIT={rc}")
    print("===NEXUS-CV-QUALITY-END===")
    # Always deliver diagnostic payload; caller checks the explicit verdict.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
