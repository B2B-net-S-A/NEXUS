"""Zmiany jako śledzenie zmian Worda (``w:ins``/``w:del``) i komentarze.

Zasady, które trzymają plik „bez naprawy” w Wordzie i LibreOffice:

* Przebieg dzielimy tylko na granicy zmiany; kopia dostaje to samo ``w:rPr``
  (formatowanie zostaje). ``w:pPr`` akapitu nie ruszamy, poza znakiem akapitu
  wstawionego/skreślonego (``w:pPr/w:rPr/w:ins|w:del`` — na początku ``w:rPr``).
* Skreślony tekst przechodzi z ``w:t`` do ``w:delText`` wewnątrz ``w:del``.
* ``w:ins`` nigdy w ``w:ins`` — wstawka obok cudzej wstawki idzie poziom wyżej.
* Pola Worda są nietykalne (``RedlineError`` z prośbą o ręczną zmianę).
* ``w:id`` zmian i komentarzy rośnie od największego ``w:id`` w dokumencie.
"""

from __future__ import annotations

import copy
import re
from collections import defaultdict
from dataclasses import replace as dc_replace
from datetime import datetime
from typing import Iterable

from lxml import etree

from app.services.legal_redline.docx_io import (
    CT_NS,
    DOCUMENT_PART,
    REL_NS,
    W_NS,
    XML_NS,
    DocxPackage,
    Segment,
    is_heading_style,
    load_package,
    paragraph_elements,
    paragraph_segments,
    parse_xml,
    serialize_xml,
    w,
    write_package,
)
from app.services.legal_redline.model import (
    AUTHOR,
    AUTHOR_INITIALS,
    RedlineChange,
    RedlineError,
)

COMMENTS_PART = "word/comments.xml"
DOC_RELS_PART = "word/_rels/document.xml.rels"
CONTENT_TYPES_PART = "[Content_Types].xml"
COMMENTS_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
)
COMMENTS_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
)


def format_word_date(when: datetime) -> str:
    """Word zapisuje czas lokalny z dopiskiem ``Z`` — tak samo robimy my."""
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


class _Ids:
    def __init__(self, start: int) -> None:
        self._next = start

    def take(self) -> str:
        value = self._next
        self._next += 1
        return str(value)


def _max_id(*roots: etree._Element | None) -> int:
    best = 0
    attr = w("id")
    for root in roots:
        if root is None:
            continue
        for el in root.iter():
            raw = el.get(attr)
            if raw and raw.lstrip("-").isdigit():
                best = max(best, int(raw))
    return best


# ── budowa elementów ────────────────────────────────────────────────────────


def _el(tag: str, **attrs: str) -> etree._Element:
    el = etree.Element(w(tag))
    for key, value in attrs.items():
        el.set(w(key), value)
    return el


def _text_children(text: str, *, deleted: bool = False) -> list[etree._Element]:
    """Tekst → ``w:t``/``w:tab``/``w:br`` (w skreśleniu ``w:delText``)."""

    out: list[etree._Element] = []
    for piece in re.split(r"(\t|\n)", text):
        if piece == "":
            continue
        if piece == "\t":
            out.append(_el("tab"))
        elif piece == "\n":
            out.append(_el("br"))
        else:
            t = _el("delText" if deleted else "t")
            t.set(f"{{{XML_NS}}}space", "preserve")
            t.text = piece
            out.append(t)
    return out


def _clean_rpr(rpr: etree._Element | None) -> etree._Element | None:
    if rpr is None:
        return None
    rpr = copy.deepcopy(rpr)
    for child in list(rpr):
        if child.tag in (w("rPrChange"), w("ins"), w("del")):
            rpr.remove(child)
    return rpr


def _new_run(text: str, rpr: etree._Element | None) -> etree._Element:
    run = _el("r")
    rpr = _clean_rpr(rpr)
    if rpr is not None:
        run.append(rpr)
    for child in _text_children(text):
        run.append(child)
    return run


def _tracked(tag: str, ids: _Ids, date: str) -> etree._Element:
    return _el(tag, id=ids.take(), author=AUTHOR, date=date)


# ── dzielenie przebiegów ────────────────────────────────────────────────────


def _split_run_before(run: etree._Element, child: etree._Element) -> etree._Element:
    """Przenosi ``child`` i wszystko po nim do nowego przebiegu tuż za ``run``."""

    new_run = etree.Element(run.tag)
    rpr = run.find(w("rPr"))
    if rpr is not None:
        new_run.append(copy.deepcopy(rpr))
    moving = []
    current = child
    while current is not None:
        moving.append(current)
        current = current.getnext()
    for el in moving:
        new_run.append(el)
    run.addnext(new_run)
    return new_run


def _split_at(p: etree._Element, offset: int, depth: int) -> None:
    """Granica przebiegów w miejscu ``offset`` tekstu akapitu."""

    segments, _, _ = paragraph_segments(p, depth)
    for seg in segments:
        if seg.start < offset < seg.end:
            if seg.locked:
                raise RedlineError("Zmiana przecina pole Worda.")
            k = offset - seg.start
            text = seg.child.text or ""
            second = _el("t")
            second.set(f"{{{XML_NS}}}space", "preserve")
            second.text = text[k:]
            seg.child.text = text[:k]
            seg.child.set(f"{{{XML_NS}}}space", "preserve")
            seg.child.addnext(second)
            _split_run_before(seg.run, second)
            return
    for left, right in zip(segments, segments[1:]):
        if left.end == offset and right.start == offset and left.run is right.run:
            if left.child is right.child:
                continue
            _split_run_before(left.run, right.child)
            return


def _runs_in_range(
    segments: list[Segment], start: int, end: int
) -> list[etree._Element]:
    runs: list[etree._Element] = []
    for seg in segments:
        if seg.end <= seg.start:
            continue
        if (
            seg.start >= start
            and seg.end <= end
            and (not runs or runs[-1] is not seg.run)
        ):
            runs.append(seg.run)
    return runs


def _groups(runs: list[etree._Element]) -> list[list[etree._Element]]:
    """Kolejne przebiegi rodzeństwa (bez nic pomiędzy) → jedna grupa ``w:del``."""

    groups: list[list[etree._Element]] = []
    for run in runs:
        if groups and groups[-1][-1].getnext() is run:
            groups[-1].append(run)
        else:
            groups.append([run])
    return groups


def _to_deleted(run: etree._Element) -> None:
    for el in run.iter(w("t"), w("instrText")):
        el.tag = w("delText") if el.tag == w("t") else w("delInstrText")
        el.set(f"{{{XML_NS}}}space", "preserve")


def _wrap_deleted(
    runs: list[etree._Element], ids: _Ids, date: str
) -> list[etree._Element]:
    wrappers = []
    for group in _groups(runs):
        wrapper = _tracked("del", ids, date)
        group[0].addprevious(wrapper)
        for run in group:
            _to_deleted(run)
            wrapper.append(run)
        wrappers.append(wrapper)
    return wrappers


def _outside_ins(el: etree._Element) -> etree._Element:
    """Element, obok którego wolno postawić nowe ``w:ins`` (nie wewnątrz ``w:ins``)."""

    current = el
    while current.getparent() is not None and current.getparent().tag in (
        w("ins"),
        w("moveTo"),
    ):
        current = current.getparent()
    return current


def _insert_point(
    p: etree._Element, offset: int, depth: int
) -> tuple[etree._Element | None, str, etree._Element | None]:
    """(sąsiad, ``after``/``before``/``append``, przebieg wzoru formatowania)."""

    segments, _, _ = paragraph_segments(p, depth)
    before_seg = None
    after_seg = None
    for seg in segments:
        if seg.end == offset and seg.end > seg.start:
            before_seg = seg
        if seg.start == offset and seg.end > seg.start and after_seg is None:
            after_seg = seg
        if seg.locked and seg.start < offset < seg.end:
            raise RedlineError("Wstawka wypada w środku pola Worda.")
    if before_seg is not None and not before_seg.locked:
        return _outside_ins(before_seg.run), "after", before_seg.run
    if after_seg is not None and not after_seg.locked:
        return _outside_ins(after_seg.run), "before", after_seg.run
    if before_seg is None and after_seg is None:
        return None, "append", None
    # Sąsiad to pole Worda: nie wiemy, gdzie pole się zaczyna i kończy wśród
    # przebiegów, więc wstawka mogłaby wpaść między jego kod a wynik.
    raise RedlineError("Wstawka przylega do pola Worda — wstaw ją ręcznie w Wordzie.")


def _place(
    new: etree._Element, anchor: etree._Element | None, where: str, p: etree._Element
) -> None:
    if where == "after" and anchor is not None:
        anchor.addnext(new)
    elif where == "before" and anchor is not None:
        anchor.addprevious(new)
    else:
        p.append(new)


# ── komentarze ──────────────────────────────────────────────────────────────


class _Comments:
    def __init__(self, pkg: DocxPackage, date: str) -> None:
        raw = pkg.parts.get(COMMENTS_PART)
        self.root = (
            parse_xml(raw) if raw else etree.Element(w("comments"), nsmap={"w": W_NS})
        )
        self.existed = raw is not None
        self.date = date
        self.used = False

    def add(self, comment_id: str, text: str) -> None:
        comment = _el(
            "comment",
            id=comment_id,
            author=AUTHOR,
            date=self.date,
            initials=AUTHOR_INITIALS,
        )
        for i, line in enumerate(text.split("\n")):
            para = _el("p")
            if i == 0:
                ref = _el("r")
                ref.append(_el("annotationRef"))
                para.append(ref)
            run = _el("r")
            for child in _text_children(line):
                run.append(child)
            para.append(run)
            comment.append(para)
        self.root.append(comment)
        self.used = True


def _mark_range(
    first: etree._Element,
    last: etree._Element,
    comment_id: str,
) -> None:
    start = _el("commentRangeStart", id=comment_id)
    end = _el("commentRangeEnd", id=comment_id)
    first.addprevious(start)
    last.addnext(end)
    ref_run = _el("r")
    ref_run.append(_el("commentReference", id=comment_id))
    end.addnext(ref_run)


def comment_text(change: RedlineChange) -> str:
    lines = []
    if change.reason.strip():
        lines.append(change.reason.strip())
    for source in change.sources:
        line = f"{source.label}: „{source.quote}”" if source.quote else source.label
        if source.url:
            line += f" ({source.url})"
        lines.append(line)
    return "\n".join(lines)


# ── zmiany ──────────────────────────────────────────────────────────────────


def _resolve_range(text: str, change: RedlineChange) -> RedlineChange:
    """Ustala ``[start, end)``: podane przesunięcia albo jedyne wystąpienie ``find``."""

    if change.start is not None:
        end = change.end if change.end is not None else change.start + len(change.find)
        if (
            0 <= change.start <= end <= len(text)
            and text[change.start : end] == change.find
        ):
            return dc_replace(change, end=end)
    if change.find:
        hits = [m.start() for m in re.finditer(re.escape(change.find), text)]
        if len(hits) == 1:
            return dc_replace(change, start=hits[0], end=hits[0] + len(change.find))
        if len(hits) > 1:
            raise RedlineError(
                f"Fragment „{_short(change.find)}” występuje w akapicie {len(hits)} razy — wskaż miejsce.",
                change_id=change.id,
            )
        raise RedlineError(
            f"W akapicie nie ma fragmentu „{_short(change.find)}” — dokument się zmienił?",
            change_id=change.id,
        )
    if change.start is None:
        return dc_replace(change, start=len(text), end=len(text))
    raise RedlineError("Miejsce wstawki wychodzi poza akapit.", change_id=change.id)


def _short(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def resolve_changes(
    paragraph_texts: list[str], changes: Iterable[RedlineChange]
) -> list[RedlineChange]:
    """Sprawdza kotwice wszystkich zmian i nakładanie się w akapicie."""

    resolved: list[RedlineChange] = []
    for change in changes:
        if not 0 <= change.paragraph < len(paragraph_texts):
            raise RedlineError(
                "Zmiana wskazuje akapit, którego w dokumencie nie ma.",
                change_id=change.id,
            )
        if change.kind == "replace":
            change = _resolve_range(paragraph_texts[change.paragraph], change)
            if change.start == change.end and not change.new_text:
                raise RedlineError(
                    "Pusta zmiana — nic do wstawienia ani skreślenia.",
                    change_id=change.id,
                )
        elif change.kind == "insert_paragraph" and not change.new_text.strip():
            raise RedlineError("Nowy akapit nie ma treści.", change_id=change.id)
        resolved.append(change)

    by_paragraph: dict[int, list[RedlineChange]] = defaultdict(list)
    for change in resolved:
        if change.kind != "insert_paragraph":
            by_paragraph[change.paragraph].append(change)
    for items in by_paragraph.values():
        if any(c.kind == "delete_paragraph" for c in items) and len(items) > 1:
            raise RedlineError(
                "Akapit jest skreślony w całości i ma jeszcze inną zmianę.",
                change_id=items[-1].id,
            )
        ordered = sorted(
            (c for c in items if c.kind == "replace"), key=lambda c: (c.start, c.end)
        )
        for prev, nxt in zip(ordered, ordered[1:]):
            if nxt.start < prev.end or nxt.start == prev.start:
                raise RedlineError(
                    "Dwie zmiany nachodzą na ten sam fragment.", change_id=nxt.id
                )
    return resolved


def _set_mark(p: etree._Element, tag: str, ids: _Ids, date: str) -> None:
    """Znak akapitu wstawiony/skreślony: ``w:pPr/w:rPr`` z ``w:ins``/``w:del`` na początku."""

    ppr = p.find(w("pPr"))
    if ppr is None:
        ppr = _el("pPr")
        p.insert(0, ppr)
    rpr = ppr.find(w("rPr"))
    if rpr is None:
        rpr = _el("rPr")
        tail = ppr.find(w("sectPr"))
        if tail is None:
            tail = ppr.find(w("pPrChange"))
        if tail is not None:
            tail.addprevious(rpr)
        else:
            ppr.append(rpr)
    rpr.insert(0, _tracked(tag, ids, date))


def _apply_replace(
    p: etree._Element,
    depth: int,
    change: RedlineChange,
    ids: _Ids,
    date: str,
    comments: _Comments,
) -> None:
    assert change.start is not None and change.end is not None
    touched: list[etree._Element] = []
    format_run: etree._Element | None = None
    try:
        if change.start < change.end:
            segments, _, _ = paragraph_segments(p, depth)
            if any(
                s.locked and s.start < change.end and s.end > change.start
                for s in segments
            ):
                raise RedlineError("Zmiana przecina pole Worda (np. numer strony).")
            _split_at(p, change.end, depth)
            _split_at(p, change.start, depth)
            segments, _, _ = paragraph_segments(p, depth)
            runs = _runs_in_range(segments, change.start, change.end)
            format_run = runs[0]
            touched = _wrap_deleted(runs, ids, date)
        if change.new_text:
            ins = _tracked("ins", ids, date)
            if touched:
                ins.append(_new_run(change.new_text, format_run.find(w("rPr"))))
                touched[-1].addnext(ins)
            else:
                _split_at(p, change.start, depth)
                anchor, where, model_run = _insert_point(p, change.start, depth)
                rpr = (
                    model_run.find(w("rPr"))
                    if model_run is not None
                    else _paragraph_mark_rpr(p)
                )
                ins.append(_new_run(change.new_text, rpr))
                _place(ins, anchor, where, p)
            touched.append(ins)
    except RedlineError as exc:
        raise RedlineError(str(exc), change_id=change.id) from exc
    _comment(change, touched[0], touched[-1], ids, comments)


def _paragraph_mark_rpr(p: etree._Element) -> etree._Element | None:
    rpr = p.find(f"{w('pPr')}/{w('rPr')}")
    if rpr is None:
        return None
    run_rpr = _el("rPr")
    for child in rpr:
        run_rpr.append(copy.deepcopy(child))
    return run_rpr


def _comment(
    change: RedlineChange,
    first: etree._Element,
    last: etree._Element,
    ids: _Ids,
    comments: _Comments,
) -> None:
    text = comment_text(change)
    if not text:
        return
    comment_id = ids.take()
    comments.add(comment_id, text)
    _mark_range(first, last, comment_id)


def _apply_delete_paragraph(
    p: etree._Element,
    depth: int,
    change: RedlineChange,
    ids: _Ids,
    date: str,
    comments: _Comments,
) -> None:
    segments, text, _ = paragraph_segments(p, depth)
    if any(s.locked for s in segments):
        raise RedlineError(
            "Akapit zawiera pole Worda — skreśl go ręcznie w Wordzie.",
            change_id=change.id,
        )
    runs = _runs_in_range(segments, 0, len(text))
    wrappers = _wrap_deleted(runs, ids, date) if runs else []
    nxt = p.getnext()
    if nxt is not None and nxt.tag == w("p"):
        _set_mark(p, "del", ids, date)
    if wrappers:
        _comment(change, wrappers[0], wrappers[-1], ids, comments)


def _template_paragraph(elements: list[etree._Element], index: int) -> etree._Element:
    """Wzór wyglądu nowego akapitu: kotwica, a gdy to nagłówek — następny akapit treści."""

    anchor = elements[index]
    style = anchor.find(f"{w('pPr')}/{w('pStyle')}")
    if style is not None and is_heading_style(style.get(w("val"))):
        for candidate in elements[index + 1 : index + 4]:
            cstyle = candidate.find(f"{w('pPr')}/{w('pStyle')}")
            if cstyle is None or not is_heading_style(cstyle.get(w("val"))):
                if candidate.getparent() is anchor.getparent():
                    return candidate
    return anchor


def _new_paragraph(
    template: etree._Element,
    change: RedlineChange,
    ids: _Ids,
    date: str,
    comments: _Comments,
) -> etree._Element:
    p = _el("p")
    ppr = template.find(w("pPr"))
    if ppr is not None:
        ppr = copy.deepcopy(ppr)
        for child in list(ppr):
            if child.tag in (w("sectPr"), w("pPrChange"), w("rPr")):
                ppr.remove(child)
        p.append(ppr)
    _set_mark(p, "ins", ids, date)
    model_run = next(
        (r for r in template.iter(w("r")) if r.find(w("t")) is not None), None
    )
    rpr = (
        model_run.find(w("rPr"))
        if model_run is not None
        else _paragraph_mark_rpr(template)
    )
    ins = _tracked("ins", ids, date)
    ins.append(_new_run(change.new_text, rpr))
    p.append(ins)
    _comment(change, ins, ins, ids, comments)
    return p


def apply_changes(
    data: bytes, changes: list[RedlineChange], *, when: datetime
) -> bytes:
    """DOCX + zmiany → DOCX ze śledzeniem zmian i komentarzami."""

    pkg = load_package(data)
    body = pkg.body
    elements = paragraph_elements(body)
    depths: list[int] = []
    texts: list[str] = []
    depth = 0
    for p in elements:
        depths.append(depth)
        _, text, depth = paragraph_segments(p, depth)
        texts.append(text)

    resolved = resolve_changes(texts, changes)
    date = format_word_date(when)
    comments = _Comments(pkg, date)
    ids = _Ids(_max_id(pkg.document, comments.root) + 1)

    inline = sorted(
        (c for c in resolved if c.kind == "replace"),
        key=lambda c: (c.paragraph, c.start),
        reverse=True,
    )
    for change in inline:
        _apply_replace(
            elements[change.paragraph],
            depths[change.paragraph],
            change,
            ids,
            date,
            comments,
        )
    for change in resolved:
        if change.kind == "delete_paragraph":
            _apply_delete_paragraph(
                elements[change.paragraph],
                depths[change.paragraph],
                change,
                ids,
                date,
                comments,
            )
    last_after: dict[int, etree._Element] = {}
    for change in resolved:
        if change.kind != "insert_paragraph":
            continue
        new_p = _new_paragraph(
            _template_paragraph(elements, change.paragraph), change, ids, date, comments
        )
        anchor = elements[change.paragraph]
        if change.before:
            anchor.addprevious(new_p)
        else:
            last_after.get(change.paragraph, anchor).addnext(new_p)
            last_after[change.paragraph] = new_p

    replaced = {DOCUMENT_PART: serialize_xml(pkg.document)}
    if comments.used:
        replaced[COMMENTS_PART] = serialize_xml(comments.root)
        if not comments.existed:
            replaced.update(_register_comments_part(pkg))
    return write_package(pkg, replaced)


def _register_comments_part(pkg: DocxPackage) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    types = parse_xml(pkg.parts[CONTENT_TYPES_PART])
    if not any(
        o.get("PartName") == "/" + COMMENTS_PART
        for o in types.iter(f"{{{CT_NS}}}Override")
    ):
        override = etree.SubElement(types, f"{{{CT_NS}}}Override")
        override.set("PartName", "/" + COMMENTS_PART)
        override.set("ContentType", COMMENTS_CONTENT_TYPE)
        out[CONTENT_TYPES_PART] = serialize_xml(types)

    raw_rels = pkg.parts.get(DOC_RELS_PART)
    rels = (
        parse_xml(raw_rels)
        if raw_rels
        else etree.Element(f"{{{REL_NS}}}Relationships", nsmap={None: REL_NS})
    )
    existing = list(rels.iter(f"{{{REL_NS}}}Relationship"))
    if not any(r.get("Type") == COMMENTS_REL_TYPE for r in existing):
        taken = {r.get("Id") for r in existing}
        n = len(existing) + 1
        while f"rId{n}" in taken:
            n += 1
        rel = etree.SubElement(rels, f"{{{REL_NS}}}Relationship")
        rel.set("Id", f"rId{n}")
        rel.set("Type", COMMENTS_REL_TYPE)
        rel.set("Target", "comments.xml")
        out[DOC_RELS_PART] = serialize_xml(rels)
    return out
