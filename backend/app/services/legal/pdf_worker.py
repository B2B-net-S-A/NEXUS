"""Odczyt linii PDF-u tekstu jednolitego w osobnym procesie.

``pdfplumber`` na 120–400 stronach to kilkanaście sekund czystego Pythona
(KC 25.11.2026: 7,5 s). W wątku workera trzymałby GIL i zatrzymywał pętlę
zdarzeń wszystkich pętli w tle, więc biegnie tu, z limitem pamięci i czasu —
tak jak odczyt PDF-ów w ``cv_text_extractor``.

Uruchomienie: ``python -m app.services.legal.pdf_worker <plik.pdf>``; wynik to
JSON ``[[tekst, rozmiar], …]`` w ostatniej linii wyjścia.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from typing import Optional

from app.services.legal.parse import PdfLine, read_pdf_lines

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 300
MEMORY_BYTES = 2 * 1024 * 1024 * 1024
_BACKEND_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


def _limit_memory() -> None:
    try:
        import resource

        limit = int(os.environ.get("NEXUS_LEGAL_PDF_MEMORY_BYTES") or MEMORY_BYTES)
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, ValueError, OSError):  # macOS nie zawsze pozwala
        pass


def read_lines_in_process(path: str) -> Optional[list[PdfLine]]:
    """Linie PDF-u z procesu odczytu albo ``None`` (limit, awaria). Blokujące."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (_BACKEND_ROOT, env.get("PYTHONPATH")) if p
    )
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "app.services.legal.pdf_worker",
                os.path.abspath(path),
            ],
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("[legal] odczyt PDF przerwany po %s s", TIMEOUT_SECONDS)
        return None
    except OSError as exc:
        logger.warning(
            "[legal] proces odczytu PDF nie wystartował: %s", type(exc).__name__
        )
        return None
    if proc.returncode != 0:
        logger.warning(
            "[legal] proces odczytu PDF zakończył się kodem %s", proc.returncode
        )
        return None
    lines = proc.stdout.decode("utf-8", "replace").strip().splitlines()
    if not lines:
        return None
    try:
        rows = json.loads(lines[-1])
    except ValueError:
        return None
    return [PdfLine(str(text), float(size)) for text, size in rows]


async def read_lines(path: str) -> Optional[list[PdfLine]]:
    return await asyncio.to_thread(read_lines_in_process, path)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        return 2
    _limit_memory()
    rows = [[line.text, line.size] for line in read_pdf_lines(argv[1])]
    sys.stdout.write(json.dumps(rows, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - proces potomny
    raise SystemExit(main(sys.argv))
