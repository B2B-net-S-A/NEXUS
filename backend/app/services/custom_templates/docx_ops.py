"""Operacje na akapitach DOCX — wspólne klocki wzorów (przeniesione 25.11.2026
ze ``scripts/build_b2b_document_templates.py``, który je teraz importuje).

Czytają je: buildery szablonów działu (skrypty), wykrywanie pól we wgranym
Wordzie i nakładanie zmian szkicu na wzór własny (``custom_templates``).

* ``replace_span`` — podmiana fragmentu tekstu akapitu z zachowaniem
  formatowania wokół (tekst bywa pocięty na wiele runów),
* ``doc_to_html`` — lustro HTML do podglądu,
* ``scrub_package`` — bez autorów, SharePointu, dodatków Worda i podświetleń.
"""

from __future__ import annotations

import copy
import html as _html
import io
import re
import zipfile
from typing import TYPE_CHECKING

from docx.document import Document as _Doc
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.text.run import Run


class DocxOpsError(RuntimeError):
    """Akapit nie daje się bezpiecznie zmienić (np. tekst poza runami)."""


if TYPE_CHECKING:
    Segment = tuple[str, bool | None]


def _segments(repl: str | list[Segment]) -> list[Segment]:
    return [(repl, None)] if isinstance(repl, str) else list(repl)


def paragraphs(doc: _Doc) -> list[Paragraph]:
    """Wszystkie akapity treści (także w tabelach), w kolejności dokumentu."""
    return [Paragraph(p, doc) for p in doc.element.body.iter(qn("w:p"))]


def _runs_text(p: Paragraph) -> tuple[list[Run], list[str]]:
    runs = list(p.runs)
    return runs, [r.text for r in runs]


_TEXT_ONLY = {qn("w:rPr"), qn("w:t"), qn("w:tab"), qn("w:br"), qn("w:cr")}


def _is_text_run(r: Run) -> bool:
    return all(child.tag in _TEXT_ONLY for child in r._r)


def _new_run_like(src: Run, p: Paragraph, text: str, bold: bool | None) -> Run:
    el = copy.deepcopy(src._r)
    run = Run(el, p)
    run.text = text
    if bold is not None:
        run.bold = bold
    return run


def replace_span(p: Paragraph, start: int, end: int, repl) -> None:
    """Zastąp znaki [start, end) tekstu akapitu, zachowując formatowanie
    tekstu wokół — wstawka dziedziczy formatowanie runu, w którym zaczyna się
    dopasowanie (chyba że segment mówi inaczej o pogrubieniu)."""
    runs, texts = _runs_text(p)
    full = "".join(texts)
    if full != p.text:
        raise DocxOpsError(
            f"Akapit ma tekst poza runami (hiperłącze?): {p.text[:60]!r}"
        )
    if not runs:
        p.add_run("")
        runs, texts = _runs_text(p)
    starts, acc = [], 0
    for t in texts:
        starts.append(acc)
        acc += len(t)

    def run_at(pos: int) -> int:
        for k, t in enumerate(texts):
            if starts[k] <= pos < starts[k] + len(t):
                return k
        return len(texts) - 1

    i = run_at(start)
    j = run_at(end - 1) if end > start else i
    ri = runs[i]
    prefix = texts[i][: start - starts[i]]
    suffix = texts[j][end - starts[j] :]
    for k in range(i + 1, j):
        runs[k]._r.getparent().remove(runs[k]._r)
    anchor = ri._r
    new_els = []
    for text, bold in _segments(repl):
        if text:
            new_els.append(_new_run_like(ri, p, text, bold)._r)
    if j > i:
        runs[j].text = suffix
    elif suffix:
        new_els.append(_new_run_like(ri, p, suffix, None)._r)
    for el in new_els:
        anchor.addnext(el)
        anchor = el
    if prefix:
        ri.text = prefix
    elif _is_text_run(ri):
        ri._r.getparent().remove(ri._r)
    else:
        ri.text = ""


def sub_para(p: Paragraph, rx: re.Pattern, repl) -> int:
    matches = [m for m in rx.finditer(p.text) if m.end() > m.start()]
    for m in reversed(matches):
        value = repl(m) if callable(repl) else repl
        replace_span(p, m.start(), m.end(), value)
    return len(matches)


def sub(doc: _Doc, pattern: str, repl, *, count: int | None = 1, flags: int = 0) -> int:
    """Podstaw ``repl`` za każde dopasowanie w akapitach; ``count`` = oczekiwana
    liczba trafień (inaczej błąd — wzór się zmienił i reguła nie trafia)."""
    rx = re.compile(pattern, flags | re.S)
    hits = sum(sub_para(p, rx, repl) for p in paragraphs(doc))
    if count is not None and hits != count:
        raise DocxOpsError(
            f"Reguła {pattern[:70]!r}: {hits} trafień, oczekiwano {count}"
        )
    return hits


# ── HTML (lustro podglądu) ──

_JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)
_ONLY_LINES = re.compile(r"^(?:[\s_.…()]|[Pp]odpis|[Ss]ignature)*$")


def _esc(s: str) -> str:
    return _html.escape(s, quote=False)


def _run_html(r: Run) -> str:
    text = re.sub(r"[\t\n]+", " ", r.text)
    if not text:
        return ""
    out = _esc(text)
    if r.underline:
        out = f"<u>{out}</u>"
    if r.bold:
        out = f"<strong>{out}</strong>"
    return out


def _is_numbered(p: Paragraph) -> bool:
    ppr = p._p.pPr
    return ppr is not None and ppr.numPr is not None


def _iter_blocks(doc: _Doc):
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


def doc_to_html(doc: _Doc) -> str:
    parts: list[str] = []
    in_list = False
    heading_done = False
    for block in _iter_blocks(doc):
        if isinstance(block, Table):
            rows = "".join(
                "<tr>"
                + "".join(f"<td>{_esc(c.text.strip())}</td>" for c in row.cells)
                + "</tr>"
                for row in block.rows
            )
            parts.append(f"<table>{rows}</table>")
            continue
        text = block.text.strip()
        if not text:
            continue
        if text.startswith("{%p"):
            parts.append("{%" + text[3:])
            continue
        numbered = _is_numbered(block)
        if numbered and not in_list:
            parts.append("<ol>")
            in_list = True
        elif not numbered and in_list:
            parts.append("</ol>")
            in_list = False
        inner = "".join(_run_html(r) for r in block.runs).strip()
        if numbered:
            parts.append(f"<li>{inner}</li>")
        elif re.match(r"^§\s*\S+\s*\.?$", _JINJA.sub("1", text)):
            parts.append(f"<h2>{_esc(text)}</h2>")
        elif not heading_done and block.alignment == 1:
            parts.append(f"<h1>{_esc(text)}</h1>")
            heading_done = True
        else:
            cls = ' class="right"' if block.alignment == 2 else ""
            parts.append(f"<p{cls}>{inner}</p>")
    if in_list:
        parts.append("</ol>")
    return "\n".join(parts) + "\n"


# ── Pakiet: podświetlenia i metadane ──

_CORE_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
    'metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/'
    'dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    "<dc:title>{title}</dc:title><dc:creator>B2B.net S.A.</dc:creator>"
    "<cp:lastModifiedBy>NEXUS</cp:lastModifiedBy><cp:revision>1</cp:revision>"
    '<dcterms:created xsi:type="dcterms:W3CDTF">2026-09-23T00:00:00Z</dcterms:created>'
    '<dcterms:modified xsi:type="dcterms:W3CDTF">2026-09-23T00:00:00Z</dcterms:modified>'
    "</cp:coreProperties>"
)


def _dropped(name: str) -> bool:
    return (
        name.startswith("customXml/")
        or name.startswith("word/webextensions/")
        or name == "docProps/custom.xml"
    )


_REL = re.compile(r"<Relationship\b[^>]*/>")
_OVERRIDE = re.compile(r"<Override\b[^>]*/>")


def scrub_package(data: bytes, title: str) -> bytes:
    """Bez autorów wzoru, metadanych SharePointu, dodatków Worda i podświetleń."""
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            name = info.filename
            if _dropped(name):
                continue
            body = src.read(name)
            if name == "docProps/core.xml":
                body = _CORE_XML.format(title=_esc(title)).encode()
            elif name == "docProps/app.xml":
                # Firma i kierownik ze wzoru (nazwa kancelarii), także z prefiksem.
                body = re.sub(
                    rb"<((?:\w+:)?(?:Company|Manager))>[^<]+</\1>", rb"<\1/>", body
                )
            elif name.endswith(".rels"):
                text = body.decode("utf-8")
                text = _REL.sub(
                    lambda m: (
                        ""
                        if re.search(
                            r'Target="[^"]*(customXml/|webextensions/|custom\.xml)',
                            m.group(0),
                        )
                        else m.group(0)
                    ),
                    text,
                )
                body = text.encode()
            elif name == "[Content_Types].xml":
                text = body.decode("utf-8")
                text = _OVERRIDE.sub(
                    lambda m: (
                        ""
                        if re.search(
                            r'PartName="/(customXml/|word/webextensions/|docProps/custom\.xml)',
                            m.group(0),
                        )
                        else m.group(0)
                    ),
                    text,
                )
                body = text.encode()
            elif name.startswith("word/") and name.endswith(".xml"):
                body = re.sub(rb"<w:highlight\b[^>]*/>", b"", body)
            zi = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            dst.writestr(zi, body)
    return out.getvalue()
