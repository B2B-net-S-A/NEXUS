"""CV text extractor — PDF / DOCX / TXT → plain text.

The upload pipeline stores the original file on disk but never populated
`raw_cv_text`, which left the enrichment LLM without any input. This module
closes the gap.

Design
------
Dispatch by the file's real format (first bytes), falling back to the extension
(case-insensitive). Heavy libraries imported lazily so
import-time cost stays near zero in environments where CV uploads never happen
(e.g. CI unit tests that don't touch candidates).

Failures are swallowed into an empty string so the calling pipeline can proceed
with `raw_cv_text=""` and degrade gracefully to regex parsing. Only an
explicitly unsupported extension raises `UnsupportedCvFormat`; the upload
endpoint catches that and logs, still accepting the file.

Usage
-----
>>> from app.services.cv_text_extractor import extract_text
>>> text = await asyncio.to_thread(extract_text, "/tmp/nexus/uploads/file.pdf", "file.pdf")
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from typing import Optional

from app.core.log_safety import safe_filename

logger = logging.getLogger(__name__)


class UnsupportedCvFormat(Exception):
    """Raised when the file extension is not supported for text extraction."""


# Triple-or-more blank lines → a single blank line. Keeps paragraph structure.
_MULTI_BLANK_LINE = re.compile(r"\n{3,}")
# Runs of horizontal whitespace (spaces, tabs) collapsed to a single space.
_HORIZONTAL_WS = re.compile(r"[ \t]+")
# Trailing whitespace at end of each line.
_LINE_TRAILING = re.compile(r"[ \t]+\n")


def _normalize(text: str) -> str:
    """Collapse whitespace while preserving paragraph breaks.

    Drops NUL bytes first: some PDFs (broken font maps, OCR layers) yield
    ``\x00`` in the extracted text and Postgres rejects it at insert
    (``invalid byte sequence for encoding "UTF8": 0x00``), so ``/from-cv``
    answered 500 instead of creating the candidate.
    """
    if not text:
        return ""
    text = text.replace("\x00", "")
    text = _HORIZONTAL_WS.sub(" ", text)
    text = _LINE_TRAILING.sub("\n", text)
    text = _MULTI_BLANK_LINE.sub("\n\n", text)
    return text.strip()


# Threshold below which we suspect the PDF is a scan / image-only and fall
# back to OCR. 100 chars is enough to capture page-numbers/headers from a
# corrupt extraction; real CV text starts at >1KB.
_OCR_FALLBACK_THRESHOLD_CHARS = 100


# Średnia długość „słowa” (znaki / przerwy), powyżej której tekst uznajemy za
# SKLEJONY. Zwykłe CV ma ~6–8; PDF-y z ciasnym odstępem między literami dają
# w domyślnym odczycie 12–37 („ledtheqainitiativeandthedevelopment…”) —
# 1 581 CV na produkcji (23.09.2026), niewidocznych dla wyszukiwania słów.
GLUED_AVG_WORD_LEN = 12.0
_WHITESPACE_RUN = re.compile(r"\s+")


def avg_word_length(text: str) -> float:
    return len(text) / (len(_WHITESPACE_RUN.findall(text)) + 1)


def looks_glued(text: Optional[str]) -> bool:
    """Tekst bez przerw między słowami (krótkie teksty nie są oceniane)."""
    if not text or len(text) < 300:
        return False
    return avg_word_length(text) > GLUED_AVG_WORD_LEN


def _pdfplumber_text(pdf, **kwargs) -> str:
    return "\n\n".join(
        txt for page in pdf.pages if (txt := page.extract_text(**kwargs) or "")
    )


def _extract_pdf_native(path: str) -> Optional[str]:
    """Try pdfplumber first (better multi-column / layout), fall back to
    pdfminer.six on any failure. Both are pure-text extractors — return None
    if PDF is image-only (caller will trigger OCR).

    Sklejony wynik domyślnego odczytu (``looks_glued``) jest czytany drugi raz
    z ``x_tolerance=1``: pdfplumber wstawia spację, gdy odstęp między literami
    przekracza próg (domyślnie 3 pt), a PDF-y z ciasnym kerningiem mają odstęp
    międzywyrazowy poniżej niego. Próbka 24 takich CV z produkcji: średnia
    długość słowa 12–37 → 6–8. Próg niższy dla WSZYSTKICH PDF-ów ryzykowałby
    rozcinanie słów w rozstrzelonych nagłówkach, więc to tylko ścieżka zapasowa.
    """
    # pdfplumber preserves layout columns better than pdfminer for modern CVs.
    try:
        import pdfplumber  # type: ignore[import-untyped]

        with pdfplumber.open(path) as pdf:
            text = _pdfplumber_text(pdf)
            if looks_glued(text):
                tight = _pdfplumber_text(pdf, x_tolerance=1)
                if avg_word_length(tight) < avg_word_length(text):
                    text = tight
        if text:
            return text
    except Exception as e:  # pragma: no cover — defensive
        # Runda 8 (R8-V3-1): ścieżka na dysku to `…/{uuid8}-{oryginalna_nazwa}`
        # (zwykle imię i nazwisko), a komunikat wyjątku bywa tą ścieżką — do logu
        # idzie kształt pliku i klasa wyjątku.
        logger.info(
            "[cv_text_extractor] pdfplumber failed on %s: %s — trying pdfminer",
            safe_filename(path),
            type(e).__name__,
        )

    # Legacy fallback for rare PDFs that pdfplumber chokes on.
    try:
        from pdfminer.high_level import extract_text as _pdfminer_extract

        return _pdfminer_extract(path) or ""
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            "[cv_text_extractor] pdfminer also failed on %s: %s",
            safe_filename(path),
            type(e).__name__,
        )
        return None


def _extract_pdf_ocr(path: str) -> Optional[str]:
    """Render PDF pages to images and OCR them via tesseract.

    Used when native text extraction yields too little — typical for scanned
    CVs or image-only PDFs. Polish + English language packs cover most cases.
    Heavy: ~2-5s per page; we cap to first 10 pages (CVs are short).
    """
    try:
        import pytesseract  # type: ignore[import-untyped]
        from pdf2image import convert_from_path  # type: ignore[import-untyped]

        import tempfile

        # Runda 9 (R9-N7-2): `size` ogranicza rozmiar strony w pikselach (MediaBox
        # 200×200 cali przy 200 dpi to 40 000 × 40 000 px, czyli gigabajty na stronę),
        # a `output_folder` trzyma strony na dysku zamiast w pamięci procesu.
        with tempfile.TemporaryDirectory(prefix="nexus-ocr-") as tmpdir:
            pages = convert_from_path(
                path,
                dpi=200,
                last_page=10,
                size=_OCR_PAGE_MAX_PX,
                output_folder=tmpdir,
            )
            out: list[str] = []
            for img in pages:
                txt = pytesseract.image_to_string(img, lang="pol+eng")
                if txt:
                    out.append(txt)
        return "\n\n".join(out) if out else ""
    except (
        Exception
    ) as e:  # pragma: no cover — defensive (system tesseract may be missing)
        logger.warning(
            "[cv_text_extractor] OCR fallback failed on %s: %s",
            safe_filename(path),
            type(e).__name__,
        )
        return None


def _extract_pdf_inprocess(path: str) -> Optional[str]:
    """Extract PDF text — native first (pdfplumber→pdfminer), OCR fallback if
    output is suspiciously short (likely a scan).

    Returns None only on total failure so the dispatcher degrades to "".
    Runs in the sandboxed worker (``_extract_pdf``), never on the web process.
    """
    native = _extract_pdf_native(path)
    if native and len(native.strip()) >= _OCR_FALLBACK_THRESHOLD_CHARS:
        return native
    # Either native extraction failed, or yielded near-empty output → OCR.
    ocr = _extract_pdf_ocr(path)
    if ocr and len(ocr.strip()) >= _OCR_FALLBACK_THRESHOLD_CHARS:
        logger.info(
            "[cv_text_extractor] PDF %s extracted via OCR (native too short)",
            safe_filename(path),
        )
        return ocr
    # Return whichever has more content (could still be empty).
    return (native or "") if (len(native or "") >= len(ocr or "")) else (ocr or "")


# ── Odczyt PDF w osobnym procesie (runda 9, R9-N7-2) ─────────────────────────
#
# pdfminer dekompresuje strumienie PDF bez limitu, a pdf2image renderuje strony
# w rozmiarze z MediaBox — „bomba” PDF (kilka MB, które rozwijają się do
# gigabajtów) wgrana z formularza kariery albo z poczty zamówień zabijała
# OOM-killerem CAŁY backend (jeden proces uvicorna, limit kontenera 4 GB).
# Dlatego odczyt PDF idzie w podprocesie z limitem pamięci (RLIMIT_AS, dziedziczą
# go też pdftoppm i tesseract) i limitem czasu; przekroczenie = pusty tekst, jak
# każdy nieczytelny PDF. Koszt: start interpretera z pdfplumberem (~0,1–0,3 s).

#: Limit przestrzeni adresowej procesu odczytu. Tesseract z pol+eng i strony
#: A4 przy 200 dpi mieszczą się z zapasem.
PDF_WORKER_MEMORY_BYTES = 1536 * 1024 * 1024
#: Limit czasu całego odczytu (natywny + OCR do 10 stron po ~2–5 s).
PDF_WORKER_TIMEOUT_SECONDS = 150
#: Najdłuższy bok strony renderowanej do OCR (A4 przy 200 dpi = 2339 px).
_OCR_PAGE_MAX_PX = 2400
#: Sufit tekstu oddawanego przez proces odczytu — żadne CV ani zamówienie nie
#: ma dwóch milionów znaków, a odpowiedź czyta proces webowy.
_PDF_WORKER_MAX_CHARS = 2_000_000
_BACKEND_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_WORKER_OPS = (
    "pdf",
    "native",
    "pdfminer",
    "pages",
    "words",
    "all_pages",
    "word",
    "odt",
    "first_page_ocr",
)
#: Sufit liczby słów z położeniem (tabela zamówienia ma ich kilkaset).
_PDF_WORKER_MAX_WORDS = 50_000


def _pdf_worker_command(op: str, path: str) -> list[str]:
    return [sys.executable, "-m", "app.services.cv_text_extractor", op, path]


def _run_pdf_worker(
    op: str,
    path: str,
    *,
    timeout: float | None = None,
    memory_bytes: int | None = None,
) -> Optional[dict]:
    """Wynik operacji ``op`` z procesu odczytu albo ``None`` (limit, awaria)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (_BACKEND_ROOT, env.get("PYTHONPATH")) if p
    )
    env["NEXUS_PDF_WORKER_MEMORY_BYTES"] = str(memory_bytes or PDF_WORKER_MEMORY_BYTES)
    try:
        proc = subprocess.run(
            _pdf_worker_command(op, os.path.abspath(path)),
            capture_output=True,
            timeout=timeout or PDF_WORKER_TIMEOUT_SECONDS,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "[cv_text_extractor] PDF %s: odczyt przerwany po limicie czasu (%s)",
            safe_filename(path),
            op,
        )
        return None
    except OSError as e:
        logger.warning(
            "[cv_text_extractor] PDF %s: proces odczytu nie wystartował: %s",
            safe_filename(path),
            type(e).__name__,
        )
        return None
    if proc.returncode != 0:
        logger.warning(
            "[cv_text_extractor] PDF %s: proces odczytu zakończył się kodem %s (%s)"
            " — limit pamięci albo uszkodzony plik",
            safe_filename(path),
            proc.returncode,
            op,
        )
        return None
    # Ostatnia linia wyjścia to wynik; wcześniejsze (gdyby biblioteka coś
    # wypisała na stdout) pomijamy.
    lines = proc.stdout.decode("utf-8", "replace").strip().splitlines()
    try:
        result = json.loads(lines[-1]) if lines else None
    except ValueError:
        return None
    return result if isinstance(result, dict) else None


#: Strona z mniejszą liczbą znaków idzie do OCR (test paczki umów 30.10.2026:
#: Aneks NBP miał 9 z 13 stron skanem obok tekstu na pozostałych).
_OCR_PAGE_MIN_CHARS = 50
#: Sufit odczytu dokumentu prawnego; najdłuższy skan z paczki ma 248 stron.
ALL_PAGES_MAX = 500
#: Limit czasu odczytu wszystkich stron: start + sekundy na stronę, z sufitem.
_ALL_PAGES_TIMEOUT_BASE_SECONDS = 150
_ALL_PAGES_TIMEOUT_PER_PAGE_SECONDS = 10
_ALL_PAGES_TIMEOUT_MAX_SECONDS = 3600


@dataclass(frozen=True)
class AllPagesText:
    """Tekst wszystkich stron PDF-a i to, ile z nich przeczytał OCR."""

    text: str
    pages: int
    ocr_pages: int


def all_pages_timeout(pages: Optional[int]) -> int:
    """Skan OCR-uje się kilka sekund na stronę, więc limit rośnie ze stronami."""
    return min(
        _ALL_PAGES_TIMEOUT_BASE_SECONDS
        + _ALL_PAGES_TIMEOUT_PER_PAGE_SECONDS * min(pages or 0, ALL_PAGES_MAX),
        _ALL_PAGES_TIMEOUT_MAX_SECONDS,
    )


def extract_pdf_all_pages_sandboxed(path: str) -> Optional[AllPagesText]:
    """Cały PDF dla dokumentów prawnych: tekst stron, a strony bez tekstu z OCR.

    CV i zamówienia zostają przy ``extract_text`` (OCR 10 pierwszych stron).
    ``None`` = limit czasu, limit pamięci albo uszkodzony plik.
    """
    pages = pdf_page_count_sandboxed(path)
    result = _run_pdf_worker("all_pages", path, timeout=all_pages_timeout(pages))
    text = result.get("text") if result else None
    if not isinstance(text, str):
        return None
    return AllPagesText(
        text=text,
        pages=int(result.get("pages") or 0),
        ocr_pages=int(result.get("ocr_pages") or 0),
    )


def _extract_pdf(path: str) -> Optional[str]:
    """Tekst PDF z procesu odczytu z limitem pamięci i czasu (R9-N7-2)."""
    result = _run_pdf_worker("pdf", path)
    text = result.get("text") if result else None
    return text if isinstance(text, str) else None


def extract_pdf_native_sandboxed(path: str) -> Optional[str]:
    """``_extract_pdf_native`` w procesie odczytu (bez OCR)."""
    result = _run_pdf_worker("native", path)
    text = result.get("text") if result else None
    return text if isinstance(text, str) else None


def extract_pdfminer_sandboxed(path: str) -> Optional[str]:
    """Sam pdfminer.six w procesie odczytu (poczta zamówień: literowanie)."""
    result = _run_pdf_worker("pdfminer", path)
    text = result.get("text") if result else None
    return text if isinstance(text, str) and text else None


def pdf_page_count_sandboxed(path: str) -> Optional[int]:
    """Liczba stron PDF z procesu odczytu."""
    result = _run_pdf_worker("pages", path)
    pages = result.get("pages") if result else None
    return pages if isinstance(pages, int) else None


def extract_pdf_words_sandboxed(path: str) -> Optional[list]:
    """Słowa PDF z położeniem z procesu odczytu: ``[strona, x0, x1, góra, dół, tekst]``.

    Tabele, których kolumn nie da się odtworzyć ze zwykłego tekstu (PKO BP:
    wielolinijkowy profil sklejał się z nazwiskiem), reguła klienta czyta
    z położenia słów pod nagłówkami.
    """
    result = _run_pdf_worker("words", path)
    words = result.get("words") if result else None
    return words if isinstance(words, list) else None


def _worker_words(path: str) -> Optional[list]:
    try:
        import pdfplumber  # type: ignore[import-untyped]

        out: list = []
        with pdfplumber.open(path) as pdf:
            for number, page in enumerate(pdf.pages):
                for word in page.extract_words():
                    out.append(
                        [
                            number,
                            round(float(word["x0"]), 2),
                            round(float(word["x1"]), 2),
                            round(float(word["top"]), 2),
                            round(float(word["bottom"]), 2),
                            str(word["text"]).replace("\x00", ""),
                        ]
                    )
                    if len(out) >= _PDF_WORKER_MAX_WORDS:
                        return out
        return out
    except Exception:  # noqa: BLE001 — wynik best-effort
        return None


def _ocr_one_page(path: str, number: int) -> str:
    """OCR jednej strony (numer od 1); strona na dysku, nie w pamięci procesu."""
    import tempfile

    import pytesseract  # type: ignore[import-untyped]
    from pdf2image import convert_from_path  # type: ignore[import-untyped]

    with tempfile.TemporaryDirectory(prefix="nexus-ocr-") as tmpdir:
        images = convert_from_path(
            path,
            dpi=200,
            first_page=number,
            last_page=number,
            size=_OCR_PAGE_MAX_PX,
            output_folder=tmpdir,
        )
        return "\n".join(
            pytesseract.image_to_string(image, lang="pol+eng") for image in images
        )


def _worker_first_page_ocr(path: str) -> Optional[str]:
    """OCR pierwszej strony; awaria to brak nagłówka, nie brak tekstu CV."""
    try:
        os.environ["OMP_THREAD_LIMIT"] = "1"
        return _ocr_one_page(path, 1)
    except Exception:  # noqa: BLE001 — wynik best-effort
        return None


def _worker_all_pages(path: str) -> dict:
    """Strona po stronie: tekst z PDF-a, a gdy go brak, OCR tej strony."""
    try:
        import pdfplumber  # type: ignore[import-untyped]

        # Jeden wątek: odczyt skanu nie może zająć wszystkich rdzeni serwera.
        os.environ["OMP_THREAD_LIMIT"] = "1"
        parts: list[str] = []
        ocr_pages = 0
        with pdfplumber.open(path) as pdf:
            total = len(pdf.pages)
            for number, page in enumerate(pdf.pages[:ALL_PAGES_MAX], start=1):
                text = page.extract_text() or ""
                if looks_glued(text):
                    tight = page.extract_text(x_tolerance=1) or ""
                    if avg_word_length(tight) < avg_word_length(text):
                        text = tight
                page.close()
                if len(text.strip()) < _OCR_PAGE_MIN_CHARS:
                    try:
                        scanned = _ocr_one_page(path, number)
                    except Exception:  # noqa: BLE001 — zostaje tekst strony
                        scanned = ""
                    if len(scanned.strip()) > len(text.strip()):
                        text = scanned
                        ocr_pages += 1
                if text.strip():
                    parts.append(text)
        return {"text": "\n\n".join(parts), "pages": total, "ocr_pages": ocr_pages}
    except Exception:  # noqa: BLE001 — wynik best-effort
        return {"text": None}


def _worker_pdfminer(path: str) -> Optional[str]:
    try:
        from pdfminer.high_level import extract_text as _pdfminer_extract

        return _pdfminer_extract(path) or None
    except Exception:  # noqa: BLE001 — wynik best-effort
        return None


def _worker_page_count(path: str) -> Optional[int]:
    try:
        import pdfplumber  # type: ignore[import-untyped]

        with pdfplumber.open(path) as pdf:
            return len(pdf.pages)
    except Exception:  # noqa: BLE001 — metadane są best-effort
        return None


def _apply_worker_limits() -> None:
    try:
        import resource

        limit = int(
            os.environ.get("NEXUS_PDF_WORKER_MEMORY_BYTES") or PDF_WORKER_MEMORY_BYTES
        )
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, ValueError, OSError):  # pragma: no cover — macOS/Windows
        pass


def _worker_main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in _WORKER_OPS:
        return 2
    op, path = argv
    _apply_worker_limits()
    payload: dict = {}
    if op == "pdf":
        payload["text"] = _extract_pdf_inprocess(path)
    elif op == "native":
        payload["text"] = _extract_pdf_native(path)
    elif op == "pdfminer":
        payload["text"] = _worker_pdfminer(path)
    elif op == "words":
        payload["words"] = _worker_words(path)
    elif op == "all_pages":
        payload = _worker_all_pages(path)
    elif op == "word":
        payload["text"] = _worker_word(path)
    elif op == "odt":
        payload["text"] = _worker_odt(path)
    elif op == "first_page_ocr":
        payload["text"] = _worker_first_page_ocr(path)
    else:
        payload["pages"] = _worker_page_count(path)
    text = payload.get("text")
    if isinstance(text, str) and len(text) > _PDF_WORKER_MAX_CHARS:
        payload["text"] = text[:_PDF_WORKER_MAX_CHARS]
    sys.stdout.write("\n" + json.dumps(payload) + "\n")
    sys.stdout.flush()
    return 0


#: Tylko prawdziwy Word po bajtach. RTF czy HTML pod nazwą `.doc` zostają bez
#: tekstu: arkusz stylów z HTML-a wykonywał żądanie mimo blokady linków w profilu.
_WORD_IMPORT_FILTERS = {".doc": "MS Word 97", ".docx": "MS Word 2007 XML"}


def _worker_word(path: str) -> Optional[str]:
    """Plik Worda przez LibreOffice do PDF-a, dalej zwykły odczyt PDF (z OCR)."""
    infilter = _WORD_IMPORT_FILTERS.get(sniff_extension(path) or "")
    if not infilter:
        return None
    try:
        from app.core.zip_guard import assert_safe_ooxml
        from app.services.cv_pdf_preview import docx_to_pdf

        # `_extract_docx` połyka odmowę strażnika, więc bomba ZIP dochodzi aż tutaj.
        assert_safe_ooxml(path)
        with open(path, "rb") as handle:
            pdf = docx_to_pdf(handle.read(), infilter=infilter)
        with tempfile.TemporaryDirectory(prefix="nexus-word-") as tmpdir:
            target = os.path.join(tmpdir, "word.pdf")
            with open(target, "wb") as handle:
                handle.write(pdf)
            return _extract_pdf_inprocess(target)
    except Exception as e:  # noqa: BLE001 — wynik best-effort
        logger.warning(
            "[cv_text_extractor] LibreOffice failed on %s: %s",
            safe_filename(path),
            type(e).__name__,
        )
        return None


# LibreOffice to ciężki proces (`cv_pdf_preview`): jedna zamiana naraz na proces
# webowy, a kolejka z limitem, żeby seria plików nie zabrała wątków innym trasom.
_word_slot = threading.BoundedSemaphore(1)
_WORD_SLOT_WAIT_SECONDS = 60
#: LibreOffice rezerwuje więcej przestrzeni adresowej niż pdfplumber i tesseract:
#: prawdziwe CV (69 KB) przy 1,5 GB kończyło się sygnałem 11, od 1,75 GB czytało się.
WORD_WORKER_MEMORY_BYTES = 2560 * 1024 * 1024


def _extract_word_via_pdf(path: str) -> Optional[str]:
    """Tekst Worda z LibreOffice, w procesie odczytu z limitem pamięci i czasu."""
    from app.services.cv_pdf_preview import soffice_path

    if not soffice_path():
        return None
    if not _word_slot.acquire(timeout=_WORD_SLOT_WAIT_SECONDS):
        logger.warning(
            "[cv_text_extractor] %s: LibreOffice zajęty, plik bez odczytu",
            safe_filename(path),
        )
        return None
    try:
        result = _run_pdf_worker("word", path, memory_bytes=WORD_WORKER_MEMORY_BYTES)
    finally:
        _word_slot.release()
    text = result.get("text") if result else None
    return text if isinstance(text, str) else None


def _extract_word(path: str) -> Optional[str]:
    """Word: python-docx, a gdy prawie nic nie odczytał, LibreOffice.

    python-docx odrzuca binarny `.doc`, a w `.docx` pomija pola tekstowe
    i kontrolki, więc takie CV miało pusty tekst i `/from-cv` odpowiadał 400
    (03.11.2026, zgłoszenia z Pracuj.pl przepadały). LibreOffice jest tylko
    ścieżką zapasową, bo wolny: pomiar na kopii produkcji to 0,4–2,6 s na plik.
    """
    text = _extract_docx(path)
    if len((text or "").strip()) >= _OCR_FALLBACK_THRESHOLD_CHARS:
        return text
    via_pdf = _extract_word_via_pdf(path)
    if len(via_pdf or "") > len(text or ""):
        logger.info(
            "[cv_text_extractor] %s extracted via LibreOffice (python-docx too short)",
            safe_filename(path),
        )
        return via_pdf
    return text


def _extract_docx(path: str) -> Optional[str]:
    """Extract text from a DOCX via python-docx (binary .doc always fails here)."""
    try:
        from docx import Document  # type: ignore[import-untyped]

        from app.core.docx_cells import grid_cell_texts
        from app.core.zip_guard import assert_safe_ooxml

        assert_safe_ooxml(path)
        doc = Document(path)
        lines = [p.text for p in doc.paragraphs if p.text]
        # Include table cells — CVs often layout experience as tables.
        # `grid_cell_texts`, nie `row.cells`: ten sam tekst co dotąd, ale liczby
        # z pliku (CV z formularza kariery) nie sterują już kosztem odczytu.
        lines.extend(grid_cell_texts(doc.tables))
        return "\n".join(lines)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            "[cv_text_extractor] python-docx failed on %s: %s",
            safe_filename(path),
            type(e).__name__,
        )
        return None


_ODF_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
_ODF_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_ODF_PARAGRAPHS = frozenset({f"{_ODF_TEXT}p", f"{_ODF_TEXT}h"})
#: `text:s` niesie liczbę spacji z pliku, a `_normalize` i tak zwija je do jednej,
#: więc liczba z pliku nie steruje kosztem odczytu.
_ODF_INLINE_BREAKS = {
    f"{_ODF_TEXT}s": " ",
    f"{_ODF_TEXT}tab": "\t",
    f"{_ODF_TEXT}line-break": "\n",
}
#: Usunięty tekst ze śledzenia zmian i komentarze: w pliku są, w dokumencie nie.
_ODF_NOT_CONTENT = frozenset(
    {f"{_ODF_TEXT}tracked-changes", f"{_ODF_OFFICE}annotation"}
)


def _odf_parse(content: bytes):
    # Plik od kandydata: bez DTD, encji i sieci, jak `hr/bank/camt053.py`.
    from lxml import etree

    return etree.fromstring(
        content,
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            load_dtd=False,
            huge_tree=False,
            remove_comments=True,
            remove_pis=True,
        ),
    )


def _odf_collect(element, out: list[str], in_paragraph: bool = False) -> None:
    """Tekst akapitów z poddrzewa. Poza `text:p` i `text:h` tekstu nie bierzemy,
    bo leżą tam opisy obrazków i wzorce spisu treści."""
    if in_paragraph and element.text:
        out.append(element.text)
    for child in element:
        tag = child.tag
        # Encja zostaje w drzewie jako węzeł bez nazwy; tekst po niej jest treścią.
        if isinstance(tag, str) and tag not in _ODF_NOT_CONTENT:
            if tag in _ODF_PARAGRAPHS:
                out.append("\n")
                _odf_collect(child, out, True)
                out.append("\n")
            elif tag in _ODF_INLINE_BREAKS:
                out.append(_ODF_INLINE_BREAKS[tag])
            else:
                _odf_collect(child, out, in_paragraph and tag.startswith(_ODF_TEXT))
        if in_paragraph and child.tail:
            out.append(child.tail)


def _worker_odt(path: str) -> Optional[str]:
    """ODT: tekst z `content.xml`, w procesie odczytu, bo drzewo XML buduje się
    z pliku od kandydata. Limit rozpakowanego rozmiaru daje `assert_safe_ooxml`."""
    try:
        import zipfile

        from app.core.zip_guard import assert_safe_ooxml

        assert_safe_ooxml(path)
        with zipfile.ZipFile(path) as archive:
            root = _odf_parse(archive.read("content.xml"))
        parts: list[str] = []
        _odf_collect(root.find(f"{_ODF_OFFICE}body"), parts)
        return "\n".join(line for line in "".join(parts).splitlines() if line.strip())
    except Exception as e:  # noqa: BLE001 — wynik best-effort
        logger.warning(
            "[cv_text_extractor] ODT read failed on %s: %s",
            safe_filename(path),
            type(e).__name__,
        )
        return None


def _extract_odt(path: str) -> Optional[str]:
    result = _run_pdf_worker("odt", path)
    text = result.get("text") if result else None
    return text if isinstance(text, str) else None


def _extract_txt(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            "[cv_text_extractor] txt read failed on %s: %s",
            safe_filename(path),
            type(e).__name__,
        )
        return None


def _declared_extension(file_path: str, filename: str) -> str:
    """Extension from the filename (stable across temp-file renames), falling
    back to the on-disk path."""
    _, ext = os.path.splitext(filename or "")
    if not ext:
        _, ext = os.path.splitext(file_path or "")
    return ext.lower()


_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ODT_MIMETYPE = b"application/vnd.oasis.opendocument.text"
# PDF allows junk before the header; readers look within the first 1 KB.
_SNIFF_BYTES = 1024


def _zip_document_extension(archive) -> Optional[str]:
    """``.docx`` albo ``.odt`` po zawartości archiwum; xlsx, pages czy arkusz ODS
    to też ZIP, ale nie dokument tekstowy."""
    names = archive.namelist()
    if "word/document.xml" in names:
        return ".docx"
    if "mimetype" in names:
        with archive.open("mimetype") as handle:
            if handle.read(len(_ODT_MIMETYPE) + 1) == _ODT_MIMETYPE:
                return ".odt"
    return None


def sniff_extension(file_path: str) -> Optional[str]:
    """Real format from the file's first bytes: ``.pdf``, ``.docx``, ``.odt``, ``.doc``.

    The NAME lies. Measured on prod 2026-09-22: 3 320 Traffit CVs named
    ``*.docx`` are PDFs inside (Traffit serves its converted copy under the
    original name). Dispatching by name sent them to python-docx, which failed,
    and the backfill marked them ``empty`` — terminal — so their text was never
    searched. ``None`` = no known signature (plain text, images, garbage);
    the caller keeps the declared extension then.
    """
    try:
        with open(file_path, "rb") as f:
            head = f.read(_SNIFF_BYTES)
    except OSError:
        return None
    if head.startswith(_OLE_MAGIC):
        return ".doc"
    if head.startswith(_ZIP_MAGIC):
        try:
            import zipfile

            with zipfile.ZipFile(file_path) as zf:
                return _zip_document_extension(zf)
        except Exception:  # noqa: BLE001 — broken zip = unknown format
            return None
    if _PDF_MAGIC in head:
        return ".pdf"
    return None


def sniff_extension_bytes(data: bytes) -> Optional[str]:
    """``sniff_extension`` dla bajtów w pamięci (generator CV — runda 6 audytu).

    Generator CV dostaje plik jako bajty i do 26.09.2026 wybierał parser po
    nazwie: PDF zapisany jako ``.docx`` (3 320 takich z Traffita) kończył się
    „Nie można odczytać dokumentu DOCX.” Ta sama reguła co ``sniff_extension``.
    """
    head = bytes(data[:_SNIFF_BYTES]) if data else b""
    if head.startswith(_OLE_MAGIC):
        return ".doc"
    if head.startswith(_ZIP_MAGIC):
        try:
            import io
            import zipfile

            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                return _zip_document_extension(zf)
        except Exception:  # noqa: BLE001 — broken zip = unknown format
            return None
    if _PDF_MAGIC in head:
        return ".pdf"
    return None


def _resolve_extension(file_path: str, filename: str) -> str:
    """Format to parse as: the sniffed one when the bytes say so, otherwise the
    declared extension."""
    declared = _declared_extension(file_path, filename)
    sniffed = sniff_extension(file_path)
    if sniffed and sniffed != declared:
        logger.info(
            "[cv_text_extractor] %s declared %r but content is %r — using content",
            # runda 6 audytu: nazwa pliku CV to zwykle imię i nazwisko
            safe_filename(filename or file_path),
            declared,
            sniffed,
        )
        return sniffed
    return declared


def extract_text(file_path: str, filename: str) -> str:
    """Read `file_path` and return its text content as a single string.

    Parameters
    ----------
    file_path : str
        Absolute or relative path to the file on disk.
    filename : str
        Original uploaded filename — used to determine format when `file_path`
        is an extension-less temp file.

    Returns
    -------
    str
        Extracted, whitespace-normalized text. Empty string on extraction
        failure (never None).

    Raises
    ------
    UnsupportedCvFormat
        If the format is not one of: .pdf, .docx, .doc, .odt, .txt. The format
        comes from the file's first bytes when they carry a known signature, so
        a PDF saved as ``cv.docx`` (or ``cv.odt``) is read as a PDF.
    """
    ext = _resolve_extension(file_path, filename)

    if ext == ".pdf":
        raw = _extract_pdf(file_path)
    elif ext in (".docx", ".doc"):
        raw = _extract_word(file_path)
    elif ext == ".odt":
        raw = _extract_odt(file_path)
    elif ext == ".txt":
        raw = _extract_txt(file_path)
    else:
        raise UnsupportedCvFormat(
            f"Unsupported CV format: {ext!r} (filename={filename!r}). "
            "Supported: .pdf, .docx, .doc, .odt, .txt"
        )

    return _normalize(raw or "")


# ── Nazwisko i kontakt w grafice nagłówka CV (05.11.2026) ────────────────────
#
# PDF z tekstem w treści i nagłówkiem w obrazku przekracza próg
# ``_OCR_FALLBACK_THRESHOLD_CHARS``, więc OCR nie rusza, a tekst nie ma nazwiska,
# maila ani telefonu. Reguła nagłówka bierze wtedy nagłówek sekcji, a wykrywanie
# duplikatów nie ma czego szukać. Pomiar: ``kandydaci-wyszukiwanie/odczyt-naglowka-z-grafiki.md``.

#: OCR jednej strony z procesem odczytu: mediana ok. 2,4 s, najgorszy plik 27 s.
_FIRST_PAGE_OCR_TIMEOUT_SECONDS = 45
#: Sufit bloku: to nagłówek, nie druga kopia pierwszej strony.
_OCR_HEADER_MAX_LINES = 15
_OCR_WORD = re.compile(r"[^\W_]+")
#: Linia OCR jest nowa, gdy co najmniej tyle jej słów nie ma w tekście PDF-a.
#: OCR myli pojedyncze litery, więc linia z tekstu PDF-a bywa nowa w części.
_OCR_NEW_LINE_MIN_SHARE = 0.6
#: Adres z OCR nie wchodzi do tekstu, także z `@` odczytaną jako litera. Kalibracja na
#: 190 CV z mailem w tekście: 8 z 80 odczytanych adresów było błędnych, a drugi odczyt
#: w 300 dpi tego nie łapie (w 5 z 55 par mylą się oba). Wiadomość do kandydata
#: poszłaby do obcej osoby. Telefon: 2 z 179 błędnych.
_OCR_ADDRESS = re.compile(
    r"\S*(?:@|\.(?:com|pl|eu|net|org|io|de|uk)\b)\S*", re.IGNORECASE
)


def _ocr_lines_missing_from_text(native: str, ocr: str) -> list[str]:
    """Linie z OCR, których tekst PDF-a nie ma, w kolejności ze strony.

    Linia z telefonem zostaje zawsze: reszta jej słów bywa w tekście PDF-a, a sam
    numer leży czasem w stopce, za sufitem bloku.
    """
    from app.services.cv_parser import _extract_phone_from_text

    known = {word.casefold() for word in _OCR_WORD.findall(native)}
    lines: list[str] = []
    other_lines = 0
    for raw_line in ocr.splitlines():
        line = _HORIZONTAL_WS.sub(" ", _OCR_ADDRESS.sub("", raw_line)).strip()
        if _extract_phone_from_text(line):
            lines.append(line)
            continue
        words = [w.casefold() for w in _OCR_WORD.findall(line) if len(w) >= 2]
        if not words or other_lines >= _OCR_HEADER_MAX_LINES:
            continue
        new_words = [word for word in words if word not in known]
        if len(new_words) >= _OCR_NEW_LINE_MIN_SHARE * len(words):
            lines.append(line)
            other_lines += 1
    return lines


def extract_cv_text(file_path: str, filename: str) -> str:
    """``extract_text`` dla CV: PDF bez maila i telefonu dostaje OCR pierwszej strony.

    Linie, których nie ma w tekście PDF-a, idą bez adresów na początek, jak nagłówek
    na stronie. Dalej to zwykły tekst CV: nazwa z niego przechodzi przez odczyt
    modelu, ``record_detected_identity`` i bramkę, jak każda inna. Zamówienia
    i dokumenty klientów zostają przy ``extract_text``. Awaria OCR zostawia tekst PDF-a.
    """
    text = extract_text(file_path, filename)
    # Krótszy tekst przeszedł już OCR w `_extract_pdf_inprocess`, cały plik.
    if (
        len(text) < _OCR_FALLBACK_THRESHOLD_CHARS
        or sniff_extension(file_path) != ".pdf"
    ):
        return text
    from app.services.cv_parser import (
        _extract_email_from_text,
        _extract_phone_from_text,
    )

    if _extract_email_from_text(text) or _extract_phone_from_text(text):
        return text
    result = _run_pdf_worker(
        "first_page_ocr", file_path, timeout=_FIRST_PAGE_OCR_TIMEOUT_SECONDS
    )
    ocr = result.get("text") if result else None
    lines = _ocr_lines_missing_from_text(text, ocr) if isinstance(ocr, str) else []
    if not lines:
        return text
    return _normalize("\n".join(lines) + "\n\n" + text)


if __name__ == "__main__":  # proces odczytu PDF (``_run_pdf_worker``)
    sys.exit(_worker_main(sys.argv[1:]))
