"""Mapa „wymaganie → dowody z CV" dla interaktywnej wersji wygenerowanego CV.

Generowana JEDNYM dodatkowym wywołaniem Claude tuż po udanej generacji CV
(tylko mode="new" — upload nie ma joba, więc nie ma wymagań). Publiczny
endpoint ``GET /api/public/cv-i/{token}`` serwuje wyłącznie zapisany cache —
zero AI na publicznej ścieżce, koszt jest deterministyczny (1 call/generację).

Bezpieczniki:
* wejściem do modelu jest CLIENT-SAFE payload z ``public_view.build_public_payload``
  (blind już zamaskowany, bez warnings) — model nie widzi niczego, czego nie
  widzi klient;
* każdy cytat-dowód jest walidowany jako substring tekstu publicznego payloadu
  (po normalizacji whitespace + case) — parafrazy i fabrykacje są wycinane,
  a wymaganie bez ocalałego dowodu spada z "met" na "partial";
* kwota AI (``AIFeatureKey.cv_requirement_map``) działa FAIL-OPEN: przekroczenie
  limitu lub błąd LLM nie psuje generacji CV — link działa w widoku classic,
  kafelki są po prostu niedostępne.

Cache po ``input_hash`` (prompt_version + model + payload + wymagania):
ponowna finalizacja tego samego payloadu nie płaci drugi raz.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_feature import AIFeatureKey
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.job import Job
from app.services.ai_quota import AIQuotaExceeded, check_and_increment
from app.services.skill_normalize import iter_skill_names
from app.services.cv_generator_b2b.public_view import (
    build_public_payload,
    public_payload_text,
)
from app.services.llm_prompts import CV_REQUIREMENT_MAP

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("CV_REQUIREMENT_MAP_MODEL", "claude-sonnet-5")
MAX_TOKENS = int(os.environ.get("CV_REQUIREMENT_MAP_MAX_TOKENS", "4000"))

_MAX_MUST = 12
_MAX_NICE = 8
_MAX_EVIDENCE_PER_REQ = 4
_MAX_QUOTE_CHARS = 220
_MAX_NOTE_CHARS = 250
_VALID_STATUSES = {"met", "partial", "no_data"}

_WS_RE = re.compile(r"\s+")


def _normalize_for_match(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().casefold()


def build_requirements(job: Job) -> list[dict[str, str]]:
    """Lista wymagań na kafelki: ``[{"name", "kind": "must"|"nice"}]``.

    Źródło pierwsze: strukturalne ``Job.must_skills``/``nice_skills``
    (przez ``iter_skill_names`` — obsługuje wszystkie legacy kształty JSONB).
    Fallback (must_skills puste — ~88% prod jobów): regexowa ekstrakcja
    z Championa/JD, ta sama co w scoringu (implicit must).
    """
    must = iter_skill_names(job.must_skills)[:_MAX_MUST]
    nice = iter_skill_names(job.nice_skills)[:_MAX_NICE]

    if not must:
        try:
            from app.services.scoring_service import _extract_skills_from_champion

            extracted = _extract_skills_from_champion(job)
            must = [
                str(s.get("name"))
                for s in extracted
                if isinstance(s, dict) and s.get("name")
            ][:_MAX_MUST]
        except Exception as exc:  # noqa: BLE001 — fallback nie może psuć mapy
            logger.warning("[cv_req_map] champion fallback failed: %s", exc)

    seen: set[str] = set()
    requirements: list[dict[str, str]] = []
    for name, kind in [(n, "must") for n in must] + [(n, "nice") for n in nice]:
        key = _normalize_for_match(name)
        if not key or key in seen:
            continue
        seen.add(key)
        requirements.append({"name": name, "kind": kind})
    return requirements


def _input_hash(
    public_payload: dict[str, Any], requirements: list[dict[str, str]]
) -> str:
    blob = json.dumps(
        {
            "prompt_version": CV_REQUIREMENT_MAP.version,
            "model": DEFAULT_MODEL,
            "cv": public_payload,
            "requirements": requirements,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _strip_code_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def _sanitize_items(
    parsed: dict[str, Any],
    requirements: list[dict[str, str]],
    public_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Zwaliduj odpowiedź modelu przeciw wymaganiom i treści CV.

    Kontrakt anty-fabrykacyjny: cytat, którego nie ma w publicznym payloadzie
    (substring po normalizacji), jest ODRZUCANY; wymaganie ze statusem "met",
    które straciło wszystkie dowody, spada na "partial". Wpisy spoza listy
    wymagań są ignorowane; brakujące dostają "no_data".
    """
    haystack = _normalize_for_match(public_payload_text(public_payload))
    experience_count = len(public_payload.get("experience", []))
    by_key = {_normalize_for_match(r["name"]): r for r in requirements}

    raw_items = parsed.get("items")
    model_items: dict[str, dict[str, Any]] = {}
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            key = _normalize_for_match(str(item.get("requirement") or ""))
            if key in by_key and key not in model_items:
                model_items[key] = item

    sanitized: list[dict[str, Any]] = []
    for req in requirements:
        key = _normalize_for_match(req["name"])
        item = model_items.get(key)
        if item is None:
            sanitized.append(
                {
                    "requirement": req["name"],
                    "kind": req["kind"],
                    "status": "no_data",
                    "note": None,
                    "evidence": [],
                }
            )
            continue

        status = str(item.get("status") or "").strip()
        if status not in _VALID_STATUSES:
            status = "no_data"

        evidence_out: list[dict[str, Any]] = []
        for ev in item.get("evidence") or []:
            if not isinstance(ev, dict):
                continue
            quote = str(ev.get("quote") or "").strip()[:_MAX_QUOTE_CHARS]
            if not quote or _normalize_for_match(quote) not in haystack:
                continue  # parafraza/fabrykacja — odrzucamy
            idx: Optional[int] = ev.get("experience_index")
            if not isinstance(idx, int) or not (0 <= idx < experience_count):
                idx = None
            evidence_out.append({"experience_index": idx, "quote": quote})
            if len(evidence_out) >= _MAX_EVIDENCE_PER_REQ:
                break

        if status == "met" and not evidence_out:
            status = "partial"

        note = str(item.get("note") or "").strip()[:_MAX_NOTE_CHARS] or None
        sanitized.append(
            {
                "requirement": req["name"],
                "kind": req["kind"],
                "status": status,
                "note": note,
                "evidence": evidence_out,
            }
        )
    return sanitized


async def ensure_requirement_map(
    db: AsyncSession, generated_id: int, *, user_id: Optional[int]
) -> None:
    """Wygeneruj (lub potwierdź z cache) mapę wymagań dla wiersza ``generated_id``.

    Wołane na końcu background-joba generacji (mode="new"). NIGDY nie rzuca —
    każda porażka jest logowana, a CV zostaje w pełni użyteczne bez mapy.
    Committuje samodzielnie (job po ``_finalize_success`` już zrobił commit).
    """
    try:
        row = await db.get(CvGeneratedDocument, generated_id)
        if (
            row is None
            or row.mode != "new"
            or row.status != "ready"
            or not row.render_payload
            or row.job_id is None
        ):
            return
        job = await db.get(Job, row.job_id)
        if job is None:
            return

        requirements = build_requirements(job)
        if not requirements:
            logger.info(
                "[cv_req_map] no requirements for job=%s generated=%s — skipping",
                row.job_id,
                generated_id,
            )
            return

        public_payload = build_public_payload(row.render_payload)
        digest = _input_hash(public_payload, requirements)
        if row.requirement_map and row.requirement_map_input_hash == digest:
            return  # cache hit — nic do zrobienia, zero kosztu

        # Kwota AI — FAIL-OPEN: brak kwoty/feature off = brak kafelków, nie awaria.
        try:
            await check_and_increment(db, AIFeatureKey.cv_requirement_map, user_id)
            await db.commit()
        except AIQuotaExceeded as exc:
            await db.rollback()
            logger.warning(
                "[cv_req_map] quota blocked (%s) generated=%s", exc.reason, generated_id
            )
            return

        api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get(
            "CLAUDE_API_KEY"
        )
        if not api_key:
            logger.warning("[cv_req_map] no API key configured — skipping")
            return

        from app.services.claude_client import call_claude

        prompt = CV_REQUIREMENT_MAP.render(
            cv_json=json.dumps(public_payload, ensure_ascii=False),
            requirements_json=json.dumps(requirements, ensure_ascii=False),
            language_label=(
                "angielski" if public_payload["language"] == "en" else "polski"
            ),
        )
        started = time.time()
        message = await run_in_threadpool(
            call_claude,
            model=DEFAULT_MODEL,
            max_tokens=MAX_TOKENS,
            # Claude 5: adaptive thinking liczy się do max_tokens i ucina JSON.
            thinking={"type": "disabled"},
            system=CV_REQUIREMENT_MAP.system_prompt,
            messages=[{"role": "user", "content": prompt}],
            api_key=api_key,
        )
        raw = _strip_code_fences(
            "".join(
                getattr(b, "text", "") or ""
                for b in message.content
                if hasattr(b, "text")
            )
        )
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("LLM returned non-object JSON")

        items = _sanitize_items(parsed, requirements, public_payload)
        row.requirement_map = {"items": items}
        row.requirement_map_input_hash = digest
        row.requirement_map_model = DEFAULT_MODEL
        row.requirement_map_generated_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info(
            "[cv_req_map] generated=%s items=%d latency_ms=%d",
            generated_id,
            len(items),
            int((time.time() - started) * 1000),
        )
    except Exception as exc:  # noqa: BLE001 — mapa nigdy nie psuje generacji CV
        try:
            await db.rollback()
        except Exception:  # pragma: no cover — defensive
            pass
        logger.warning(
            "[cv_req_map] generation failed generated=%s: %s", generated_id, exc
        )
