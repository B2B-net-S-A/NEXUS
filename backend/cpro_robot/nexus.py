"""Trasy biegu NEXUSA z tokenem: zlecenie, CV pozycji, jeden raport.

Te same zasady co dla rutyny Grok Bota (``docs/claude/integracje/cpro-bot-grok.md``,
„Bezpieczeństwo”): token idzie wyłącznie pod dokładny origin NEXUSA i ścieżki
tego biegu, bez przekierowań, userinfo, query ani fragmentu.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlsplit

SCHEMA_VERSION = 2
KIND = "cpro_offers"  # = app.services.cpro_bot.runs.KIND (pilnuje test)
TIMEOUT = 60
_REQUIRED = ("task", "report_format", "items", "submit", "callback_url", "expires_at")


class TaskRejected(Exception):
    """Wejście nie przeszło kontroli; robot nie zaczyna pracy."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def check_url(url: object, origin: str, path: str) -> str:
    """Adres z tokenem: dokładny origin i ścieżka, nic więcej."""

    if not isinstance(url, str):
        raise TaskRejected("adres nie jest tekstem")
    parts = urlsplit(url)
    want = urlsplit(origin)
    if (
        parts.scheme != want.scheme
        or parts.hostname != want.hostname
        or parts.port != want.port
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or parts.path != path
    ):
        raise TaskRejected("adres spoza biegu")
    return url


@dataclass(frozen=True)
class Wake:
    run_id: int
    token: str
    task_url: str


def parse_wake(body: object, origin: str) -> Wake:
    if not isinstance(body, dict):
        raise TaskRejected("pobudka bez obiektu")
    run_id = body.get("run_id")
    token = body.get("token")
    if body.get("schema_version") != SCHEMA_VERSION or body.get("kind") != KIND:
        raise TaskRejected("inna wersja pobudki")
    if (
        not isinstance(run_id, int)
        or run_id <= 0
        or not isinstance(token, str)
        or not token
    ):
        raise TaskRejected("pobudka bez biegu albo tokenu")
    url = check_url(
        body.get("task_url"), origin, f"/api/integrations/cpro-bot/runs/{run_id}/task"
    )
    return Wake(run_id, token, url)


def check_task(task: object, wake: Wake, origin: str) -> dict[str, Any]:
    """Całe zlecenie przed pracą: zgodny bieg, komplet pól, adresy CV z tego biegu."""

    if not isinstance(task, dict):
        raise TaskRejected("zlecenie nie jest obiektem")
    if (
        task.get("schema_version") != SCHEMA_VERSION
        or task.get("run_id") != wake.run_id
        or task.get("kind") != KIND
    ):
        raise TaskRejected("zlecenie innego biegu")
    if any(
        task.get(key) in (None, "") for key in _REQUIRED if key != "submit"
    ) or not isinstance(task.get("submit"), bool):
        raise TaskRejected("niepełne zlecenie")
    base = f"/api/integrations/cpro-bot/runs/{wake.run_id}"
    check_url(task["callback_url"], origin, base)
    items = task["items"]
    if not isinstance(items, list) or not items:
        raise TaskRejected("zlecenie bez pozycji")
    for item in items:
        ref = item.get("ref") if isinstance(item, dict) else None
        if not isinstance(ref, int):
            raise TaskRejected("pozycja bez ref")
        check_url((item.get("offer") or {}).get("cv_url"), origin, f"{base}/cv/{ref}")
    return task


def _request(
    url: str, token: str, *, data: Optional[bytes] = None
) -> tuple[int, dict[str, str], bytes]:
    headers = {"X-Run-Token": token, "User-Agent": "nexus-cpro-robot"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url, data=data, headers=headers, method="POST" if data is not None else "GET"
    )
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as resp:
            return (
                resp.status,
                {k.lower(): v for k, v in resp.headers.items()},
                resp.read(),
            )
    except urllib.error.HTTPError as exc:
        return exc.code, {}, b""


def fetch_task(wake: Wake, origin: str) -> dict[str, Any]:
    status, _, body = _request(wake.task_url, wake.token)
    if status != 200:
        raise TaskRejected(f"zlecenie HTTP {status}")
    try:
        task = json.loads(body)
    except ValueError as exc:
        raise TaskRejected("zlecenie nie jest JSON") from exc
    return check_task(task, wake, origin)


_PDF_NAME = re.compile(r"^[^#/\\]+\.pdf$", re.IGNORECASE)


def fetch_cv(item: dict[str, Any], token: str) -> bytes:
    """Zatwierdzony firmowy PDF pozycji. Wszystko inne → ``cv_not_pdf``."""

    offer = item.get("offer") or {}
    if offer.get("cv_format") != "pdf" or not _PDF_NAME.match(
        offer.get("cv_file_name") or ""
    ):
        raise ValueError("cv_not_pdf")
    status, headers, body = _request(offer["cv_url"], token)
    if (
        status != 200
        or not headers.get("content-type", "").startswith("application/pdf")
        or not body.startswith(b"%PDF-")
    ):
        raise ValueError("cv_not_pdf")
    return body


def send_report(task: dict[str, Any], token: str, items: list[dict[str, Any]]) -> int:
    status, _, _ = _request(
        task["callback_url"], token, data=json.dumps({"items": items}).encode()
    )
    return status
