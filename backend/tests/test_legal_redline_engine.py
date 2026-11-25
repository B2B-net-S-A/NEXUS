"""Silnik „Popraw dokument”: DOCX ze śledzeniem zmian i komentarzami.

Dokumenty są fikcyjne (budowane w teście albo wzory z ``app/templates/contract``
bez wypełnienia). Plik wynikowy musi się otworzyć w ``python-docx``, a gdy na
maszynie jest LibreOffice — przejść konwersję do PDF bez błędu.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

import docx
import pytest
from lxml import etree

from app.services.legal_redline.diff import diff_texts
from app.services.legal_redline.docx_io import load_package, paragraph_elements, read_paragraphs
from app.services.legal_redline.model import (
    AUTHOR,
    ChangeSource,
    NotADocxError,
    RedlineChange,
    RedlineError,
)
from app.services.legal_redline.tracked import apply_changes

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WHEN = datetime(2026, 11, 25, 12, 30)
TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "templates" / "contract"


def _sample_docx() -> bytes:
    d = docx.Document()
    d.add_heading("§ 1 Przedmiot umowy", level=1)
    p = d.add_paragraph()
    p.add_run("Partner świadczy usługi ")
    bold = p.add_run("programistyczne")
    bold.bold = True
    p.add_run(" na rzecz Zamawiającego przez 30 dni.")
    d.add_paragraph("Wynagrodzenie płatne w terminie 14 dni od doręczenia faktury.")
    table = d.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Stawka"
    table.cell(0, 1).text = "Zgodnie z załącznikiem nr 1"
    d.add_paragraph("Zażółć gęślą jaźń — ostatni akapit.")
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


def _document_xml(data: bytes) -> etree._Element:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return etree.fromstring(z.read("word/document.xml"))


def _accepted_text(data: bytes) -> list[str]:
    """Tekst po „Przyjmij wszystkie”: w:t bez skreśleń (python-docx pomija w:ins)."""
    root = _document_xml(data)
    out = []
    for p in root.iter(f"{W}p"):
        out.append("".join(t.text or "" for t in p.iter(f"{W}t")))
    return out


def _rejected_text(data: bytes) -> list[str]:
    root = _document_xml(data)
    out = []
    for p in root.iter(f"{W}p"):
        mark = p.find(f"{W}pPr/{W}rPr/{W}ins")
        if mark is not None:
            continue
        parts = []
        for el in p.iter(f"{W}t", f"{W}delText"):
            inside_ins = any(a.tag == f"{W}ins" for a in el.iterancestors())
            if not inside_ins:
                parts.append(el.text or "")
        out.append("".join(parts))
    return out


def _paragraph(data: bytes, startswith: str) -> int:
    for para in read_paragraphs(load_package(data)):
        if para.text.startswith(startswith):
            return para.index
    raise AssertionError(startswith)


def _soffice() -> str | None:
    found = shutil.which("soffice")
    mac = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    return found or (mac if Path(mac).exists() else None)


def _assert_opens(data: bytes, tmp_path: Path) -> None:
    docx.Document(io.BytesIO(data))
    soffice = _soffice()
    if soffice is None:
        return
    src = tmp_path / "wynik.docx"
    src.write_bytes(data)
    subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(tmp_path), str(src)],
        check=True,
        capture_output=True,
        timeout=120,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert (tmp_path / "wynik.pdf").stat().st_size > 1000


def test_reads_paragraphs_with_table_and_polish_letters():
    paragraphs = read_paragraphs(load_package(_sample_docx()))
    texts = [p.text for p in paragraphs]
    assert "§ 1 Przedmiot umowy" in texts
    assert "Partner świadczy usługi programistyczne na rzecz Zamawiającego przez 30 dni." in texts
    assert "Zgodnie z załącznikiem nr 1" in texts
    table_rows = [p for p in paragraphs if p.in_table]
    assert [p.text for p in table_rows] == ["Stawka", "Zgodnie z załącznikiem nr 1"]
    assert paragraphs[0].heading is True


def test_insert_in_middle_of_paragraph_keeps_run_format(tmp_path):
    data = _sample_docx()
    idx = _paragraph(data, "Partner")
    text = read_paragraphs(load_package(data))[idx].text
    pos = text.index("programistyczne") + len("programi")
    change = RedlineChange(id="c1", kind="replace", paragraph=idx, start=pos, end=pos, new_text="[WSTAWKA]")
    out = apply_changes(data, [change], when=WHEN)
    accepted = _accepted_text(out)
    assert "Partner świadczy usługi programi[WSTAWKA]styczne na rzecz Zamawiającego przez 30 dni." in accepted
    root = _document_xml(out)
    ins = root.find(f".//{W}ins")
    assert ins.get(f"{W}author") == AUTHOR
    assert ins.get(f"{W}date") == "2026-11-25T12:30:00Z"
    # Wstawka w pogrubionym słowie jest pogrubiona.
    assert ins.find(f"{W}r/{W}rPr/{W}b") is not None
    _assert_opens(out, tmp_path)


def test_delete_across_run_boundary_moves_text_to_deltext(tmp_path):
    data = _sample_docx()
    idx = _paragraph(data, "Partner")
    change = RedlineChange(
        id="c1", kind="replace", paragraph=idx, find="usługi programistyczne na", new_text="prace na"
    )
    out = apply_changes(data, [change], when=WHEN)
    accepted = _accepted_text(out)
    rejected = _rejected_text(out)
    assert "Partner świadczy prace na rzecz Zamawiającego przez 30 dni." in accepted
    assert "Partner świadczy usługi programistyczne na rzecz Zamawiającego przez 30 dni." in rejected
    root = _document_xml(out)
    deleted = "".join(t.text for t in root.iter(f"{W}delText"))
    assert deleted == "usługi programistyczne na"
    # Skreślenie przechodzi przez trzy przebiegi (zwykły, pogrubiony, zwykły) —
    # pogrubienie zostaje w skreślonym przebiegu.
    bold_deleted = [
        r for r in root.iter(f"{W}r")
        if r.find(f"{W}delText") is not None and r.find(f"{W}rPr/{W}b") is not None
    ]
    assert len(bold_deleted) == 1
    _assert_opens(out, tmp_path)


def test_comment_with_sources_lands_in_comments_part(tmp_path):
    data = _sample_docx()
    idx = _paragraph(data, "Wynagrodzenie")
    change = RedlineChange(
        id="c1",
        kind="replace",
        paragraph=idx,
        find="14 dni",
        new_text="30 dni",
        reason="Termin zapłaty jak w umowie ramowej klienta.",
        sources=(ChangeSource(ref="msa", label="Umowa ramowa — pkt 5", quote="w terminie 30 dni", kind="client"),),
    )
    out = apply_changes(data, [change], when=WHEN)
    with zipfile.ZipFile(io.BytesIO(out)) as z:
        names = z.namelist()
        comments = etree.fromstring(z.read("word/comments.xml"))
        types = z.read("[Content_Types].xml").decode()
        rels = z.read("word/_rels/document.xml.rels").decode()
    assert "word/comments.xml" in names
    assert "comments+xml" in types
    assert "relationships/comments" in rels
    comment = comments.find(f"{W}comment")
    body = "\n".join("".join(t.text for t in p.iter(f"{W}t")) for p in comment.iter(f"{W}p"))
    assert "Termin zapłaty jak w umowie ramowej klienta." in body
    assert "Umowa ramowa — pkt 5: „w terminie 30 dni”" in body
    root = _document_xml(out)
    cid = comment.get(f"{W}id")
    assert root.find(f".//{W}commentRangeStart[@{W}id='{cid}']") is not None
    assert root.find(f".//{W}commentRangeEnd[@{W}id='{cid}']") is not None
    assert root.find(f".//{W}commentReference[@{W}id='{cid}']") is not None
    # Komentarz ma inny w:id niż zmiany (jeden licznik).
    ids = [el.get(f"{W}id") for el in root.iter(f"{W}ins", f"{W}del")]
    assert cid not in ids and len(set(ids)) == len(ids)
    _assert_opens(out, tmp_path)


def test_change_in_table_cell(tmp_path):
    data = _sample_docx()
    idx = _paragraph(data, "Zgodnie")
    change = RedlineChange(id="c1", kind="replace", paragraph=idx, find="nr 1", new_text="nr 2")
    out = apply_changes(data, [change], when=WHEN)
    root = _document_xml(out)
    cell = root.find(f".//{W}tbl")
    assert "".join(t.text for t in cell.iter(f"{W}t")) == "StawkaZgodnie z załącznikiem nr 2"
    assert "".join(t.text for t in cell.iter(f"{W}delText")) == "nr 1"
    _assert_opens(out, tmp_path)


def test_insert_and_delete_whole_paragraphs(tmp_path):
    data = _sample_docx()
    first = _paragraph(data, "§ 1")
    pay = _paragraph(data, "Wynagrodzenie")
    changes = [
        RedlineChange(id="n1", kind="insert_paragraph", paragraph=first, new_text="Nowy ustęp o szkoleniach z bezpieczeństwa."),
        RedlineChange(id="n2", kind="insert_paragraph", paragraph=first, new_text="Drugi nowy ustęp."),
        RedlineChange(id="x1", kind="delete_paragraph", paragraph=pay, find="Wynagrodzenie"),
    ]
    out = apply_changes(data, changes, when=WHEN)
    accepted = [t for t in _accepted_text(out) if t]
    assert accepted.index("Nowy ustęp o szkoleniach z bezpieczeństwa.") + 1 == accepted.index("Drugi nowy ustęp.")
    assert accepted.index("§ 1 Przedmiot umowy") + 1 == accepted.index("Nowy ustęp o szkoleniach z bezpieczeństwa.")
    root = _document_xml(out)
    # Nowy akapit po nagłówku bierze wygląd akapitu treści, nie nagłówka.
    new_p = [p for p in root.iter(f"{W}p") if "Drugi nowy" in "".join(t.text or "" for t in p.iter(f"{W}t"))][0]
    style = new_p.find(f"{W}pPr/{W}pStyle")
    assert style is None or not style.get(f"{W}val").lower().startswith("heading")
    assert new_p.find(f"{W}pPr/{W}rPr/{W}ins") is not None
    assert "Wynagrodzenie płatne w terminie 14 dni od doręczenia faktury." in _rejected_text(out)
    _assert_opens(out, tmp_path)


def test_anchor_mismatch_names_the_change():
    data = _sample_docx()
    idx = _paragraph(data, "Partner")
    with pytest.raises(RedlineError) as exc:
        apply_changes(data, [RedlineChange(id="c9", kind="replace", paragraph=idx, find="nie ma mnie", new_text="x")], when=WHEN)
    assert exc.value.change_id == "c9"


def test_ambiguous_fragment_is_refused():
    data = _sample_docx()
    idx = _paragraph(data, "Partner")
    with pytest.raises(RedlineError, match="razy"):
        apply_changes(data, [RedlineChange(id="c1", kind="replace", paragraph=idx, find="a", new_text="b")], when=WHEN)


def test_overlapping_changes_are_refused():
    data = _sample_docx()
    idx = _paragraph(data, "Partner")
    changes = [
        RedlineChange(id="a", kind="replace", paragraph=idx, find="usługi programistyczne", new_text="x"),
        RedlineChange(id="b", kind="replace", paragraph=idx, find="programistyczne na", new_text="y"),
    ]
    with pytest.raises(RedlineError, match="nachodzą"):
        apply_changes(data, changes, when=WHEN)


def test_not_a_docx():
    with pytest.raises(NotADocxError):
        load_package(b"%PDF-1.7 nie docx")


def _with_field() -> bytes:
    """Akapit z polem PAGE (fldChar) — numer strony w treści."""
    d = docx.Document()
    p = d.add_paragraph("Strona ")
    for kind, extra in (("begin", None), (None, " PAGE "), ("separate", None), (None, "1"), ("end", None)):
        run = p.add_run()
        r = run._r
        if kind:
            fld = etree.SubElement(r, f"{W}fldChar")
            fld.set(f"{W}fldCharType", kind)
        elif extra == " PAGE ":
            instr = etree.SubElement(r, f"{W}instrText")
            instr.text = extra
        else:
            run.text = extra
    p.add_run(" z umowy.")
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


def test_field_is_untouchable_but_text_beside_it_changes(tmp_path):
    data = _with_field()
    paragraphs = read_paragraphs(load_package(data))
    assert paragraphs[0].text == "Strona 1 z umowy."
    with pytest.raises(RedlineError, match="pol"):
        apply_changes(data, [RedlineChange(id="f", kind="replace", paragraph=0, find="1 z", new_text="2 z")], when=WHEN)
    out = apply_changes(
        data, [RedlineChange(id="ok", kind="replace", paragraph=0, find="umowy", new_text="aneksu")], when=WHEN
    )
    root = _document_xml(out)
    assert root.find(f".//{W}instrText").text == " PAGE "
    _assert_opens(out, tmp_path)


@pytest.mark.parametrize("name", ["umowa_b2b_pl.docx", "umowa_b2b_en.docx", "umowa_zlecenie_pl.docx"])
def test_our_templates_with_numbering_and_tables(name, tmp_path):
    data = (TEMPLATES / name).read_bytes()
    paragraphs = read_paragraphs(load_package(data))
    body = [p for p in paragraphs if len(p.text) > 40 and not p.in_table]
    target = body[len(body) // 2]
    word = target.text.split()[2]
    change = RedlineChange(
        id="t1",
        kind="replace",
        paragraph=target.index,
        start=target.text.index(word),
        end=target.text.index(word) + len(word),
        find=word,
        new_text=word + " (zmienione)",
        reason="Fikcyjna zmiana testowa.",
    )
    add = RedlineChange(id="t2", kind="insert_paragraph", paragraph=target.index, new_text="Akapit dodany w teście.")
    out = apply_changes(data, [change, add], when=WHEN)
    reread = read_paragraphs(load_package(out))
    assert any("Akapit dodany w teście." == p.text for p in reread)
    # Numeracja nowego akapitu = numeracja akapitu-kotwicy.
    root = _document_xml(out)
    new_p = [p for p in root.iter(f"{W}p") if "".join(t.text or "" for t in p.iter(f"{W}t")) == "Akapit dodany w teście."][0]
    anchor = paragraph_elements(load_package(data).body)[target.index]
    assert (new_p.find(f"{W}pPr/{W}numPr") is None) == (anchor.find(f"{W}pPr/{W}numPr") is None)
    _assert_opens(out, tmp_path)


def test_diff_two_versions_to_changes(tmp_path):
    data = _sample_docx()
    old = [p.text for p in read_paragraphs(load_package(data))]
    new = list(old)
    pay = old.index("Wynagrodzenie płatne w terminie 14 dni od doręczenia faktury.")
    new[pay] = "Wynagrodzenie płatne w terminie 30 dni od doręczenia prawidłowej faktury."
    new.insert(pay + 1, "Faktura w formie elektronicznej.")
    del new[old.index("Zażółć gęślą jaźń — ostatni akapit.") + 1]
    changes = diff_texts(old, "\n".join(new))
    kinds = sorted(c.kind for c in changes)
    assert kinds.count("insert_paragraph") == 1
    assert kinds.count("delete_paragraph") == 1
    inline = [c for c in changes if c.kind == "replace"]
    assert {(c.find, c.new_text) for c in inline} == {("14", "30"), ("", "prawidłowej ")}
    out = apply_changes(data, changes, when=WHEN)
    accepted = [t for t in _accepted_text(out) if t]
    assert "Wynagrodzenie płatne w terminie 30 dni od doręczenia prawidłowej faktury." in accepted
    assert "Faktura w formie elektronicznej." in accepted
    assert "Zażółć gęślą jaźń — ostatni akapit." not in accepted
    _assert_opens(out, tmp_path)


def test_diff_without_changes_is_empty():
    old = ["A b c.", "D e."]
    assert diff_texts(old, "A b c.\nD e.") == []


def test_new_paragraph_keeps_paragraph_mark_format_for_numbering():
    """Numer listy Word bierze z formatu znaku akapitu — nowy ustęp nie może go zgubić."""
    data = (TEMPLATES / "umowa_b2b_pl.docx").read_bytes()
    elements = paragraph_elements(load_package(data).body)
    anchor_index = next(
        i
        for i, p in enumerate(elements)
        if p.find(f"{W}pPr/{W}numPr") is not None and p.find(f"{W}pPr/{W}rPr") is not None
    )
    anchor_rpr = elements[anchor_index].find(f"{W}pPr/{W}rPr")
    out = apply_changes(
        data,
        [RedlineChange(id="n", kind="insert_paragraph", paragraph=anchor_index, new_text="Nowy ustęp.")],
        when=WHEN,
    )
    root = _document_xml(out)
    new_p = [p for p in root.iter(f"{W}p") if "".join(t.text or "" for t in p.iter(f"{W}t")) == "Nowy ustęp."][0]
    rpr = new_p.find(f"{W}pPr/{W}rPr")
    assert rpr[0].tag == f"{W}ins"
    kept = {c.tag for c in rpr[1:]}
    assert kept == {c.tag for c in anchor_rpr if c.tag not in (f"{W}ins", f"{W}del", f"{W}rPrChange")}


def test_diff_keeps_line_breaks_inside_a_paragraph():
    """`w:br` w akapicie (np. „§ 2 ⏎ Definicje”) nie może rozbić porównania wierszami."""
    old = ["§ 2 \nDefinicje", "Termin wynosi 14 dni.", "Podpisy:\n\nB2BNET\tPartner"]
    sent = "\n".join(p.replace("\n", " ") for p in old).replace("14 dni", "21 dni")
    changes = diff_texts(old, sent)
    assert [(c.kind, c.paragraph, c.find, c.new_text) for c in changes] == [("replace", 1, "14", "21")]
