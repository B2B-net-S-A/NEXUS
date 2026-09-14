"""Production Sentry digest to Teams Workflows. No private issue titles in output."""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SENTRY_HOST = os.environ.get('SENTRY_HOST', 'b2bnet-sa.sentry.io')
SENTRY_ORG = os.environ.get('SENTRY_ORG', 'b2bnet-sa')
SENTRY_PROJECTS = [p.strip() for p in os.environ.get('SENTRY_PROJECTS', 'nexus-be,nexus-fe').split(',') if p.strip()]
SAFE_ID = re.compile(r'^[A-Za-z0-9_.:-]{1,80}$')


def safe(value, fallback='unknown'):
    value = str(value or '')
    return value if SAFE_ID.fullmatch(value) else fallback


def fetch_issues(token: str, project: str, query: str = 'is:unresolved', sort: str = 'freq') -> list[dict]:
    params = {'query': query, 'environment': 'production', 'statsPeriod': '24h', 'sort': sort, 'limit': '100'}
    base = f'https://{SENTRY_HOST}/api/0/projects/{SENTRY_ORG}/{project}/issues/'
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
        f'https://{SENTRY_HOST}/api/0/issues/{issue_id}/events/latest/?environment=production',
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
    # stats[24h] is explicitly windowed; lifetime count is never labelled 24h.
    points = (issue.get('stats') or {}).get('24h')
    count = sum(p[1] for p in points) if isinstance(points, list) else 'unavailable'
    owner = issue.get('assignedTo') or {}
    owner_label = ('Artur' if owner.get('email') == 'artur.twardowski@b2bnetwork.pl' else 'assignee:' + safe(owner.get('id'))) if owner else 'ARTUR: unassigned'
    status = safe(issue.get('status'))
    release = issue.get('lastRelease') or {}
    if isinstance(release, dict):
        release = release.get('version')
    last_seen = safe(issue.get('lastSeen'))
    short_id = safe(issue.get('shortId'), issue_id)
    return (f'[{short_id}](https://{SENTRY_HOST}/issues/{issue_id}/) — {status}; '
            f'events/24h: {count}; {owner_label}; release: {safe(release)}; last seen: {last_seen}. '
            f'operation: {safe(issue.get("operation"))}; terminal: {safe(issue.get("terminal"))}; cause: {safe(issue.get("failureKind"))}. PR: see linked issue activity.')


def project_section(token: str, project: str, *, redact: bool = True) -> str:
    rows = fetch_issues(token, project)
    new_ids = {str(i['id']) for i in fetch_issues(token, project, 'is:unresolved age:-24h', 'new')}
    lines = [f'**{safe(project)} — production, 24h ({len(rows)} issues)**']
    for issue in rows:
        prefix = 'NEW: ' if str(issue['id']) in new_ids else ''
        lines.append(prefix + format_issue_line(enrich_issue(token, issue)))
    if not rows:
        lines.append('No unresolved issues returned. This alone does not prove healthy ingestion.')
    return '\n\n'.join(lines)


def build_message(token: str, *, redact: bool = True) -> str:
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    return '\n\n'.join([f'**NEXUS Sentry — {now}**', 'Triage: artur.twardowski@b2bnetwork.pl', *[project_section(token, p) for p in SENTRY_PROJECTS]])


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
        message = build_message(token)
    except Exception as exc:
        print(f'ERROR: incomplete Sentry read ({type(exc).__name__})', file=sys.stderr)
        return 1
    if dry_run:
        print(message)
        return 0
    try:
        post_to_teams(webhook, message)
    except Exception as exc:
        print(f'ERROR: Teams delivery failed ({type(exc).__name__})', file=sys.stderr)
        return 2
    print(f'Teams accepted digest for {len(SENTRY_PROJECTS)} projects; initial setup requires channel receipt verification.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
