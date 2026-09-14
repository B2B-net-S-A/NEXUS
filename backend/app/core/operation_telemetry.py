"""Content-free outcomes suitable for unsampled Loki counters and Sentry triage."""

import logging
import os
from uuid import uuid4

import sentry_sdk

logger = logging.getLogger(__name__)


def record_job_outcome(
    job: str, success: bool, *, interval_seconds: int, subject_id: int | None = None
) -> None:
    operation_id = str(uuid4())
    logger.info(
        "job_outcome",
        extra={
            "event_kind": "job_outcome",
            "subject_id": subject_id,
            "environment": os.getenv("SENTRY_ENVIRONMENT", "production"),
            "release": os.getenv("GIT_SHA", "unknown"),
            "job": job,
            "outcome": "success" if success else "failure",
            "expected_interval_seconds": interval_seconds,
            "operation_id": operation_id,
        },
    )
    if not success:
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("operation", job)
            scope.set_tag("job", job)
            scope.set_tag("terminal", "true")
            scope.set_tag("failure_kind", "job_failure")
            scope.set_tag("sampling_policy", "all-terminal-operations")
            scope.set_context("correlation", {"operation_id": operation_id})
            scope.fingerprint = ["job-terminal-failure", job]
            sentry_sdk.capture_message("Background operation failed", level="error")
