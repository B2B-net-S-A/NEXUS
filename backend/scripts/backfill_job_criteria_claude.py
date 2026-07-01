"""Claude-driven backfill of must_skills / nice_skills for empty jobs.

When `backfill_job_criteria.py` (regex / Ollama) couldn't extract criteria,
this script falls back to Claude Haiku — cheap (~$0.001/job, ~$3 for 3.4K
jobs) and good at parsing Polish job titles + reference numbers.

Why Claude: regex misses compound expressions ("Programista Java BPM",
"Senior IT Analyst Data Hub") and domain abbreviations (PEP, ZOB, RFQ).
Haiku handles both Polish and English consistently.

Run:
    python -m scripts.backfill_job_criteria_claude --dry-run
    python -m scripts.backfill_job_criteria_claude --commit --limit 50
    python -m scripts.backfill_job_criteria_claude --commit
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import case, func, or_, select  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.client import Client  # noqa: E402

logger = logging.getLogger("backfill_job_criteria_claude")


SYSTEM_PROMPT = (
    "You are a recruiter for a Polish IT staffing agency. Extract structured "
    "skill requirements from a job title and metadata. Output ONLY valid JSON "
    "matching this schema (no preamble, no fences):\n"
    "{\n"
    '  "must_skills": [{"name": "<canonical skill or role>"}, ...],\n'
    '  "nice_skills": [{"name": "..."}, ...]\n'
    "}\n"
    "Rules:\n"
    "- Use canonical English names where possible: 'Java', 'Python', 'AWS',\n"
    "  'Manual Testing', 'Business Analysis', 'Project Management'.\n"
    "- For Polish role-only titles ('Tester manualny'), output a role token\n"
    "  ('Manual Testing') in must_skills.\n"
    "- Empty title yields empty arrays. Don't hallucinate.\n"
    "- Project codes / abbreviations (PEP4917, ZOB-2614) are NOT skills.\n"
    "- Maximum 5 must_skills, 5 nice_skills."
)


def _user_prompt(job: Job, client_name: str) -> str:
    nr = getattr(job, "reference_number", None) or ""
    return (
        f"Title: {job.title or '(brak)'}\n"
        f"Client: {client_name or '(brak)'}\n"
        f"Reference: {nr}\n"
        f"Description: {(job.description or '')[:600]}\n"
        f"Requirements: {(job.requirements or '')[:600]}"
    )


def _call_claude_sync(prompt: str, *, model: str) -> dict:
    """Sync Claude call via httpx. Wrapped in asyncio.to_thread.

    Supports both styles of credential:
      - ANTHROPIC_API_KEY=sk-ant-api03-... → x-api-key header (SDK default)
      - CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-... → Authorization: Bearer
        (Claude Code OAuth token, used when run from a developer machine
        without provisioning a separate API key on the Coolify env vault).
    """
    import httpx

    base_url = os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"
    headers: dict[str, str] = {
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if api_key and api_key.startswith("sk-ant-api"):
        headers["x-api-key"] = api_key
    elif oauth_token:
        headers["Authorization"] = f"Bearer {oauth_token}"
    elif api_key:
        # Unrecognised prefix — try Bearer (works for sk-ant-oat01).
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        raise RuntimeError(
            "Neither ANTHROPIC_API_KEY nor CLAUDE_CODE_OAUTH_TOKEN set"
        )

    payload = {
        "model": model,
        "max_tokens": 400,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(f"{base_url}/v1/messages", json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    text = ""
    for block in data.get("content") or []:
        if block.get("type") == "text":
            text += block.get("text") or ""
    text = text.strip()
    # Strip code fences if present.
    if text.startswith("```"):
        text = text.strip("`")
        # Drop leading "json\n" line if any.
        if "\n" in text:
            text = text.split("\n", 1)[1]
        text = text.strip()
    return json.loads(text)


async def _run(*, commit: bool, limit: int | None, model: str, log_every: int) -> int:
    must_len = case(
        (
            func.jsonb_typeof(Job.must_skills) == "array",
            func.jsonb_array_length(Job.must_skills),
        ),
        else_=0,
    )
    async with AsyncSessionLocal() as db:
        stmt = select(Job).where(or_(Job.must_skills.is_(None), must_len == 0))
        if limit is not None:
            stmt = stmt.limit(limit)
        jobs = (await db.execute(stmt)).scalars().all()

    total = len(jobs)
    logger.info("Found %s jobs without must_skills (commit=%s, model=%s)", total, commit, model)

    # Pre-load client names so we don't hit DB per-job.
    async with AsyncSessionLocal() as db:
        client_rows = (await db.execute(select(Client.id, Client.name))).all()
    client_name_by_id = {cid: name for cid, name in client_rows}

    updated = failed = empty = 0
    for i, job in enumerate(jobs):
        client_name = client_name_by_id.get(job.client_id, "") if job.client_id else ""
        prompt = _user_prompt(job, client_name)
        try:
            parsed = await asyncio.to_thread(_call_claude_sync, prompt, model=model)
        except Exception as e:  # noqa: BLE001
            logger.warning("job=%s LLM error: %s", job.id, e)
            failed += 1
            continue

        must = parsed.get("must_skills") or []
        nice = parsed.get("nice_skills") or []
        if not isinstance(must, list):
            must = []
        if not isinstance(nice, list):
            nice = []
        # Sanitize: keep only items with non-empty `name` string.
        must = [{"name": x["name"]} for x in must if isinstance(x, dict) and isinstance(x.get("name"), str) and x["name"].strip()][:5]
        nice = [{"name": x["name"]} for x in nice if isinstance(x, dict) and isinstance(x.get("name"), str) and x["name"].strip()][:5]
        if not must and not nice:
            empty += 1
            continue

        if commit:
            async with AsyncSessionLocal() as db:
                fresh = await db.scalar(select(Job).where(Job.id == job.id))
                if fresh is None:
                    failed += 1
                    continue
                fresh.must_skills = must
                fresh.nice_skills = nice
                fresh.criteria_generated_at = datetime.now(timezone.utc)
                await db.commit()

        updated += 1
        if (i + 1) % log_every == 0:
            logger.info(
                "[%s/%s] updated=%s empty=%s failed=%s — last: job=%s must=%s",
                i + 1,
                total,
                updated,
                empty,
                failed,
                job.id,
                [m["name"] for m in must],
            )

    logger.info(
        "DONE total=%s updated=%s empty=%s failed=%s",
        total,
        updated,
        empty,
        failed,
    )
    return 0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--commit", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--model", default="claude-sonnet-5")
    p.add_argument("--log-every", type=int, default=50)
    args = p.parse_args()
    if not args.commit and not args.dry_run:
        p.error("must pass --commit or --dry-run")
    if args.commit and args.dry_run:
        p.error("--commit and --dry-run are mutually exclusive")
    return args


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    args = _parse_args()
    return asyncio.run(
        _run(
            commit=args.commit,
            limit=args.limit,
            model=args.model,
            log_every=args.log_every,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
