"""Stos wątku pętli zdarzeń, gdy pętla stoi dłużej niż ``LOOP_STALL_DUMP_SECONDS``.

24.11.2026 proces web stawał po 52 s (11:39–12:03 i 13:12–13:18, CPU 86–100%,
bez pełnego GC): wszystkie żądania czekały, przeglądarki zrywały je po 30 s
(„Nie udało się zapisać wyboru.” w „Umów rozmowę i prepy”). ``runtime_metrics``
mówi, że pętla stała, ale nie mówi, na której linii — na stagingu się nie
odtwarza. Decyzja Artura 24.11.2026: strażnik, który przy zastoju zapisuje stos.

Jak działa: ``faulthandler.dump_traceback_later`` uzbrajany co sekundę z pętli
zdarzeń. Gdy pętla nie zdąży go przezbroić, wątek C faulthandlera po progu
zrzuca stosy wszystkich wątków do pliku tymczasowego — także wtedy, gdy kod
w pętli trzyma GIL (wątek Pythona by się wtedy nie doczekał). Po powrocie pętla
czyta plik i loguje JSON ``event_kind="loop_stall"`` ze stosem samego wątku
pętli: ścieżki, numery linii i nazwy funkcji, bez wartości zmiennych.

Jeden zrzut na zastój (z chwili ``LOOP_STALL_DUMP_SECONDS`` po jego początku).
``0`` wyłącza strażnika. Awaria strażnika nigdy nie przerywa pętli metryk.
"""

from __future__ import annotations

import asyncio
import faulthandler
import logging
import os
import re
import tempfile
import threading
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

REARM_SECONDS = 1.0
MAX_FRAMES = 40

_THREAD_HEADER = re.compile(r"^(?:Current thread|Thread) (0x[0-9a-fA-F]+)")
_FRAME = re.compile(r'^\s+File "(?P<path>[^"]+)", line (?P<line>\d+) in (?P<func>\S+)')


def _short_path(path: str) -> str:
    """``/app/app/api/x.py`` → ``app/api/x.py``; biblioteki od ``site-packages/``."""
    if path.startswith("/app/"):
        return path.removeprefix("/app/")
    _, sep, tail = path.rpartition("site-packages/")
    return tail if sep else path


def parse_dump(text: str, thread_id: int) -> tuple[list[str], int]:
    """Ramki wątku ``thread_id`` (najnowsza pierwsza) i liczba wszystkich wątków w zrzucie."""
    frames: list[str] = []
    threads = 0
    current: int | None = None
    for line in text.splitlines():
        header = _THREAD_HEADER.match(line)
        if header:
            threads += 1
            current = int(header.group(1), 16)
            continue
        frame = _FRAME.match(line)
        if frame and current == thread_id and len(frames) < MAX_FRAMES:
            frames.append(
                f"{_short_path(frame['path'])}:{frame['line']} {frame['func']}"
            )
    return frames, threads


class LoopStallGuard:
    def __init__(self, threshold_seconds: float, path: Path | None = None):
        self.threshold_seconds = threshold_seconds
        self.path = (
            path or Path(tempfile.gettempdir()) / f"nexus-loop-stall-{os.getpid()}.txt"
        )
        self.thread_id = threading.get_ident()
        # Przezbrojenie dużo częściej niż próg — inaczej zwykły sen pętli wygląda jak zastój.
        self.rearm_seconds = min(REARM_SECONDS, threshold_seconds / 3)

    def report(self, sink) -> bool:
        """Zaloguj zrzut, jeśli jest, i wyczyść plik. ``True`` = był zastój."""
        text = self.path.read_text("utf-8", errors="replace")
        if not text.strip():
            return False
        sink.seek(0)
        sink.truncate()
        frames, threads = parse_dump(text, self.thread_id)
        logger.warning(
            "loop_stall",
            extra={
                "event_kind": "loop_stall",
                "process_role": settings.NEXUS_PROCESS_ROLE,
                "stall_threshold_seconds": self.threshold_seconds,
                "threads": threads,
                "frames": frames,
            },
        )
        return True

    async def run(self) -> None:
        self.thread_id = threading.get_ident()
        with open(self.path, "wb", buffering=0) as sink:
            try:
                while True:
                    faulthandler.dump_traceback_later(
                        self.threshold_seconds, repeat=False, file=sink
                    )
                    await asyncio.sleep(self.rearm_seconds)
                    try:
                        self.report(sink)
                    except Exception as exc:  # noqa: BLE001 — pomiar, nie może wywrócić pętli
                        logger.warning(
                            "loop_stall report failed",
                            extra={
                                "event_kind": "loop_stall",
                                "failure_kind": type(exc).__name__,
                            },
                        )
            finally:
                faulthandler.cancel_dump_traceback_later()


async def loop_stall_guard(threshold_seconds: float | None = None) -> None:
    """Strażnik na czas życia wywołującego; ``0`` albo błąd startu = nic nie robi."""
    threshold = (
        settings.LOOP_STALL_DUMP_SECONDS
        if threshold_seconds is None
        else threshold_seconds
    )
    if threshold <= 0:
        return
    try:
        await LoopStallGuard(threshold).run()
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — bez strażnika metryki idą dalej
        logger.warning(
            "loop_stall guard failed",
            extra={"event_kind": "loop_stall", "failure_kind": type(exc).__name__},
        )
