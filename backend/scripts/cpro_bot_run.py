#!/usr/bin/env python3
"""Próba bota Cpro przed włączeniem flagi: kolejka, braki i jeden bieg.

Bez ``--start`` skrypt tylko pokazuje kolejkę Cpro tak, jak widzi ją bot:
karta, rekrutacja (numer requestu), braki albo „gotowa”, skąd dane. Nic nie
wysyła — tak sprawdzisz kolejkę na produkcji przed włączeniem.

``--start --stage-ids <id>`` zleca bieg na wskazane karty także przy
wyłączonym ``CPRO_BOT_ENABLED``. Domyślnie to PRÓBA: bot wypełnia ofertę
i zostawia ją jako szkic (DRAFT) w Cpro, nic nie idzie do Nordei. ``--submit``
wysyła naprawdę (Submit Offer) i przesuwa kartę na „Wysłane do Cpro”.

Uruchomienie (z ``backend/``)::

    python -m scripts.cpro_bot_run
    python -m scripts.cpro_bot_run --start --stage-ids 123456
    python -m scripts.cpro_bot_run --start --stage-ids 123456 --submit

``--interactive-draft`` tworzy zlecenie jednego szkicu bez webhooka przy wyłączonej fladze.
Świeży token przekazuje wyłącznie wcześniej podłączonemu prywatnemu pipe/socketowi
``--token-fd``. Nie ma opcji wypisania lub odzyskania tokenu.
``--repair-draft-run-id`` pozwala wyłącznie poprawić szkic potwierdzony
raportem wskazanego biegu dla tej samej karty, konta i requestu.

Wynik to identyfikatory, liczby i braki, bez nazwisk i stawek (logi są publiczne).
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import logging
import os
import re
import socket
import stat
import sys
from datetime import datetime, timezone
from typing import Optional, Sequence

from app.core.database import AsyncSessionLocal, engine
from app.core.scheduling import business_date
from app.services.cpro_bot import flow, runs
from app.services.cpro_bot import items as bot_items


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse wstawia podaną wartość do błędów typu i nieznanych opcji.
        # Nie powtarzaj wejścia operatora w publicznym strumieniu diagnostyki.
        self.exit(2, '{"started": false, "status": "invalid_arguments"}\n')


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Wymagana dodatnia liczba.") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("Wymagana dodatnia liczba.")
    return number


def _request_number(value: str) -> str:
    if re.fullmatch(r"[0-9]{4,7}", value) is None:
        raise argparse.ArgumentTypeError("Wymagany numer requestu Cpro.")
    return value


def validate_token_fd(fd: int) -> None:
    """Token może opuścić proces wyłącznie dedykowanym pipe lub socketem Unix."""

    if fd < 3:
        raise ValueError("invalid_token_channel")
    info = os.fstat(fd)
    if not (stat.S_ISFIFO(info.st_mode) or stat.S_ISSOCK(info.st_mode)):
        raise ValueError("invalid_token_channel")
    if (fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE) == os.O_RDONLY:
        raise ValueError("invalid_token_channel")
    for public_fd in (0, 1, 2):
        try:
            public = os.fstat(public_fd)
        except OSError:
            continue
        if (info.st_dev, info.st_ino) == (public.st_dev, public.st_ino):
            raise ValueError("invalid_token_channel")
    if stat.S_ISSOCK(info.st_mode):
        # Nie dopuść przypadkowego socketu TCP ani niepołączonego odbiorcy.
        with socket.socket(fileno=os.dup(fd)) as channel:
            if channel.family != socket.AF_UNIX:
                raise ValueError("invalid_token_channel")
            channel.getpeername()


def deliver_token(fd: int, token: str) -> None:
    """Jedna krótka wiadomość do wcześniej zweryfikowanego odbiorcy, bez logów."""

    validate_token_fd(fd)
    data = token.encode("ascii") + b"\n"
    if len(data) > 256 or re.fullmatch(rb"[A-Za-z0-9_-]+\n", data) is None:
        raise ValueError("invalid_fresh_token")
    blocking = os.get_blocking(fd)
    try:
        os.set_blocking(fd, False)
        if os.write(fd, data) != len(data):
            raise OSError("incomplete_token_delivery")
    finally:
        os.set_blocking(fd, blocking)


async def interactive_draft(
    stage_id: int,
    *,
    delivery_lead_id: int,
    request_number: str,
    token_fd: int,
    repair_draft_run_id: Optional[int] = None,
) -> dict[str, object]:
    """Utwórz zlecenie szkicu i przekaż świeży token poza stdout/stderr."""

    run_id: Optional[int] = None
    try:
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            try:
                run, fresh_token = await flow.create_interactive_draft(
                    db,
                    stage_id,
                    delivery_lead_id=delivery_lead_id,
                    request_number=request_number,
                    now=now,
                    today=business_date(now),
                    repair_draft_run_id=repair_draft_run_id,
                )
            except flow.NotReady:
                return {"started": False, "status": "not_ready"}
            run_id = run.id
            try:
                deliver_token(token_fd, fresh_token)
            except (OSError, ValueError):
                # Bieg jest już zapisany. Nie zostawiaj działającego tokenu,
                # którego nie dało się dostarczyć do chronionego odbiorcy.
                await runs._close_open_run(
                    db,
                    run_id,
                    status="failed",
                    error="Nie dostarczono tokenu do prywatnego kanału operatora.",
                )
                return {
                    "started": False,
                    "status": "token_delivery_failed",
                    "run_id": run_id,
                }
            finally:
                fresh_token = None
            return {
                "started": True,
                "run_id": run_id,
                "status": run.status,
                "submit": False,
                "items": 1,
            }
    except Exception:
        result: dict[str, object] = {"started": False, "status": "interactive_error"}
        if run_id is not None:
            result["run_id"] = run_id
        return result
    finally:
        await engine.dispose()


def _ids(value: str) -> list[int]:
    try:
        return [int(part) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--stage-ids: liczby po przecinku.") from exc


async def show() -> dict[str, object]:
    try:
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            queue = await bot_items.load_items(db, now=now, today=business_date(now))
            states = await runs.item_states(db, [i.stage_id for i in queue], now=now)
            return {
                "items": [
                    {
                        "stage_id": item.stage_id,
                        "job_id": item.job_id,
                        "delivery_lead_id": item.extra.get("delivery_lead_id"),
                        "request": (item.payload or {}).get("request_number"),
                        "ready": item.payload is not None,
                        "blockers": list(item.blockers),
                        "data_from": list(item.data_from),
                        "bot_state": states[item.stage_id].state
                        if item.stage_id in states
                        else None,
                    }
                    for item in queue
                ],
            }
    finally:
        await engine.dispose()


async def start(stage_ids: list[int], submit: bool) -> dict[str, object]:
    try:
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            try:
                run = await flow.start_chosen(
                    db, stage_ids, now=now, today=business_date(now), submit=submit
                )
            except flow.NotReady as exc:
                return {"started": False, "reason": exc.detail}
            return {
                "started": True,
                "run_id": run.id,
                "status": run.status,
                "submit": run.submit,
                "error": run.error,
                "items": len(run.stage_ids or []),
            }
    finally:
        await engine.dispose()


def main(argv: Optional[Sequence[str]] = None) -> int:
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    interactive = any(arg.split("=", 1)[0] == "--interactive-draft" for arg in raw_args)
    parser_type = SafeArgumentParser if interactive else argparse.ArgumentParser
    parser = parser_type(description="Próba bota Cpro")
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--stage-ids", type=_ids, default=[])
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--interactive-draft", action="store_true")
    parser.add_argument(
        "--delivery-lead-id",
        type=_positive_int,
        help="Rzeczywisty DL rekrutacji: 14 (Igor), 27 (Marcin), 32 (Dominik, konto Cpro Marcina).",
    )
    parser.add_argument("--request-number", type=_request_number)
    parser.add_argument("--token-fd", type=_positive_int)
    parser.add_argument("--repair-draft-run-id", type=_positive_int)
    args = parser.parse_args(raw_args)
    if args.interactive_draft:
        if (
            args.start
            or args.submit
            or len(args.stage_ids) != 1
            or args.stage_ids[0] <= 0
            or args.delivery_lead_id is None
            or args.request_number is None
            or args.token_fd is None
        ):
            parser.error("Niepoprawne argumenty szkicu interaktywnego.")
        try:
            validate_token_fd(args.token_fd)
        except (OSError, ValueError, OverflowError):
            print(
                '{"started": false, "status": "invalid_token_channel"}', file=sys.stderr
            )
            return 2
        if runs.enabled():
            print('{"started": false, "status": "bot_enabled"}')
            return 1
        # Wyjątki ORM/transportu nie mogą wypisać parametrów lub treści wejścia.
        previous_logging_disable = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            result = asyncio.run(
                interactive_draft(
                    args.stage_ids[0],
                    delivery_lead_id=args.delivery_lead_id,
                    request_number=args.request_number,
                    token_fd=args.token_fd,
                    repair_draft_run_id=args.repair_draft_run_id,
                )
            )
        except Exception:
            result = {"started": False, "status": "interactive_error"}
        finally:
            logging.disable(previous_logging_disable)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("started") else 1
    if any(
        value is not None
        for value in (
            args.delivery_lead_id,
            args.request_number,
            args.token_fd,
            args.repair_draft_run_id,
        )
    ):
        parser.error("Opcje wymagają --interactive-draft.")
    if not args.start:
        print(json.dumps(asyncio.run(show()), ensure_ascii=False, indent=1))
        return 0
    if not args.stage_ids:
        parser.error("--start wymaga --stage-ids.")
    if not runs.configured():
        print("Brak GROK_BOT_CPRO_WEBHOOK_URL albo _KEY.", file=sys.stderr)
        return 2
    result = asyncio.run(start(args.stage_ids, args.submit))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") in ("started", "received") else 1


if __name__ == "__main__":
    sys.exit(main())
