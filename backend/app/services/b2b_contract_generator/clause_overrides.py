"""Per-klient modyfikacje treści umowy B2B (silnik operacji + matcher).

Niektórzy Klienci wymagają specyficznych zapisów. Zamiast modyfikować szablon
(`umowa_b2b_{pl,en}.docx/html`) i `build_b2b_templates.py`, podmieniamy/dokładamy
treść w JUŻ wyrenderowanym dokumencie — domyślna umowa dla pozostałych Klientów
pozostaje nietknięta.

Silnik wspiera operacje (Op = ``(kind, target, blocks)``):
  - ``replace_section``    target=int  → podmień cały § N (np. § 4, § 10)
  - ``append_to_section``  target=int  → dołącz akapity na końcu § N (przed § N+1)
  - ``append_appendix``    target=None → nowy Załącznik na końcu dokumentu (page-break)
  - ``after_table``        target=int  → wstaw akapity po tabeli (indeks)
  - ``after_sentence``     target=str  → wstaw akapity po akapicie zawierającym frazę

Blok = ``(kind, text)``. kind: ``h`` nagłówek (centrowany bold), ``sub`` podtytuł
(centrowany bold), ``sh`` nagłówek sekcji wewnątrz załącznika (bold), ``p``
klauzula numerowana, ``i`` podpunkt a)/b) (wcięcie), ``b`` wypunktowanie,
``sig`` linia podpisu (plain), ``gap`` pusty akapit.

Treść klauzul (PL+EN) trzymana w ``clause_override_content.py``.
"""

from __future__ import annotations

import html
import re

Block = tuple[str, str]
Op = tuple[str, object, tuple[Block, ...]]


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def overrides_for_client(client_name: str | None, language: str) -> list[Op]:
    """Lista operacji modyfikujących umowę dla danego Klienta (pusta = brak).

    Dopasowanie po znormalizowanej nazwie Klienta; treść w języku umowy (PL/EN)."""
    if not client_name:
        return []
    from app.services.b2b_contract_generator.clause_override_content import (
        CLIENT_OVERRIDES,
    )

    is_en = (language or "pl").lower().startswith("en")
    n = _norm(client_name)
    for needles, ops_builder in CLIENT_OVERRIDES:
        if any(needle in n for needle in needles):
            return ops_builder("en" if is_en else "pl")
    return []


def has_override(client_name: str | None) -> bool:
    """Czy Klient ma jakiekolwiek modyfikacje umowy (dowolny język)."""
    return bool(overrides_for_client(client_name, "pl"))


# ── Render bloków do HTML ────────────────────────────────────────────────────


def _blocks_html(blocks: tuple[Block, ...]) -> str:
    out: list[str] = []
    for kind, text in blocks:
        # quote=False: treść elementu (<p>…), nie atrybut → czyste apostrofy.
        esc = html.escape(text, quote=False)
        if kind == "h":
            out.append(f"<h2>{esc}</h2>")
        elif kind in ("sub", "sh"):
            out.append(f"<p><strong>{esc}</strong></p>")
        elif kind == "i":
            out.append(f'<p style="margin-left:1.5em">{esc}</p>')
        elif kind == "b":
            out.append(f'<p style="margin-left:2.5em">{esc}</p>')
        elif kind == "gap":
            out.append("<p></p>")
        else:  # "p", "sig"
            out.append(f"<p>{esc}</p>")
    return "\n".join(out) + "\n"


# ── HTML: aplikacja operacji na wyrenderowanym stringu ───────────────────────

_H2 = re.compile(r"<h2[ >]")


def _html_section_span(rendered: str, n: int) -> tuple[int, int] | None:
    """(start nagłówka § N, start następnego <h2>) lub None."""
    m = re.search(rf"<h2>\s*§\s*{n}\s*\.?\s*</h2>", rendered)
    if not m:
        return None
    nxt = _H2.search(rendered, m.end())
    end = nxt.start() if nxt else len(rendered)
    return (m.start(), end)


def apply_ops_html(rendered_html: str, ops: list[Op]) -> str:
    out = rendered_html
    for kind, target, blocks in ops:
        frag = _blocks_html(blocks)
        if kind == "replace_section":
            span = _html_section_span(out, int(target))  # type: ignore[arg-type]
            if span:
                out = out[: span[0]] + frag + out[span[1] :]
        elif kind == "append_to_section":
            span = _html_section_span(out, int(target))  # type: ignore[arg-type]
            if span:
                out = out[: span[1]] + frag + out[span[1] :]
        elif kind == "append_appendix":
            out = out.rstrip() + "\n" + frag
        elif kind == "after_table":
            idx = out.find("</table>")
            if idx != -1:
                cut = idx + len("</table>")
                out = out[:cut] + "\n" + frag + out[cut:]
        elif kind == "after_sentence":
            anchor = str(target)
            pos = out.find(anchor)
            if pos != -1:
                close = out.find("</p>", pos)
                if close != -1:
                    cut = close + len("</p>")
                    out = out[:cut] + "\n" + frag + out[cut:]
    return out


# ── DOCX: aplikacja operacji na wyrenderowanym python-docx Document ──────────


def _ref_font(paragraph) -> tuple[object, object]:
    if paragraph is not None and paragraph.runs:
        f = paragraph.runs[0].font
        return (f.size, f.name)
    return (None, None)


def _doc_ref_styles(doc):
    """(base_style, head_font, body_font) z reprezentatywnych akapitów umowy."""
    base_style = None
    head_p = body_p = None
    for p in doc.paragraphs:
        t = (p.text or "").strip()
        if head_p is None and re.fullmatch(r"§\s*\d+\s*A?", t):
            head_p = p
            base_style = p.style
        elif body_p is None and len(t) > 80:
            body_p = p
        if head_p is not None and body_p is not None:
            break
    return (base_style, _ref_font(head_p), _ref_font(body_p))


def _apply_font(run, font) -> None:
    size, name = font
    if size is not None:
        run.font.size = size
    if name is not None:
        run.font.name = name


def _style_para(para, kind: str, text: str, styles) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches

    base_style, head_font, body_font = styles
    if base_style is not None:
        para.style = base_style
    run = para.add_run(text)
    pf = para.paragraph_format
    if kind in ("h", "sub"):
        run.bold = True
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _apply_font(run, head_font)
    elif kind == "sh":
        run.bold = True
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        _apply_font(run, body_font)
    elif kind == "sig":
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        _apply_font(run, body_font)
    elif kind == "gap":
        pass
    else:  # p / i / b
        para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        # Klauzule numerowane (`p`) bez wcięcia akapitu — flush jak natywne
        # paragrafy umowy (left_indent=None), żeby § 4A / § 4 BNP nie wyróżniały
        # się innym wcięciem. Wcięcie zostaje tylko dla podpunktów a)/b) i bullet.
        if kind in ("i", "b"):
            pf.left_indent = Inches(0.5)
        _apply_font(run, body_font)


def _new_p(body_parent):
    from docx.oxml import OxmlElement
    from docx.text.paragraph import Paragraph

    el = OxmlElement("w:p")
    return el, Paragraph(el, body_parent)


def _emit_before(ref_el, body_parent, blocks, styles) -> None:
    """Wstaw akapity (w kolejności) przed elementem ``ref_el``."""
    for kind, text in blocks:
        el, para = _new_p(body_parent)
        ref_el.addprevious(el)
        _style_para(para, kind, text, styles)


def _emit_after(ref_el, body_parent, blocks, styles, *, page_break_first=False):
    """Wstaw akapity (w kolejności) po elemencie ``ref_el``."""
    cur = ref_el
    first = True
    for kind, text in blocks:
        el, para = _new_p(body_parent)
        cur.addnext(el)
        _style_para(para, kind, text, styles)
        if first and page_break_first:
            para.paragraph_format.page_break_before = True
        first = False
        cur = el


def _find_section_heading_el(doc, n: int):
    for p in doc.paragraphs:
        if re.fullmatch(rf"§\s*{n}\s*A?", (p.text or "").strip()):
            return p._p
    return None


def _next_heading_el(doc, start_el):
    """Element następnego nagłówka (§ N / § NA / Załącznik) po ``start_el``."""
    seen = False
    for p in doc.paragraphs:
        if p._p is start_el:
            seen = True
            continue
        if not seen:
            continue
        t = (p.text or "").strip()
        if re.fullmatch(r"§\s*\d+\s*A?", t) or re.match(r"(?i)za[łl]ącznik\s*nr", t):
            return p._p
    return None


def apply_ops_docx(doc, ops: list[Op]) -> int:
    """Zastosuj operacje na wyrenderowanym DOCX. Zwraca liczbę wykonanych."""
    styles = _doc_ref_styles(doc)
    body_parent = doc.paragraphs[0]._parent if doc.paragraphs else None
    if body_parent is None:
        return 0
    applied = 0
    for kind, target, blocks in ops:
        if kind == "replace_section":
            start = _find_section_heading_el(doc, int(target))  # type: ignore[arg-type]
            if start is None:
                continue
            nxt = _next_heading_el(doc, start)
            if nxt is None:
                continue
            # usuń akapity § N (od nagłówka do przed następnym nagłówkiem)
            el = start
            while el is not None and el is not nxt:
                to_remove = el
                el = el.getnext()
                to_remove.getparent().remove(to_remove)
            _emit_before(nxt, body_parent, blocks, styles)
            applied += 1
        elif kind == "append_to_section":
            start = _find_section_heading_el(doc, int(target))  # type: ignore[arg-type]
            if start is None:
                continue
            nxt = _next_heading_el(doc, start)
            if nxt is None:
                continue
            _emit_before(nxt, body_parent, blocks, styles)
            applied += 1
        elif kind == "append_appendix":
            last_el = doc.paragraphs[-1]._p
            _emit_after(last_el, body_parent, blocks, styles, page_break_first=True)
            applied += 1
        elif kind == "after_table":
            idx = int(target)  # type: ignore[arg-type]
            if idx < len(doc.tables):
                _emit_after(doc.tables[idx]._tbl, body_parent, blocks, styles)
                applied += 1
        elif kind == "after_sentence":
            anchor = str(target)
            ref = None
            for p in doc.paragraphs:
                if anchor in (p.text or ""):
                    ref = p._p
                    break
            if ref is not None:
                _emit_after(ref, body_parent, blocks, styles)
                applied += 1
    return applied
