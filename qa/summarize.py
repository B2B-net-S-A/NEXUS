"""Publish bounded, credential-free results; missing reports stay explicit."""

import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

reports = Path("qa/reports")
reports.mkdir(parents=True, exist_ok=True)
lines = [
    "## NEXUS QA toolkit",
    "",
    f"Revision: `{os.environ.get('GIT_SHA', 'unknown')}`",
    "",
    "Target: disposable CI stack. Small synthetic dataset; this is not production capacity evidence.",
    "",
]
xml = reports / "schemathesis.xml"
if xml.exists():
    suites = ET.parse(xml).getroot().iter("testsuite")
    totals = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
    for suite in suites:
        for key in totals:
            totals[key] += int(suite.get(key, "0"))
    lines += [
        "Schemathesis: " + ", ".join(f"{key}={value}" for key, value in totals.items()),
        "",
    ]
else:
    lines += ["Schemathesis: no report — execution unverified.", ""]
summary = reports / "k6-summary.json"
if summary.exists():
    data = json.loads(summary.read_text())
    metrics = data["metrics"]
    lines += [
        f"k6 profile: **{data['profile']}**",
        "",
        "| Flow | Completed | HTTP p95 (ms) |",
        "|---|---:|---:|",
    ]
    for flow in ("recruitment", "operations", "reporting"):
        count = (
            metrics.get(f"completed_workflows{{flow:{flow}}}", {})
            .get("values", {})
            .get("count", 0)
        )
        p95 = (
            metrics.get(f"http_req_duration{{scenario:{flow}}}", {})
            .get("values", {})
            .get("p(95)")
        )
        lines.append(
            f"| {flow} | {count} | {round(p95, 1) if p95 is not None else 'missing'} |"
        )
    failed = [
        name
        for name, metric in metrics.items()
        if any(not t["ok"] for t in metric.get("thresholds", {}).values())
    ]
    lines += ["", f"Failed thresholds: {', '.join(failed) if failed else 'none'}"]
else:
    lines += ["k6: no report — execution unverified."]
text = "\n".join(lines) + "\n"
(reports / "summary.md").write_text(text)
if os.environ.get("GITHUB_STEP_SUMMARY"):
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as output:
        output.write(text)
print(text)
