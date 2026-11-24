"""Serwer robota: pobudka z NEXUSA (POST /wake), kolejka biegów, jeden naraz.

NEXUS woła ``GROK_BOT_CPRO_WEBHOOK_URL`` z ``Authorization: Bearer <klucz>``;
tu ten sam klucz to ``CPRO_ROBOT_WAKE_KEY``. Pobudka odpowiada 202 od razu,
bieg idzie w wątku roboczym. Logi: tylko numery biegów, liczby i powody.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import queue
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Optional

from cpro_robot import nexus, rules

logger = logging.getLogger("cpro_robot")

MAX_BODY = 4096
PORTAL_BASE = "https://nordea.onevms.se/nordea/"


def item_report(
    ref: int, outcome: str, reason: Optional[str], message: str, **extra: Any
) -> dict[str, Any]:
    return {
        "ref": ref,
        "outcome": outcome,
        "reason": reason,
        "message": message[:400],
        **{k: v for k, v in extra.items() if v},
    }


def error_hint(exc: BaseException) -> str:
    """Rodzaj błędu do raportu: klasa i pierwsza linia bez treści w cudzysłowach.

    Komunikat Playwrighta potrafi cytować wpisywane wartości („Call log”), więc
    zostaje tylko pierwsza linia, a każdy tekst w cudzysłowie jest wycinany.
    """

    first = (str(exc).splitlines() or [""])[0]
    first = re.sub(r"(\"[^\"]*\"|'[^']*'|„[^”]*”)", "…", first)
    return f"{type(exc).__name__}: {first}"[:160]


def process_item(
    item: dict[str, Any], token: str, submit: bool, browser: Any, env: dict[str, str]
) -> dict[str, Any]:
    """Jedna pozycja: konto → CV → portal. Każdy wynik kończy się wierszem raportu."""

    from cpro_robot.portal import ItemRun, Outcome  # Playwright tylko w obrazie robota

    ref = item["ref"]
    try:
        account = rules.account_for(item.get("cpro_account"), env)
    except rules.AccountProblem as exc:
        return item_report(ref, "skipped", exc.reason, exc.message)
    try:
        cv = nexus.fetch_cv(item, token)
    except ValueError:
        return item_report(
            ref, "failed", "cv_not_pdf", "Plik CV z NEXUSA nie jest poprawnym PDF."
        )
    context = browser.new_context(accept_downloads=False)
    context.set_default_timeout(30_000)
    run = ItemRun(
        context.new_page(),
        PORTAL_BASE,
        item,
        account,
        cv,
        submit,
        dry_run=env.get("CPRO_ROBOT_DRY_RUN", "").lower() == "true",
    )
    try:
        out = run.run()
    except Outcome as exc:
        out = exc
    except Exception as exc:  # błąd robota, nie portalu: krok bez danych osoby
        # Bez tracebacku: komunikat Playwrighta („Call log”) potrafi zawierać
        # wartości wpisywane w pola, także hasło i dane osoby.
        logger.warning(
            "cpro_robot ref=%s step=%s error=%s", ref, run.step, type(exc).__name__
        )
        reason = "draft_unconfirmed" if run.saved else "other"
        out = Outcome(
            "failed", reason, f"Błąd robota na kroku „{run.step}”: {error_hint(exc)}."
        )
    finally:
        context.close()
    return item_report(
        ref,
        out.outcome,
        out.reason,
        out.message,
        cpro_status=out.cpro_status,
        offer_url=out.offer_url,
    )


def process_run(
    wake: nexus.Wake,
    origin: str,
    env: dict[str, str],
    browser_factory: Callable[[], Any],
) -> None:
    try:
        task = nexus.fetch_task(wake, origin)
    except nexus.TaskRejected as exc:
        logger.warning("cpro_robot run=%s task rejected: %s", wake.run_id, exc)
        return
    with browser_factory() as browser:
        report = [
            process_item(item, wake.token, task["submit"], browser, env)
            for item in task["items"]
        ]
    status = nexus.send_report(task, wake.token, report)
    outcomes = ",".join(
        f"{r['ref']}:{r['outcome']}/{r.get('reason') or '-'}" for r in report
    )
    logger.info(
        "cpro_robot run=%s report HTTP %s items=%s", wake.run_id, status, outcomes
    )


class _Chromium:
    def __enter__(self) -> Any:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        return self._browser

    def __exit__(self, *exc: Any) -> None:
        self._browser.close()
        self._pw.stop()


def make_handler(
    wake_key: str, origin: str, jobs: "queue.Queue[nexus.Wake]"
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(
            self, fmt: str, *args: Any
        ) -> None:  # bez ścieżek i nagłówków w logach
            return

        def _send(self, code: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send(200, {"status": "ok", "queued": jobs.qsize()})
            else:
                self._send(404, {"detail": "not found"})

        def do_POST(self) -> None:
            if self.path != "/wake":
                self._send(404, {"detail": "not found"})
                return
            auth = self.headers.get("Authorization", "")
            if not wake_key or not hmac.compare_digest(
                auth.encode(), f"Bearer {wake_key}".encode()
            ):
                self._send(401, {"detail": "unauthorized"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length <= 0 or length > MAX_BODY:
                self._send(400, {"detail": "bad body"})
                return
            try:
                wake = nexus.parse_wake(json.loads(self.rfile.read(length)), origin)
            except (ValueError, nexus.TaskRejected):
                self._send(400, {"detail": "bad wake"})
                return
            jobs.put(wake)
            logger.info("cpro_robot run=%s queued", wake.run_id)
            self._send(202, {"accepted": wake.run_id})

    return Handler


def worker(jobs: "queue.Queue[nexus.Wake]", origin: str, env: dict[str, str]) -> None:
    while True:
        wake = jobs.get()
        try:
            process_run(wake, origin, env, _Chromium)
        except Exception as exc:
            logger.warning(
                "cpro_robot run=%s crashed: %s", wake.run_id, type(exc).__name__
            )
        finally:
            jobs.task_done()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    env = dict(os.environ)
    origin = env.get("NEXUS_API_ORIGIN", "https://api.nexus.dynaminds.pl").rstrip("/")
    wake_key = env.get("CPRO_ROBOT_WAKE_KEY", "")
    if not wake_key:
        logger.warning(
            "cpro_robot: brak CPRO_ROBOT_WAKE_KEY, każda pobudka dostanie 401"
        )
    jobs: "queue.Queue[nexus.Wake]" = queue.Queue()
    threading.Thread(target=worker, args=(jobs, origin, env), daemon=True).start()
    server = ThreadingHTTPServer(
        ("0.0.0.0", int(env.get("PORT", "8090"))), make_handler(wake_key, origin, jobs)
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
