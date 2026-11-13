"""Walidacja e-faktury regułami EN16931 i Peppol BIS Billing 3 przed wysyłką.

Reguły to oficjalne pliki Schematron OpenPeppol (wydanie w
``scripts/build_peppol_rules.py``) skompilowane do XSLT 2.0 w ``rules/``.
XSLT 2.0 uruchamia Saxon HE (pakiet ``saxonche``); ``lxml`` obsługuje tylko
XSLT 1.0. Wynik to SVRL: ``failed-assert`` z ``flag="fatal"`` blokuje wysyłkę,
``warning`` tylko pokazujemy.

Saxon działa w osobnym procesie (jeden stały proces potomny, ``spawn``).
SaxonC to natywny obraz GraalVM: wywołany z innego wątku niż ten, który
utworzył procesor, kończy CAŁY proces błędem ``StackOverflowError`` (zmierzone
13.11.2026 przy ``asyncio.to_thread``). W procesie potomnym taka awaria zabija
tylko jego — pula zakłada nowy, a faktura dostaje „walidator niedostępny”
zamiast położonego API. Skompilowane reguły zostają w procesie potomnym między
wywołaniami (kompilacja ok. 1 s, walidacja ok. 0,1 s).

Walidujemy wyłącznie XML zbudowany przez ``ubl.build`` (nie plik z zewnątrz).
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import re
import threading
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from lxml import etree

RULES_DIR = Path(__file__).resolve().parent / "rules"
RULE_FILES = ("CEN-EN16931-UBL.xsl", "PEPPOL-EN16931-UBL.xsl")
SVRL = "http://purl.oclc.org/dsdl/svrl"
MAX_FINDINGS = 50
TIMEOUT_SECONDS = 120
logger = logging.getLogger(__name__)
_PREFIX_RE = re.compile(r"^\[[^\]]+\]\s*-\s*")
_PREDICATE_RE = re.compile(r"Q\{[^}]*\}")

_pool_lock = threading.Lock()
_pool: Optional[ProcessPoolExecutor] = None
#: Stan procesu potomnego: procesor Saxona i skompilowane reguły.
_child: dict[str, Any] = {}


class ValidationUnavailable(RuntimeError):
    """Brak Saxona, plików reguł albo proces walidatora padł — faktura nie wyjdzie."""


@dataclass(frozen=True)
class Finding:
    rule: str
    flag: str
    text: str
    location: str

    @property
    def blocking(self) -> bool:
        return self.flag != "warning"

    def as_dict(self) -> dict[str, str]:
        return {
            "rule": self.rule,
            "flag": self.flag,
            "text": self.text,
            "location": self.location,
        }


# ── Proces potomny ───────────────────────────────────────────────────────────


def _child_executables() -> tuple[Any, list[Any]]:
    if "executables" not in _child:
        from saxonche import PySaxonProcessor

        missing = [name for name in RULE_FILES if not (RULES_DIR / name).is_file()]
        if missing:
            raise FileNotFoundError(", ".join(missing))
        processor = PySaxonProcessor(license=False)
        compiler = processor.new_xslt30_processor()
        _child["processor"] = processor
        _child["executables"] = [
            compiler.compile_stylesheet(stylesheet_file=str(RULES_DIR / name))
            for name in RULE_FILES
        ]
    return _child["processor"], _child["executables"]


def _run_rules(xml: bytes) -> list[str]:
    """W procesie potomnym: SVRL każdego zestawu reguł."""

    processor, executables = _child_executables()
    document = processor.parse_xml(xml_text=xml.decode("utf-8"))
    out = []
    for executable in executables:
        result = executable.transform_to_string(xdm_node=document)
        if result is None:
            raise RuntimeError("empty_result")
        out.append(result)
    return out


# ── Proces główny ────────────────────────────────────────────────────────────


def _executor() -> ProcessPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ProcessPoolExecutor(
                max_workers=1, mp_context=multiprocessing.get_context("spawn")
            )
        return _pool


def _reset() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            # Zawieszony Saxon nie skończy sam — zabijamy proces potomny.
            for process in list(getattr(_pool, "_processes", {}).values()):
                process.kill()
            _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None


def _short_location(raw: Optional[str]) -> str:
    return _PREDICATE_RE.sub("", raw or "")[:300]


def _findings(svrl: str) -> list[Finding]:
    root = etree.fromstring(svrl.encode("utf-8"))
    out = []
    for node in root.iter(f"{{{SVRL}}}failed-assert", f"{{{SVRL}}}successful-report"):
        text = " ".join((node.findtext(f"{{{SVRL}}}text") or "").split())
        out.append(
            Finding(
                rule=node.get("id") or "",
                flag=(node.get("flag") or "fatal").lower(),
                text=_PREFIX_RE.sub("", text)[:500],
                location=_short_location(node.get("location")),
            )
        )
    return out


def _parse(results: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for svrl in results:
        findings.extend(_findings(svrl))
    return findings[:MAX_FINDINGS]


def _unavailable(exc: BaseException) -> ValidationUnavailable:
    logger.warning("[peppol] walidator niedostępny: %s", type(exc).__name__)
    if isinstance(exc, BrokenProcessPool):
        _reset()
        return ValidationUnavailable(
            "Walidator e-faktur przerwał pracę — spróbuj ponownie."
        )
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return ValidationUnavailable("Brak procesora XSLT 2.0 (saxonche).")
    if isinstance(exc, FileNotFoundError):
        return ValidationUnavailable(f"Brak plików reguł: {exc}.")
    if isinstance(exc, TimeoutError):
        _reset()
        return ValidationUnavailable("Walidator e-faktur nie odpowiedział na czas.")
    return ValidationUnavailable("Walidator e-faktur zwrócił błąd.")


def validate(xml: bytes) -> list[Finding]:
    """Wszystkie naruszenia reguł (puste = dokument poprawny)."""

    try:
        results = _executor().submit(_run_rules, xml).result(timeout=TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 — każdy błąd walidatora blokuje wysyłkę
        raise _unavailable(exc) from exc
    return _parse(results)


async def validate_async(xml: bytes) -> list[Finding]:
    try:
        future = asyncio.wrap_future(_executor().submit(_run_rules, xml))
        results = await asyncio.wait_for(future, timeout=TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 — każdy błąd walidatora blokuje wysyłkę
        raise _unavailable(exc) from exc
    return _parse(results)


def blocking(findings: list[Finding]) -> list[Finding]:
    return [finding for finding in findings if finding.blocking]
