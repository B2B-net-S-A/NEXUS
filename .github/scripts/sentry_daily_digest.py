"""Production Sentry digest to Teams Workflows. No private issue titles in output."""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SENTRY_HOST = os.environ.get('SENTRY_HOST', 'b2bnet-sa.sentry.io')
SENTRY_ORG = os.environ.get('SENTRY_ORG', 'b2bnet-sa')
SENTRY_PROJECTS = [p.strip() for p in os.environ.get('SENTRY_PROJECTS', 'nexus-be,nexus-fe').split(',') if p.strip()]
SAFE_ID = re.compile(r'^[A-Za-z0-9_.:-]{1,80}$')


def safe(value, fallback='unknown'):
    value = str(value or '')
    return value if SAFE_ID.fullmatch(value) else fallback


def fetch_issues(token: str, project: str, query: str = 'is:unresolved', sort: str = 'freq', *, start: str | None = None, end: str | None = None) -> list[dict]:
    params = {'query': query, 'environment': 'production', 'project': project, 'groupStatsPeriod': 'auto', 'sort': sort, 'limit': '100'}
    params.update({'start': start, 'end': end} if start and end else {'statsPeriod': '24h'})
    base = f'https://{SENTRY_HOST}/api/0/organizations/{SENTRY_ORG}/issues/'
    result, cursors = {}, set()
    for _ in range(100):
        req = urllib.request.Request(base + '?' + urllib.parse.urlencode(params), headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=20) as response:
            rows = json.loads(response.read())
            links = response.headers.get('Link', '')
        if not isinstance(rows, list):
            raise ValueError('Invalid Sentry response')
        for issue in rows:
            result[str(issue['id'])] = issue
        next_link = next((part for part in links.split(',') if 'rel="next"' in part and 'results="true"' in part), None)
        if not next_link:
            return list(result.values())
        cursor = re.search(r'cursor="([^"]+)"', next_link)
        if not cursor or cursor[1] in cursors:
            raise ValueError('Invalid pagination cursor')
        cursors.add(cursor[1])
        params['cursor'] = cursor[1]
    raise ValueError('Pagination limit exceeded; report incomplete')


def enrich_issue(token: str, issue: dict) -> dict:
    issue_id = str(issue['id'])
    if not issue_id.isdigit():
        raise ValueError('Invalid issue identifier')
    request = urllib.request.Request(
        f'https://{SENTRY_HOST}/api/0/organizations/{SENTRY_ORG}/issues/{issue_id}/events/latest/?environment=production',
        headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        event = json.loads(response.read())
    tags = {tag.get('key'): tag.get('value') for tag in event.get('tags', [])}
    issue = dict(issue)
    issue['operation'] = tags.get('operation')
    issue['terminal'] = tags.get('terminal')
    issue['failureKind'] = tags.get('failure_kind')
    release = event.get('release') or {}
    issue['lastRelease'] = release if isinstance(release, dict) else {'version': release}
    return issue


def format_issue_line(issue: dict, *, redact: bool = True) -> str:
    issue_id = str(issue.get('id', ''))
    if not issue_id.isdigit():
        raise ValueError('Invalid issue identifier')
    # Only explicitly filtered counts describe this production query window.
    # Never substitute the issue's lifetime count or a sliding 24h timeline.
    count = (issue.get('filtered') or {}).get('count', 'unavailable')
    owner = issue.get('assignedTo') or {}
    owner_label = ('Artur' if owner.get('email') == 'artur.twardowski@b2bnetwork.pl' else 'assignee:' + safe(owner.get('id'))) if owner else 'ARTUR: unassigned'
    status = safe(issue.get('status'))
    release = issue.get('lastRelease') or {}
    if isinstance(release, dict):
        release = release.get('version')
    last_seen = safe(issue.get('lastSeen'))
    short_id = safe(issue.get('shortId'), issue_id)
    operation = str(issue.get('operation') or '')
    operation = operation if re.fullmatch(r'[A-Z]+ /[a-z0-9_/:{}-]{0,150}|[a-z][a-z0-9_.-]{0,80}', operation) else 'unknown'
    verdict = ISSUE_VERDICTS.get(issue_id, {})
    pr = verdict.get('pr')
    pr_label = f'[#{pr}](https://github.com/B2B-net-S-A/NEXUS/pull/{pr})' if isinstance(pr, int) else 'not linked'
    return (f'[{short_id}](https://{SENTRY_HOST}/issues/{issue_id}/) — {status}; '
            f'Sentry events/window: {count}; {owner_label}; release: {safe(release)}; last seen: {last_seen}. '
            f'operation: {operation}; terminal: {safe(issue.get("terminal"))}; cause: {safe(issue.get("failureKind"))}. PR: {pr_label}; verdict: {safe(verdict.get("verdict"))}.')


# Curated delivery links contain no raw exception titles or user comments.
ISSUE_VERDICTS = json.loads((Path(__file__).parents[2] / 'docs/sentry-issue-verdicts.json').read_text())


def project_section(token: str, project: str, *, redact: bool = True, start: str | None = None, end: str | None = None) -> tuple[str, bool]:
    try:
        rows = fetch_issues(token, project, start=start, end=end)
        lines = [f'**{safe(project)} — production ({len(rows)} issues)**']
        for issue in rows:
            first_seen = issue.get('firstSeen') or ''
            prefix = 'NEW: ' if start and start <= first_seen <= (end or '') else ''
            if issue.get('substatus') == 'regressed':
                prefix += 'REGRESSION: '
            lines.append(prefix + format_issue_line(enrich_issue(token, issue)))
        if not rows:
            lines.append('No unresolved issues returned. This alone does not prove healthy ingestion.')
        return '\n\n'.join(lines), True
    except Exception as exc:
        # No raw error response, title, URL or token in Teams or public Actions logs.
        return f'**{safe(project)} — MONITORING READ FAILED ({type(exc).__name__})**', False


def build_message(token: str, *, redact: bool = True) -> tuple[str, bool]:
    end_time = datetime.now(timezone.utc).replace(microsecond=0)
    start = (end_time - timedelta(hours=24)).isoformat()
    end = end_time.isoformat()
    sections = [project_section(token, p, start=start, end=end) for p in SENTRY_PROJECTS]
    complete = all(ok for _, ok in sections)
    header = '**NEXUS Sentry**' if complete else '**NEXUS Sentry — INCOMPLETE MONITORING**'
    return '\n\n'.join([header, f'UTC window: {start} to {end}', 'Triage: artur.twardowski@b2bnetwork.pl', *[text for text, _ in sections]]), complete


def post_to_teams(webhook: str, message: str) -> None:
    # Keep each Adaptive Card bounded, without truncating the report silently.
    chunks, current = [], ''
    for paragraph in message.split('\n\n'):
        if len((current + paragraph).encode()) > 16000:
            chunks.append(current)
            current = ''
        current += paragraph + '\n\n'
    if current:
        chunks.append(current)
    for chunk in chunks:
        card = {'type': 'message', 'attachments': [{'contentType': 'application/vnd.microsoft.card.adaptive', 'content': {'type': 'AdaptiveCard', 'version': '1.2', 'body': [{'type': 'TextBlock', 'text': chunk, 'wrap': True}]}}]}
        req = urllib.request.Request(webhook, data=json.dumps(card).encode(), headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=20) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError('Teams rejected the report')


def main() -> int:
    token = os.environ.get('SENTRY_READ_TOKEN', '')
    webhook = os.environ.get('TEAMS_SENTRY_WEBHOOK_URL', '')
    dry_run = os.environ.get('DRY_RUN', '').lower() in ('1', 'true')
    if not token or (not webhook and not dry_run):
        print('ERROR: required Sentry read token or Teams receiver missing', file=sys.stderr)
        return 1
    try:
        message, complete = build_message(token)
    except Exception as exc:
        print(f'ERROR: incomplete Sentry read ({type(exc).__name__})', file=sys.stderr)
        return 1
    if dry_run:
        print(message)
        return 0 if complete else 1
    try:
        post_to_teams(webhook, message)
    except Exception as exc:
        print(f'ERROR: Teams delivery failed ({type(exc).__name__})', file=sys.stderr)
        return 2
    print(f'Teams accepted digest for {len(SENTRY_PROJECTS)} projects; initial setup requires channel receipt verification.')
    return 0 if complete else 1


if __name__ == '__main__':
    sys.exit(main())
