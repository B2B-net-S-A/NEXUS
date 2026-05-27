"""Daily Sentry health digest -> Slack.

Queries Sentry REST API for top unresolved + newly-seen issues across NEXUS
projects (last 24h) and posts a summary to Slack. Designed to run under
GitHub Actions cron — stdlib only, no extra pip install needed.

Environment:
    SENTRY_AUTH_TOKEN   Personal/Internal token with `project:read` + `event:read`
    SLACK_WEBHOOK_URL   Incoming webhook for #nexus-alerts (or env override)
    SENTRY_ORG          Sentry organization slug (default: b2bnet-sa)
    SENTRY_PROJECTS     Comma-separated project slugs (default: nexus-be,nexus-fe)
    SENTRY_HOST         API host (default: sentry.io — works for b2bnet-sa.sentry.io)
    TOP_N               Issues per category (default: 5)

Exit codes:
    0   Slack notified (or DRY_RUN echoed to stdout)
    1   Sentry API failure (network / auth / 5xx)
    2   Slack delivery failure
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


SENTRY_HOST = os.environ.get("SENTRY_HOST", "sentry.io")
SENTRY_ORG = os.environ.get("SENTRY_ORG", "b2bnet-sa")
SENTRY_PROJECTS = [
    p.strip()
    for p in os.environ.get("SENTRY_PROJECTS", "nexus-be,nexus-fe").split(",")
    if p.strip()
]
TOP_N = int(os.environ.get("TOP_N", "5"))


def fetch_issues(token: str, project: str, query: str, sort: str) -> list[dict]:
    """Query Sentry issues endpoint and return parsed JSON list."""
    params = urllib.parse.urlencode(
        {
            "query": query,
            "statsPeriod": "24h",
            "sort": sort,
            "limit": str(TOP_N),
        }
    )
    url = f"https://{SENTRY_HOST}/api/0/projects/{SENTRY_ORG}/{project}/issues/?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def format_issue_line(issue: dict) -> str:
    """One-line Slack mrkdwn rendering of a Sentry issue."""
    title = issue.get("title", "<no title>")[:120]
    count = issue.get("count", "?")
    users = issue.get("userCount", "?")
    permalink = issue.get("permalink", "")
    short_id = issue.get("shortId", "")
    return f"• <{permalink}|{short_id}> — {title} (events: {count}, users: {users})"


def project_section(token: str, project: str) -> str:
    """Build the Slack block for one Sentry project."""
    try:
        unresolved = fetch_issues(
            token, project, "is:unresolved", sort="freq"
        )
        new_issues = fetch_issues(
            token, project, "is:unresolved age:-24h", sort="new"
        )
    except urllib.error.HTTPError as exc:
        return f"*{project}* — API error {exc.code}: {exc.reason}"
    except (urllib.error.URLError, TimeoutError) as exc:
        return f"*{project}* — network error: {exc}"

    lines = [f"*{project}*"]
    if unresolved:
        lines.append(f"_Top {len(unresolved)} unresolved (24h, by freq)_")
        lines.extend(format_issue_line(i) for i in unresolved)
    else:
        lines.append("_No unresolved issues in last 24h_ ✅")

    if new_issues:
        lines.append(f"_New issues last 24h_ ({len(new_issues)})")
        lines.extend(format_issue_line(i) for i in new_issues)

    return "\n".join(lines)


def build_message(token: str) -> str:
    """Assemble the full Slack message body."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sections = [project_section(token, p) for p in SENTRY_PROJECTS]
    header = f":mag: *NEXUS Sentry daily digest* — {today}"
    footer = (
        "_Runbook: docs/sentry-monitoring.md · "
        "Alert rules: docs/sentry-alerts-runbook.md_"
    )
    return "\n\n".join([header, *sections, footer])


def post_to_slack(webhook: str, text: str) -> None:
    """POST mrkdwn-formatted text to a Slack incoming webhook."""
    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"Slack returned {resp.status}")


def main() -> int:
    token = os.environ.get("SENTRY_AUTH_TOKEN", "")
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "")
    dry_run = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")

    if not token:
        print("ERROR: SENTRY_AUTH_TOKEN is not set", file=sys.stderr)
        return 1

    try:
        message = build_message(token)
    except Exception as exc:  # surface to GH Actions
        print(f"ERROR: failed to build digest: {exc}", file=sys.stderr)
        return 1

    print(message)

    if dry_run or not webhook:
        print("(dry-run / no webhook — skipping Slack POST)", file=sys.stderr)
        return 0

    try:
        post_to_slack(webhook, message)
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
        print(f"ERROR: Slack delivery failed: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
