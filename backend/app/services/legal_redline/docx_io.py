"""Odczyt pakietu DOCX: części ZIP, ``document.xml`` i tekst akapitów.

Akapit to każdy ``w:p`` treści (także w komórkach tabel) poza polami
tekstowymi (``w:txbxContent``) i zapasową kopią kształtów (``mc:Fallback``).
Tekst akapitu = to, co widać w Wordzie: ``w:t``, tabulator jako ``\\t``,
złamanie wiersza jako ``\\n``; bez istniejących skreśleń i bez kodów pól.

Przebiegi w polu Worda (``w:fldChar`` … ``end`` albo ``w:fldSimple``) są
„zablokowane”: ich tekst liczy się do akapitu, ale zmiana nie może ich
przeciąć — rozcięte pole Word naprawia przy otwarciu.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

from lxml import etree

from app.services.legal_redline.model import NotADocxError, Paragraph

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
XML_NS = "http://www.w3.org/XML/1998/namespace"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

DOCUMENT_PART = "word/document.xml"
MAX_PACKAGE_BYTES = 20 * 1024 * 1024
MAX_PART_BYTES = 40 * 1024 * 1024

_PARSER = etree.XMLParser(
    resolve_entities=False, no_network=True, remove_blank_text=False, huge_tree=False
)


def w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


_SKIP_ANCESTORS = {w("txbxContent"), f"{{{MC_NS}}}Fallback"}
# Przebieg w tych kontenerach nie jest widocznym tekstem (istniejące skreślenia).
_HIDDEN_CONTAINERS = {w("del"), w("moveFrom")}
_HEADING_PREFIXES = ("heading", "nagwek", "nagłówek", "tytu", "title")


@dataclass
class DocxPackage:
    """Części pakietu w kolejności z archiwum; ``document`` to drzewo ``document.xml``."""

    names: list[str]
    parts: dict[str, bytes]
    infos: dict[str, zipfile.ZipInfo]
    document: etree._Element

    @property
    def body(self) -> etree._Element:
        body = self.document.find(w("body"))
        if body is None:
            raise NotADocxError("Dokument Worda nie ma treści (brak w:body).")
        return body


def parse_xml(data: bytes) -> etree._Element:
    return etree.fromstring(data, _PARSER)


def serialize_xml(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def load_package(data: bytes) -> DocxPackage:
    """Otwiera DOCX; zły albo za duży plik → ``NotADocxError`` z polskim zdaniem."""

    if len(data) > MAX_PACKAGE_BYTES:
        raise NotADocxError("Plik jest za duży (najwyżej 20 MB).")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise NotADocxError("To nie jest plik Worda (DOCX).") from exc
    with archive:
        infos = archive.infolist()
        if DOCUMENT_PART not in {i.filename for i in infos}:
            raise NotADocxError(
                "To nie jest plik Worda (DOCX): brak word/document.xml."
            )
        if sum(i.file_size for i in infos) > MAX_PART_BYTES * 3:
            raise NotADocxError("Plik po rozpakowaniu jest za duży.")
        parts: dict[str, bytes] = {}
        for info in infos:
            if info.file_size > MAX_PART_BYTES:
                raise NotADocxError("Część pliku Worda jest za duża.")
            parts[info.filename] = archive.read(info.filename)
    try:
        document = parse_xml(parts[DOCUMENT_PART])
    except etree.XMLSyntaxError as exc:
        raise NotADocxError("Plik Worda jest uszkodzony (document.xml).") from exc
    return DocxPackage(
        names=[i.filename for i in infos],
        parts=parts,
        infos={i.filename: i for i in infos},
        document=document,
    )


def write_package(pkg: DocxPackage, replaced: dict[str, bytes]) -> bytes:
    """Zapisuje pakiet: te same części w tej samej kolejności, podmienione i nowe."""

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        written: set[str] = set()
        for name in pkg.names:
            info = pkg.infos[name]
            content = replaced.get(name, pkg.parts[name])
            new_info = zipfile.ZipInfo(name, date_time=info.date_time)
            new_info.compress_type = zipfile.ZIP_DEFLATED
            new_info.external_attr = info.external_attr
            archive.writestr(new_info, content)
            written.add(name)
        for name, content in replaced.items():
            if name not in written:
                archive.writestr(name, content)
    return out.getvalue()


# ── akapity ─────────────────────────────────────────────────────────────────


def _skipped(el: etree._Element, stop: etree._Element) -> bool:
    parent = el.getparent()
    while parent is not None and parent is not stop:
        if parent.tag in _SKIP_ANCESTORS:
            return True
        parent = parent.getparent()
    return False


def paragraph_elements(body: etree._Element) -> list[etree._Element]:
    """Akapity treści w kolejności dokumentu (z tabelami, bez pól tekstowych)."""

    return [p for p in body.iter(w("p")) if not _skipped(p, body)]


def _style_of(p: etree._Element) -> str | None:
    style = p.find(f"{w('pPr')}/{w('pStyle')}")
    return style.get(w("val")) if style is not None else None


def is_heading_style(style: str | None) -> bool:
    return bool(style) and style.lower().startswith(_HEADING_PREFIXES)


def _in_table(p: etree._Element) -> bool:
    parent = p.getparent()
    while parent is not None:
        if parent.tag == w("tc"):
            return True
        parent = parent.getparent()
    return False


@dataclass
class Segment:
    """Kawałek tekstu akapitu w jednym dziecku przebiegu (``w:t``, ``w:tab``…)."""

    run: etree._Element
    child: etree._Element
    start: int
    end: int
    locked: bool


_CHAR_CHILDREN = {
    w("tab"): "\t",
    w("br"): "\n",
    w("cr"): "\n",
    w("noBreakHyphen"): "‑",
    w("softHyphen"): "",
}


def _own_runs(p: etree._Element) -> list[etree._Element]:
    """Przebiegi akapitu ``p`` (bez przebiegów zagnieżdżonych akapitów i skreśleń)."""

    runs = []
    for r in p.iter(w("r")):
        parent = r.getparent()
        hidden = False
        while parent is not None and parent is not p:
            if parent.tag == w("p") or parent.tag in _HIDDEN_CONTAINERS:
                hidden = True
                break
            parent = parent.getparent()
        if not hidden:
            runs.append(r)
    return runs


def _in_simple_field(r: etree._Element, p: etree._Element) -> bool:
    parent = r.getparent()
    while parent is not None and parent is not p:
        if parent.tag == w("fldSimple"):
            return True
        parent = parent.getparent()
    return False


def paragraph_segments(
    p: etree._Element, field_depth: int = 0
) -> tuple[list[Segment], str, int]:
    """Mapa znaków akapitu → (przebieg, dziecko); zwraca też głębokość pola na końcu."""

    segments: list[Segment] = []
    parts: list[str] = []
    pos = 0
    depth = field_depth
    for r in _own_runs(p):
        simple = _in_simple_field(r, p)
        for child in r:
            tag = child.tag
            if tag == w("fldChar"):
                kind = child.get(w("fldCharType"))
                if kind == "begin":
                    depth += 1
                elif kind == "end":
                    depth = max(0, depth - 1)
                continue
            if tag == w("t"):
                text = child.text or ""
            elif tag in _CHAR_CHILDREN:
                text = _CHAR_CHILDREN[tag]
            else:
                continue
            locked = simple or depth > 0
            segments.append(Segment(r, child, pos, pos + len(text), locked))
            parts.append(text)
            pos += len(text)
        # Przebieg z samym fldChar/instrText też jest w polu — zaznaczamy go,
        # żeby wstawka między ``begin`` a ``end`` była odrzucona.
        if depth > 0 or simple:
            if not segments or segments[-1].run is not r:
                segments.append(Segment(r, r, pos, pos, True))
    return segments, "".join(parts), depth


def read_paragraphs(pkg: DocxPackage) -> list[Paragraph]:
    out: list[Paragraph] = []
    depth = 0
    for i, p in enumerate(paragraph_elements(pkg.body)):
        _, text, depth = paragraph_segments(p, depth)
        style = _style_of(p)
        out.append(
            Paragraph(
                index=i,
                text=text,
                style=style,
                in_table=_in_table(p),
                heading=is_heading_style(style),
            )
        )
    return out


def document_text(paragraphs: list[Paragraph]) -> str:
    return "\n".join(p.text for p in paragraphs)
