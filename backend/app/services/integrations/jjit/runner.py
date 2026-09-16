"""Import JJIT/RocketJobs w NEXUS — orkiestracja jednego runu.

Port ``scraper.py`` (RocketJobs) na job w tle NEXUS-a. Przepływ per aplikacja:

1. stan w bazie (``integration_external_items``): widziana → pomiń,
2. CV z panelu,
3. Traffit: szukaj po e-mailu z panelu → duplikat = nowe CV do istniejącego
   (gdy SHA inny) / nowy = ``parse_cv`` → payload → ``POST /employees/`` → CV,
4. NEXUS przez loopback: kandydat z CV → auto-match do opublikowanych
   rekrutacji (próg ``JJIT_MATCH_MIN_SCORE`` + must-have),
5. zdarzenie w ``integration_run_events`` + wiersz stanu.

``dry_run=True`` (domyślnie przez tydzień równoległej obserwacji): kroki 3–4
tylko CZYTAJĄ (wyszukanie w Traffit, parse CV), nic nie zapisują w Traffit ani
w NEXUS-ie poza raportem runu — liczby „nowi / duplikaty / błędy" są
porównywalne z runem scrapera na Macu.

Współbieżność: jeden worker uvicorna + ``_RUN_LOCK`` (asyncio) + odmowa, gdy
w bazie jest run JJIT ``running`` młodszy niż 6 h (proces zabity bez
``finish`` nie blokuje na zawsze).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import socket
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.integration_external_item import IntegrationExternalItem
from app.models.integration_run import IntegrationRun, IntegrationRunEvent
from app.services.cv_parser import parse_cv
from app.services.cv_text_extractor import extract_text
from app.services.integrations.jjit.cv_payload import (
    build_traffit_payload,
    is_valid_email,
)
from app.services.integrations.jjit.nexus_client import NexusLoopbackClient
from app.services.integrations.jjit.panel_client import (
    CvFile,
    PanelAuthError,
    PanelClient,
    application_skip_reason,
    split_name,
)
from app.services.integrations.jjit.traffit_writer import TraffitWriter

logger = logging.getLogger(__name__)

SOURCE = "jjit"
_RUN_LOCK = asyncio.Lock()
STUCK_RUN_AFTER = timedelta(hours=6)
MIN_CV_BYTES = 100
PAUSE_BETWEEN_CANDIDATES_SEC = 1.0


class RunInProgress(Exception):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _cv_text(cv: CvFile) -> str:
    suffix = os.path.splitext(cv.filename)[1] or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(cv.data)
        tmp.flush()
        return extract_text(tmp.name, cv.filename)


async def _active_run_exists(db) -> bool:
    cutoff = _utcnow() - STUCK_RUN_AFTER
    run = await db.scalar(
        select(IntegrationRun)
        .where(IntegrationRun.source == SOURCE, IntegrationRun.status == "running")
        .where(IntegrationRun.started_at >= cutoff)
        .limit(1)
    )
    return run is not None


class JjitRun:
    def __init__(
        self,
        *,
        dry_run: bool,
        since: str,
        states: list[str],
        limit: int = 0,
        mode: Optional[str] = None,
    ) -> None:
        self.dry_run = dry_run
        self.since = since
        self.states = states
        self.limit = limit
        self.mode = mode or ("dry_run" if dry_run else "import")
        self.stats = {
            "created": 0,
            "duplicates": 0,
            "cv_refreshed": 0,
            "errors": 0,
            "skipped": 0,
            "nexus_pushed": 0,
            "nexus_created": 0,
            "nexus_existing": 0,
            "nexus_jobs": 0,
            "nexus_errors": 0,
            "offers": 0,
            "applications": 0,
        }
        self.run_id: Optional[int] = None

    # ── raport runu (bezpośrednio w DB — jesteśmy w NEXUS-ie) ──────────────

    async def _start_run(self) -> None:
        async with AsyncSessionLocal() as db:
            if await _active_run_exists(db):
                raise RunInProgress("run JJIT już trwa")
            run = IntegrationRun(
                source=SOURCE,
                mode=self.mode,
                status="running",
                started_at=_utcnow(),
                host=f"nexus:{socket.gethostname()[:40]}",
                version=(os.environ.get("GIT_SHA") or "")[:12] or None,
                stats={},
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            self.run_id = run.id

    async def _finish_run(self, status: str, error: Optional[str] = None) -> None:
        async with AsyncSessionLocal() as db:
            run = await db.get(IntegrationRun, self.run_id)
            if run is None:
                return
            run.status = status
            run.stats = dict(self.stats)
            run.error = error
            run.finished_at = _utcnow()
            await db.commit()

    async def _event(self, **fields) -> None:
        async with AsyncSessionLocal() as db:
            db.add(
                IntegrationRunEvent(
                    run_id=self.run_id, source=SOURCE, occurred_at=_utcnow(), **fields
                )
            )
            await db.commit()

    async def _seen(self, external_id: str) -> Optional[IntegrationExternalItem]:
        async with AsyncSessionLocal() as db:
            item = await db.scalar(
                select(IntegrationExternalItem).where(
                    IntegrationExternalItem.source == SOURCE,
                    IntegrationExternalItem.external_id == external_id,
                )
            )
            if item is not None:
                db.expunge(item)
            return item

    async def _remember(self, external_id: str, **fields) -> None:
        if self.dry_run:
            return
        async with AsyncSessionLocal() as db:
            item = await db.scalar(
                select(IntegrationExternalItem).where(
                    IntegrationExternalItem.source == SOURCE,
                    IntegrationExternalItem.external_id == external_id,
                )
            )
            if item is None:
                item = IntegrationExternalItem(source=SOURCE, external_id=external_id)
                db.add(item)
            for key, value in fields.items():
                setattr(item, key, value)
            item.last_seen_at = _utcnow()
            await db.commit()

    # ── jedna aplikacja ────────────────────────────────────────────────────

    async def _process(
        self,
        app: dict,
        offer_title: str,
        panel: PanelClient,
        traffit: TraffitWriter,
        nexus: NexusLoopbackClient,
    ) -> None:
        aid = str(app.get("id"))
        first, last = split_name(app.get("candidateName") or "")
        email = (app.get("candidateEmail") or "").strip()
        name = f"{first} {last}".strip() or aid
        self.stats["applications"] += 1

        if application_skip_reason(app):
            self.stats["skipped"] += 1
            return
        seen = await self._seen(aid)
        if seen is not None and seen.last_action in (
            "created",
            "duplicate",
            "cv_refreshed",
        ):
            self.stats["skipped"] += 1
            return

        cv = await panel.download_cv(aid)
        if cv is None or cv.size < MIN_CV_BYTES:
            self.stats["errors"] += 1
            await self._event(
                action="error",
                external_id=aid,
                candidate_name=name,
                offer_title=offer_title,
                error="brak CV",
            )
            return
        sha = hashlib.sha256(cv.data).hexdigest()

        # ── Traffit ────────────────────────────────────────────────────
        traffit_id: Optional[int] = None
        action = "created"
        existing = (
            await traffit.search_by_email(email)
            if traffit.configured and email
            else None
        )
        if existing:
            traffit_id = int(existing.get("id")) if existing.get("id") else None
            action = "duplicate"
            if (
                not self.dry_run
                and traffit_id
                and (seen is None or seen.cv_sha256 != sha)
            ):
                try:
                    await traffit.upload_cv(traffit_id, cv.data, cv.filename, cv.mime)
                    action = "cv_refreshed"
                    self.stats["cv_refreshed"] += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning("jjit: cv refresh failed for %s: %s", traffit_id, e)
            self.stats["duplicates"] += 1
        else:
            try:
                text = await asyncio.to_thread(_cv_text, cv)
                parsed = (
                    await parse_cv(text) if text and len(text.strip()) >= 50 else {}
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("jjit: parse_cv failed for %s: %s", aid, e)
                parsed = {}
            payload = build_traffit_payload(
                parsed,
                fallback={"first_name": first, "last_name": last, "email": email},
                offer_title=offer_title,
            )
            if not is_valid_email(payload["email"]):
                self.stats["errors"] += 1
                await self._event(
                    action="error",
                    external_id=aid,
                    candidate_name=name,
                    offer_title=offer_title,
                    error="brak prawidłowego e-maila (CV/panel)",
                )
                return
            if payload["email"] != email:
                existing2 = (
                    await traffit.search_by_email(payload["email"])
                    if traffit.configured
                    else None
                )
                if existing2:
                    traffit_id = (
                        int(existing2.get("id")) if existing2.get("id") else None
                    )
                    action = "duplicate"
                    self.stats["duplicates"] += 1
            if action == "created":
                if self.dry_run or not traffit.configured:
                    self.stats["created"] += 1
                else:
                    result = await traffit.create_candidate(payload)
                    data = result["data"] if isinstance(result["data"], dict) else {}
                    traffit_id = data.get("id")
                    if not traffit_id:
                        msg = str(
                            data.get("message") or data.get("error") or result["data"]
                        )
                        if (
                            result["status"] == 409
                            or "already exists" in msg
                            or "409" in msg
                        ):
                            action = "duplicate"
                            self.stats["duplicates"] += 1
                        else:
                            self.stats["errors"] += 1
                            await self._event(
                                action="error",
                                external_id=aid,
                                candidate_name=name,
                                offer_title=offer_title,
                                error=f"Traffit: {msg[:300]}",
                            )
                            return
                    else:
                        traffit_id = int(traffit_id)
                        self.stats["created"] += 1
                        try:
                            await traffit.upload_cv(
                                traffit_id, cv.data, cv.filename, cv.mime
                            )
                        except Exception as e:  # noqa: BLE001
                            logger.warning(
                                "jjit: cv upload failed for %s: %s", traffit_id, e
                            )

        # ── NEXUS (auto-match) — tylko w prawdziwym runie ───────────────
        matched: list[dict] = []
        candidate_id: Optional[int] = None
        if not self.dry_run:
            res = await nexus.push_candidate(
                cv.data,
                cv.filename,
                cv.mime,
                candidate_name=name,
                offer_title=offer_title,
                known_cv_sha=seen.cv_sha256 if seen else None,
            )
            candidate_id = res.candidate_id
            if res.action in ("created", "existing"):
                self.stats["nexus_pushed"] += 1
                self.stats[f"nexus_{res.action}"] += 1
                self.stats["nexus_jobs"] += len(res.matched)
                matched = [
                    {"job_id": m["job_id"], "title": m["title"], "score": m["score"]}
                    for m in res.matched
                ]
            elif res.action == "error":
                self.stats["nexus_errors"] += 1
                logger.warning("jjit: nexus error for %s: %s", aid, res.error)

        await self._event(
            action=action,
            external_id=aid,
            candidate_id=candidate_id,
            traffit_id=traffit_id,
            candidate_name=name,
            offer_title=offer_title,
            matched_jobs=matched,
        )
        await self._remember(
            aid,
            candidate_id=candidate_id,
            traffit_id=traffit_id,
            cv_sha256=sha,
            offer_title=offer_title[:255],
            last_action=action,
        )

    # ── cały run ───────────────────────────────────────────────────────────

    async def execute(self) -> dict:
        if _RUN_LOCK.locked():
            raise RunInProgress("run JJIT już trwa (lock)")
        async with _RUN_LOCK:
            await self._start_run()
            email = os.environ.get("JJIT_EMAIL", "").strip()
            password = os.environ.get("JJIT_PASSWORD", "")
            if not email or not password:
                await self._finish_run(
                    "failed", "JJIT_EMAIL / JJIT_PASSWORD nie ustawione"
                )
                return dict(self.stats, run_id=self.run_id, status="failed")

            total = 0
            try:
                async with (
                    PanelClient(email, password) as panel,
                    httpx.AsyncClient(
                        timeout=httpx.Timeout(60.0, connect=10.0)
                    ) as http,
                ):
                    traffit = TraffitWriter(http)
                    nexus = NexusLoopbackClient(http)
                    await panel.login()
                    offers: list[dict] = []
                    for state in self.states:
                        offers.extend(await panel.list_job_ads(state))
                    self.stats["offers"] = len(offers)
                    logger.info(
                        "jjit run %s: %d ogłoszeń, od %s, dry_run=%s",
                        self.run_id,
                        len(offers),
                        self.since,
                        self.dry_run,
                    )

                    for offer in offers:
                        if self.limit and total >= self.limit:
                            break
                        oid, title = str(offer.get("id")), str(offer.get("title") or "")
                        try:
                            applications = await panel.list_applications(
                                oid, applied_from=self.since
                            )
                        except PanelAuthError:
                            raise
                        except Exception as e:  # noqa: BLE001
                            logger.error("jjit: ogłoszenie %s: %s", oid, e)
                            continue
                        for app in applications:
                            if self.limit and total >= self.limit:
                                break
                            try:
                                await self._process(app, title, panel, traffit, nexus)
                            except PanelAuthError:
                                raise
                            except Exception as e:  # noqa: BLE001
                                self.stats["errors"] += 1
                                logger.exception("jjit: aplikacja %s", app.get("id"))
                                await self._event(
                                    action="error",
                                    external_id=str(app.get("id")),
                                    offer_title=title,
                                    error=str(e)[:300],
                                )
                            total += 1
                            await asyncio.sleep(PAUSE_BETWEEN_CANDIDATES_SEC)
            except Exception as e:  # noqa: BLE001
                logger.exception("jjit run %s failed", self.run_id)
                await self._finish_run("failed", str(e)[:1000])
                return dict(
                    self.stats, run_id=self.run_id, status="failed", error=str(e)[:300]
                )

            status = "errors" if self.stats["errors"] else "ok"
            await self._finish_run(status)
            return dict(self.stats, run_id=self.run_id, status=status)


async def run_once(
    *,
    dry_run: Optional[bool] = None,
    since: Optional[str] = None,
    states: Optional[list[str]] = None,
    limit: int = 0,
) -> dict:
    """Wejście dla pętli i endpointu admina. Domyślne wartości z configu."""
    if since is None:
        since = (_utcnow() - timedelta(days=int(settings.JJIT_LOOKBACK_DAYS))).strftime(
            "%Y-%m-%d"
        )
    run = JjitRun(
        dry_run=bool(settings.JJIT_DRY_RUN) if dry_run is None else dry_run,
        since=since,
        states=states
        or [s.strip() for s in settings.JJIT_STATES.split(",") if s.strip()],
        limit=limit,
    )
    return await run.execute()
