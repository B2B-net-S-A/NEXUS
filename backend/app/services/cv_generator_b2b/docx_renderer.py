"""DOCX renderer — 1:1 port of `lib/generate_cv.py` from artur-t-96/CV-Generator.

Renders a B2B Network-branded CV from a structured candidate dict + the
shared template `szablon_firmowy.docx`. Supports PL/EN, blind anonymization
and MUST-HAVE keyword bolding.

The candidate dict shape matches what Claude returns from the extraction
prompt — see :mod:`app.services.cv_generator_b2b.prompts`.

Public entrypoint: :func:`render_cv_to_bytes`.
"""

from __future__ import annotations

import io
import logging
import re
from typing import Any

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from lxml import etree

logger = logging.getLogger(__name__)


COLOR_HEADER = RGBColor(225, 79, 79)
COLOR_TEXT = RGBColor(55, 53, 53)

NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


_STOP_WORDS = {
    # Polski
    "w",
    "i",
    "o",
    "z",
    "do",
    "na",
    "dla",
    "od",
    "po",
    "we",
    "ze",
    "lub",
    "oraz",
    "jako",
    "przy",
    "przez",
    "pod",
    "nad",
    "przed",
    "sie",
    "to",
    "jest",
    "sa",
    "byl",
    "byla",
    "byly",
    "nie",
    "tak",
    # Angielski
    "a",
    "an",
    "the",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "and",
    "or",
    "with",
    "by",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
}


def should_highlight(word: str, keywords: list[str] | None) -> bool:
    """True iff `word` should be bolded as a MUST-HAVE keyword match."""
    if not keywords:
        return False

    word_clean = word.lower().strip(".,;:()[]/\"'")
    if not word_clean:
        return False

    if word_clean in _STOP_WORDS:
        return False

    for kw in keywords:
        kw_lower = kw.lower().strip()
        if kw_lower == word_clean or kw_lower in word_clean:
            return True
    return False


def add_text_with_highlights(
    para: Any,
    text: str,
    keywords: list[str] | None,
    base_font_size: Pt = Pt(10),
) -> None:
    """Add `text` to `para`, bolding tokens that match `keywords`."""
    if not keywords or not text:
        run = para.add_run(text)
        run.font.name = "Montserrat"
        run.font.color.rgb = COLOR_TEXT
        run.font.size = base_font_size
        return

    tokens = re.split(r"(\s+|[,;:/])", text)

    for token in tokens:
        if not token:
            continue
        run = para.add_run(token)
        run.font.name = "Montserrat"
        run.font.color.rgb = COLOR_TEXT
        run.font.size = base_font_size

        if should_highlight(token, keywords):
            run.font.bold = True


TRANSLATIONS = {
    "pl": {
        "why": "DLACZEGO NASZ KANDYDAT?",
        "education": "EDUKACJA",
        "dates": "Daty",
        "education_header": "Nazwa uczelni/kierunek",
        "skills": "UMIEJĘTNOŚCI",
        "certifications": "CERTYFIKATY",
        "languages": "JĘZYKI",
        "experience": "DOŚWIADCZENIE",
        "company_name": "Nazwa firmy:",
        "position": "Stanowisko:",
        "responsibilities": "Zakres zadań:",
        "technologies": "Technologie:",
        "rodo": (
            "Wyrażam zgodę na przetwarzanie moich danych osobowych zawartych w przekazanych "
            "przeze mnie dokumentach przez B2B.net S.A. w celach związanych z moim udziałem "
            "w niniejszym procesie rekrutacyjnym. Ponadto przyjmuję do wiadomości i oświadczam, "
            "że zrozumiałem/am, iż administratorem moich danych osobowych zebranych na podstawie "
            "niniejszej zgody jest B2B.net S.A. z siedzibą w Warszawie, Al. Jerozolimskie 180, "
            "02-486 Warszawa. Dane będą przetwarzane zgodnie z przepisami Rozporządzenia Parlamentu "
            "Europejskiego i Rady (UE) 2016/679 z dnia 27 kwietnia 2016 r. w sprawie ochrony osób "
            "fizycznych w związku z przetwarzaniem danych osobowych i w sprawie swobodnego przepływu "
            'takich danych (dalej „RODO"). Dane przekazałem/am dobrowolnie, przy czym przysługuje mi '
            "prawo do cofnięcia zgody na przetwarzanie danych w dowolnym momencie poprzez wysłanie "
            "żądania na adres: rekrutacja@b2bnetwork.pl. Podanie danych jest niezbędne do realizacji "
            "ww. celu, dlatego żądanie ich usunięcia jest równoznaczne z rezygnacją z dalszego udziału "
            "w procesie rekrutacyjnym. Przysługuje mi również prawo dostępu do treści moich danych oraz "
            "ich poprawiania w każdym czasie. Jestem również świadomy/świadoma, że odbiorcami moich danych "
            "osobowych mogą być wyłącznie podmioty upoważnione na podstawie przepisów prawa, a także "
            "upoważnione na podstawie umów zawartych przez B2B.net S.A., w szczególności z klientami."
        ),
    },
    "en": {
        "why": "WHY OUR CANDIDATE?",
        "education": "EDUCATION",
        "dates": "Dates",
        "education_header": "Names of University/degrees",
        "skills": "SKILLS",
        "certifications": "CERTIFICATIONS",
        "languages": "LANGUAGES",
        "experience": "EXPERIENCE",
        "company_name": "Company:",
        "position": "Position:",
        "responsibilities": "Tasks:",
        "technologies": "Technologies:",
        "rodo": (
            "I hereby consent to the processing of my personal data contained in the documents "
            "submitted by me by B2B.net S.A. for purposes related to my participation in this "
            "recruitment process. Furthermore, I acknowledge and declare that I have understood "
            "that the administrator of my personal data collected on the basis of this consent is "
            "B2B.net S.A. with its registered office in Warsaw, Al. Jerozolimskie 180, 02-486 Warsaw. "
            "The data will be processed in accordance with the provisions of Regulation (EU) 2016/679 "
            "of the European Parliament and of the Council of 27 April 2016 on the protection of natural "
            "persons with regard to the processing of personal data and on the free movement of such data "
            '(hereinafter "GDPR"). I have provided the data voluntarily, and I have the right to withdraw '
            "my consent to data processing at any time by sending a request to: rekrutacja@b2bnetwork.pl. "
            "The provision of data is necessary for the realization of the above purpose, therefore requesting "
            "their deletion is tantamount to resignation from further participation in the recruitment process. "
            "I also have the right to access the content of my data and to correct them at any time. I am also "
            "aware that the recipients of my personal data may only be entities authorized under the law, as well "
            "as authorized under contracts concluded by B2B.net S.A., in particular with customers."
        ),
    },
}


def add_horizontal_line(doc: Any) -> Any:
    """Add the B2B branded red horizontal divider."""
    para = doc.add_paragraph()

    hr_xml = """
    <w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
         xmlns:v="urn:schemas-microsoft-com:vml"
         xmlns:o="urn:schemas-microsoft-com:office:office">
        <w:rPr><w:noProof/></w:rPr>
        <w:pict>
            <v:rect style="width:448.6pt;height:2pt" fillcolor="#e14f4f" stroked="f"
                    o:hr="t" o:hrstd="t" o:hrnoshade="t" o:hrpct="989" o:hralign="center"/>
        </w:pict>
    </w:r>
    """

    hr_element = parse_xml(hr_xml)
    para._element.append(hr_element)
    para.paragraph_format.space_before = Pt(4)
    para.paragraph_format.space_after = Pt(6)
    return para


def add_section_header(doc: Any, text: str) -> Any:
    """Add a section header with divider above and Montserrat SemiBold title."""
    add_horizontal_line(doc)

    para = doc.add_paragraph()
    run = para.add_run(text)
    run.font.name = "Montserrat SemiBold"
    run.font.color.rgb = COLOR_HEADER
    run.font.bold = False
    run.font.size = Pt(14)
    para.paragraph_format.space_before = Pt(2)
    para.paragraph_format.space_after = Pt(3)
    return para


def add_bullet_point(
    doc: Any,
    text: str,
    punctuation: str = "",
    highlight_keywords: list[str] | None = None,
) -> Any:
    """Add a Word numbered bullet point with optional keyword bolding."""
    text = text.rstrip(".,;")
    text = text + punctuation

    para = doc.add_paragraph()

    add_text_with_highlights(para, text, highlight_keywords, Pt(10))

    pPr = para._element.get_or_add_pPr()
    numPr = etree.Element(f"{{{NS_W}}}numPr")

    ilvl = etree.SubElement(numPr, f"{{{NS_W}}}ilvl")
    ilvl.set(f"{{{NS_W}}}val", "0")

    numId = etree.SubElement(numPr, f"{{{NS_W}}}numId")
    numId.set(f"{{{NS_W}}}val", "1")

    pPr.insert(0, numPr)

    para.paragraph_format.space_before = Pt(1)
    para.paragraph_format.space_after = Pt(1)
    para.paragraph_format.line_spacing = 1.5
    return para


def add_bullet_list(
    doc: Any,
    items: list[str],
    highlight_keywords: list[str] | None = None,
) -> None:
    """Add a bullet list with commas between items and a period at the end."""
    for i, item in enumerate(items):
        is_last = i == len(items) - 1
        punctuation = "." if is_last else ","
        add_bullet_point(doc, item, punctuation, highlight_keywords)


def render_cv_to_bytes(
    candidate_data: dict[str, Any],
    template_path: str,
) -> bytes:
    """Render the candidate dict into a DOCX and return its bytes.

    Args:
        candidate_data: Dict from Claude extraction. Required keys:
            ``name``, ``position``, ``why_points``, ``skills``, ``languages``,
            ``experience``. Optional: ``education``, ``certifications``,
            ``language`` ('pl' default), ``blind_cv`` (False default),
            ``highlight_keywords`` (list of MUST-HAVE technologies).
        template_path: Path to ``szablon_firmowy.docx``.

    Returns:
        bytes — the rendered DOCX file content.
    """
    language = candidate_data.get("language", "pl")
    blind_cv = candidate_data.get("blind_cv", False)
    t = TRANSLATIONS.get(language, TRANSLATIONS["pl"])

    if blind_cv:
        if language == "en":
            candidate_data["name"] = "Candidate"
            candidate_data["first_name"] = "Candidate"
        else:
            candidate_data["name"] = "Kandydat"
            candidate_data["first_name"] = "Kandydat"

        for job in candidate_data.get("experience", []):
            industry = job.get("industry", "IT")
            if language == "en":
                job["company"] = f"Company from {industry} industry"
            else:
                job["company"] = f"Firma z branży {industry}"

    logger.info(
        "[cv_generator_b2b] Rendering CV name=%s lang=%s blind=%s",
        candidate_data.get("name"),
        language,
        blind_cv,
    )

    doc = Document(template_path)

    for element in list(doc.element.body):
        if not element.tag.endswith("}sectPr"):
            doc.element.body.remove(element)

    # === NAGŁÓWEK GŁÓWNY ===
    header_para = doc.add_paragraph()
    if blind_cv:
        header_text = candidate_data["position"]
    else:
        header_text = f"{candidate_data['position']} – {candidate_data['name']}"
    header_run = header_para.add_run(header_text)
    header_run.font.name = "Montserrat SemiBold"
    header_run.font.color.rgb = COLOR_HEADER
    header_run.font.bold = False
    header_run.font.size = Pt(24)
    header_para.paragraph_format.space_after = Pt(6)
    header_para.paragraph_format.space_before = Pt(2)

    add_horizontal_line(doc)

    # === DLACZEGO [IMIĘ] / WHY [NAME] / PODSUMOWANIE ===
    para = doc.add_paragraph()
    if blind_cv:
        why_title = "Summary" if language == "en" else "Podsumowanie"
    else:
        why_title = t["why"]
    run = para.add_run(why_title)
    run.font.name = "Montserrat SemiBold"
    run.font.color.rgb = COLOR_HEADER
    run.font.bold = False
    run.font.size = Pt(14)
    para.paragraph_format.space_before = Pt(0)
    para.paragraph_format.space_after = Pt(3)

    highlight_keywords = candidate_data.get("highlight_keywords", [])

    add_bullet_list(doc, candidate_data.get("why_points", []), highlight_keywords)

    # === EDUKACJA / EDUCATION ===
    if candidate_data.get("education"):
        add_section_header(doc, t["education"])

        table = doc.add_table(rows=len(candidate_data["education"]) + 1, cols=2)
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        table.columns[0].width = Inches(1.8)
        table.columns[1].width = Inches(5.0)

        tbl = table._tbl
        tblPr = tbl.tblPr if tbl.tblPr is not None else OxmlElement("w:tblPr")

        tblBorders = OxmlElement("w:tblBorders")
        for border_name in ["top", "left", "bottom", "right", "insideH", "insideV"]:
            border = OxmlElement(f"w:{border_name}")
            border.set(qn("w:val"), "single")
            border.set(qn("w:sz"), "4")
            border.set(qn("w:color"), "CCCCCC")
            tblBorders.append(border)
        tblPr.append(tblBorders)

        tblCellMar = OxmlElement("w:tblCellMar")
        for margin_name in ["top", "bottom"]:
            margin = OxmlElement(f"w:{margin_name}")
            margin.set(qn("w:w"), "80")
            margin.set(qn("w:type"), "dxa")
            tblCellMar.append(margin)
        for margin_name in ["left", "right"]:
            margin = OxmlElement(f"w:{margin_name}")
            margin.set(qn("w:w"), "120")
            margin.set(qn("w:type"), "dxa")
            tblCellMar.append(margin)
        tblPr.append(tblCellMar)

        header_cells = table.rows[0].cells
        header_cells[0].text = t["dates"]
        header_cells[1].text = t["education_header"]

        for cell in header_cells:
            shading_elm = OxmlElement("w:shd")
            shading_elm.set(qn("w:fill"), "E8E8E8")
            shading_elm.set(qn("w:val"), "clear")
            cell._element.get_or_add_tcPr().append(shading_elm)

            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_before = Pt(4)
                paragraph.paragraph_format.space_after = Pt(4)
                for run in paragraph.runs:
                    run.font.name = "Montserrat"
                    run.font.bold = True
                    run.font.color.rgb = COLOR_TEXT
                    run.font.size = Pt(10)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

        for i, edu in enumerate(candidate_data["education"], start=1):
            row_cells = table.rows[i].cells

            row_cells[0].text = edu["dates"]

            row_cells[1].text = ""
            para = row_cells[1].paragraphs[0]

            run_institution = para.add_run(edu["institution"])
            run_institution.font.name = "Montserrat"
            run_institution.font.bold = True
            run_institution.font.color.rgb = COLOR_TEXT
            run_institution.font.size = Pt(9)

            para.add_run("\n")

            run_degree = para.add_run(edu["degree"])
            run_degree.font.name = "Montserrat"
            run_degree.font.bold = False
            run_degree.font.color.rgb = COLOR_TEXT
            run_degree.font.size = Pt(9)

            if i % 2 == 0:
                for cell in row_cells:
                    shading_elm = OxmlElement("w:shd")
                    shading_elm.set(qn("w:fill"), "F8F8F8")
                    shading_elm.set(qn("w:val"), "clear")
                    cell._element.get_or_add_tcPr().append(shading_elm)

            for cell in row_cells:
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                for paragraph in cell.paragraphs:
                    paragraph.paragraph_format.space_before = Pt(6)
                    paragraph.paragraph_format.space_after = Pt(6)
                    paragraph.paragraph_format.line_spacing = 1.5
                    for run in paragraph.runs:
                        run.font.name = "Montserrat"
                        run.font.color.rgb = COLOR_TEXT
                        run.font.size = Pt(9)

            for para in row_cells[0].paragraphs:
                for run in para.runs:
                    run.font.name = "Montserrat"
                    run.font.color.rgb = COLOR_TEXT
                    run.font.size = Pt(9)

        doc.add_paragraph()

    # === UMIEJĘTNOŚCI / SKILLS ===
    add_section_header(doc, t["skills"])

    for skill_category in candidate_data.get("skills", []):
        para = doc.add_paragraph()

        pPr = para._element.get_or_add_pPr()
        numPr = etree.Element(f"{{{NS_W}}}numPr")
        ilvl = etree.SubElement(numPr, f"{{{NS_W}}}ilvl")
        ilvl.set(f"{{{NS_W}}}val", "0")
        numId = etree.SubElement(numPr, f"{{{NS_W}}}numId")
        numId.set(f"{{{NS_W}}}val", "1")
        pPr.insert(0, numPr)

        run1 = para.add_run(skill_category["label"] + " ")
        run1.font.name = "Montserrat"
        run1.font.bold = True
        run1.font.color.rgb = COLOR_TEXT
        run1.font.size = Pt(10)

        content = skill_category["content"].rstrip(" ,.")
        content = content + "."
        add_text_with_highlights(para, content, highlight_keywords, Pt(10))

        para.paragraph_format.space_before = Pt(1)
        para.paragraph_format.space_after = Pt(1)
        para.paragraph_format.line_spacing = 1.5

    # === CERTYFIKATY / CERTIFICATIONS ===
    if candidate_data.get("certifications"):
        add_section_header(doc, t["certifications"])
        add_bullet_list(
            doc, candidate_data.get("certifications", []), highlight_keywords
        )

    # === JĘZYKI / LANGUAGES ===
    add_section_header(doc, t["languages"])

    add_bullet_list(doc, candidate_data.get("languages", []), highlight_keywords)

    # === DOŚWIADCZENIE / EXPERIENCE ===
    add_section_header(doc, t["experience"])

    for i, job in enumerate(candidate_data.get("experience", [])):
        if i > 0:
            add_horizontal_line(doc)

        para = doc.add_paragraph()
        run = para.add_run(job["dates"])
        run.font.name = "Montserrat"
        run.font.color.rgb = COLOR_TEXT
        run.font.size = Pt(10)
        run.font.bold = True
        para.paragraph_format.space_before = Pt(1)
        para.paragraph_format.space_after = Pt(0)

        para = doc.add_paragraph()
        run1 = para.add_run(t["company_name"] + " ")
        run1.font.name = "Montserrat"
        run1.font.color.rgb = COLOR_TEXT
        run1.font.size = Pt(10)
        run2 = para.add_run(job["company"])
        run2.font.name = "Montserrat"
        run2.font.color.rgb = COLOR_TEXT
        run2.font.size = Pt(10)
        run2.font.bold = True
        para.paragraph_format.space_before = Pt(0)
        para.paragraph_format.space_after = Pt(0)

        para = doc.add_paragraph()
        run1 = para.add_run(t["position"] + " ")
        run1.font.name = "Montserrat"
        run1.font.color.rgb = COLOR_TEXT
        run1.font.size = Pt(10)
        run2 = para.add_run(job["position"])
        run2.font.name = "Montserrat"
        run2.font.color.rgb = COLOR_TEXT
        run2.font.size = Pt(10)
        run2.font.bold = True
        para.paragraph_format.space_before = Pt(0)
        para.paragraph_format.space_after = Pt(0)

        para = doc.add_paragraph()
        run = para.add_run(t["responsibilities"])
        run.font.name = "Montserrat"
        run.font.color.rgb = COLOR_TEXT
        run.font.size = Pt(10)
        run.font.bold = False
        run.font.underline = True
        para.paragraph_format.space_before = Pt(0)
        para.paragraph_format.space_after = Pt(1)

        add_bullet_list(doc, job.get("responsibilities", []), highlight_keywords)

        if job.get("technologies"):
            para = doc.add_paragraph()
            run1 = para.add_run(t["technologies"] + " ")
            run1.font.name = "Montserrat"
            run1.font.color.rgb = COLOR_TEXT
            run1.font.size = Pt(10)
            run1.font.bold = True
            add_text_with_highlights(
                para, ", ".join(job["technologies"]), highlight_keywords, Pt(10)
            )
            para.paragraph_format.space_before = Pt(4)
            para.paragraph_format.space_after = Pt(2)

    # === KLAUZULA RODO / GDPR ===
    doc.add_paragraph()
    doc.add_paragraph()

    rodo_para = doc.add_paragraph()
    rodo_text = t["rodo"]

    run = rodo_para.add_run(rodo_text)
    run.font.name = "Montserrat"
    run.font.size = Pt(5)
    run.font.color.rgb = COLOR_TEXT

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
