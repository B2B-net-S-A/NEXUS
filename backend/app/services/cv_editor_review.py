"""Text projection for source review of sanitized editor HTML."""

import re
from functools import lru_cache

from lxml import html

from app.services.cv_generator_b2b.factual_verification import verify_final_cv

_BLOCKS = {
    "p",
    "div",
    "section",
    "article",
    "h1",
    "h2",
    "h3",
    "h4",
    "li",
    "tr",
    "blockquote",
    "pre",
}
_LABELS = {
    "doświadczenie",
    "doświadczenie zawodowe",
    "experience",
    "work experience",
    "education",
    "wykształcenie",
    "skills",
    "umiejętności",
    "certifications",
    "certyfikaty",
    "languages",
    "języki",
    "podsumowanie",
    "summary",
    "dlaczego ten kandydat",
    "why this candidate",
}


class EditorReviewInputError(ValueError):
    pass


# 2 (12.10.2026): recenzent dostaje twierdzenia jawnie. W wersji 1 wszystkie
# linie szły jako `why_points`, a recenzent v4 nie traktuje tej sekcji jako
# twierdzeń — kontrola po edycji kończyła się błędem protokołu bez wywołania
# modelu (produkcja 27.09–12.10.2026: 12 z 12 zatwierdzeń).
EDITOR_REVIEW_VERSION = 2

# Znaczniki sekcji narracyjnej („dlaczego ten kandydat”) na nagłówku h2.
_NARRATIVE_MARKERS = {"why_points", "summary"}
# Akapit z takim znacznikiem należy do doświadczenia albo stopki — nie do narracji.
_STRUCTURE_MARKERS = {"role", "employer", "duties_label", "technologies", "rodo"}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
# „Rozważany na stanowisko: <tytuł>” — sam tytuł, nie zdanie dopisane za nim.
_CONSIDERED_MAX_CHARS = 80
_CONSIDERED_MAX_WORDS = 8
# Początek klauzuli zgody, który musi się zgadzać z szablonem co do znaku.
_CLAUSE_PROBE_CHARS = 200


def _title(text: str) -> str:
    return " ".join(text.split()).casefold().rstrip(":?").strip()


def _flat(text: str) -> str:
    return " ".join(text.split()).casefold()


class _Template:
    """Teksty, które dokłada szablon CV (PL i EN) — jedyne źródło „kontekstu”."""

    def __init__(self) -> None:
        # Leniwie, jak `cv_rodo_clause`: `docx_renderer` ciągnie python-docx.
        from app.services.cv_generator_b2b.docx_renderer import TRANSLATIONS

        sections = ("education", "skills", "certifications", "languages", "experience")
        self.narrative_titles = frozenset(
            {"summary", "podsumowanie", "dlaczego ten kandydat", "why this candidate"}
            | {_title(t["why"]) for t in TRANSLATIONS.values()}
        )
        self.section_titles = frozenset(
            self.narrative_titles
            | {_title(label) for label in _LABELS}
            | {_title(t[key]) for t in TRANSLATIONS.values() for key in sections}
        )
        self.duties = frozenset(
            _title(t["responsibilities"]) for t in TRANSLATIONS.values()
        )
        self.considered = tuple(
            _flat(t["considered_for"]) for t in TRANSLATIONS.values()
        )
        self.clauses = tuple(_flat(t["rodo"]) for t in TRANSLATIONS.values())

    def is_line(self, text: str) -> bool:
        """Czy linia jest w całości tekstem szablonu (nie ma jej czym potwierdzić).

        Liczy się TEKST, nie znacznik ani klasa: fakt dopisany do etykiety,
        za klauzulą zgody albo wpisany w nagłówek zostaje twierdzeniem.
        """
        if _title(text) in self.section_titles or _title(text) in self.duties:
            return True
        flat = _flat(text)
        for clause in self.clauses:
            # Starsza wersja klauzuli może różnić się końcówką, ale nie może
            # być dłuższa od szablonu — dopisane zdanie robi z niej twierdzenie.
            if len(flat) <= len(clause) and flat.startswith(
                clause[:_CLAUSE_PROBE_CHARS]
            ):
                return True
        for label in self.considered:
            if flat.startswith(label):
                rest = flat[len(label) :].strip()
                return (
                    len(rest) <= _CONSIDERED_MAX_CHARS
                    and len(rest.split()) <= _CONSIDERED_MAX_WORDS
                )
        return False


@lru_cache(maxsize=1)
def _template() -> _Template:
    return _Template()


def _review_lines(content_html: str) -> list[tuple[str, bool]]:
    """Linie dokumentu w kolejności, każda z flagą „to twierdzenie do sprawdzenia”.

    Twierdzeniem nie jest: sekcja narracyjna (kontrola v4 jej nie recenzuje —
    argumentacja składa fakty z innych pól) oraz tekst szablonu: tytuł sekcji,
    klauzula zgody, etykieta obowiązków, „Rozważany na stanowisko”. Zostają
    w dokumencie jako kontekst dla recenzenta.

    Narracja trwa od swojego nagłówka h2 do następnego nagłówka, tytułu sekcji
    albo akapitu ze znacznikiem struktury — usunięty nagłówek „Doświadczenie”
    nie może wyłączyć spod kontroli wszystkiego, co stoi pod nim.
    """
    if len(content_html.encode()) > 2_000_000:
        raise EditorReviewInputError("CV jest zbyt duże do kontroli treści.")
    root = html.fragment_fromstring(content_html, create_parent="div")
    if root.xpath(".//img | .//svg | .//object | .//iframe"):
        raise EditorReviewInputError(
            "Kontrola treści wymaga osobnego sprawdzenia obrazów w edytowanym CV."
        )
    template = _template()
    rows: list[tuple[str, bool]] = []
    current: list[tuple[str, bool]] = []
    state = {"narrative": False}

    def end_line() -> None:
        text = re.sub(r"\s+", " ", "".join(part for part, _ in current)).strip()
        if text:
            # Narracją jest tylko linia w całości z narracji — mieszana zostaje
            # twierdzeniem, żeby niczego nie ukryć przed kontrolą.
            rows.append((text, all(ctx for part, ctx in current if part.strip())))
            title = _title(text)
            if (
                title in template.section_titles
                and title not in template.narrative_titles
            ):
                # Tytuł kolejnej sekcji, także zdegradowany do akapitu.
                state["narrative"] = False
        current.clear()

    def emit(text: str) -> None:
        for piece in text.splitlines(keepends=True):
            body = "".join(piece.splitlines())
            current.append((body, state["narrative"]))
            if body != piece:
                end_line()

    def walk(node) -> None:
        element = isinstance(node.tag, str)
        tag = node.tag.lower() if element else ""
        if tag in {"script", "style"}:
            return
        if tag in _BLOCKS or tag == "br":
            end_line()
        if tag in _HEADINGS:
            state["narrative"] = tag == "h2" and (
                node.get("data-cv-section") in _NARRATIVE_MARKERS
                or _title("".join(node.itertext())) in template.narrative_titles
            )
        elif element and node.get("data-cv-section") in _STRUCTURE_MARKERS:
            state["narrative"] = False
        if node.text:
            emit(node.text)
        for child in node:
            walk(child)
            if child.tail:
                emit(child.tail)
            if child.tag in {"td", "th"}:
                emit(" | ")
        if tag in _BLOCKS:
            end_line()

    walk(root)
    end_line()
    lines = [
        (text, not (narrative or template.is_line(text)))
        for text, narrative in rows
        if text.casefold().rstrip(":") not in _LABELS
    ]
    if not lines or len(lines) > 1000:
        raise EditorReviewInputError("Nie można objąć całego CV kontrolą treści.")
    return lines


def editor_claims(content_html: str) -> list[str]:
    """Preserve paragraph order, negation and inline text; never silently truncate."""
    return [text for text, _ in _review_lines(content_html)]


def verify_editor_content(
    content_html: str,
    *,
    cv_text: str,
    screening_notes: str,
    identity: str,
    request_id: str,
) -> dict:
    # The complete ordered document is supplied alongside each batch, so dates,
    # companies and adjacent role headings remain available to the reviewer.
    # Twierdzenia podajemy jawnie: sam dokument stoi pod `why_points`, a tę
    # sekcję recenzent pomija, więc bez `claims` nie sprawdziłby niczego.
    lines = _review_lines(content_html)
    return verify_final_cv(
        {"why_points": [text for text, _ in lines]},
        cv_text=cv_text,
        screening_notes=screening_notes,
        identity=identity,
        request_id=request_id,
        claims={
            f"/why_points/{index}": text
            for index, (text, claim) in enumerate(lines)
            if claim
        },
    )
