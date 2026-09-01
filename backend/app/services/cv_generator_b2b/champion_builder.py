"""Build the Champion Profile prompt section from NEXUS DB shape.

NEXUS stores the champion as a structured JSONB (``Job.champion_profile``)
plus ``Job.must_skills`` / ``Job.nice_skills`` columns. The external
CV-Generator expected a flat ``ChampionProfile`` shape; this module maps
between the two and renders the same prompt section format produced by
``buildChampionSection()`` in ``lib/cv-shared.ts``.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field

from app.services import champion_view
from app.services.cv_generator_b2b.text_extractor import extract_text_from_file
from app.services.skill_normalize import iter_skill_names

logger = logging.getLogger(__name__)


@dataclass
class ChampionParseDiagnostics:
    """How plausible the DOCX parse was. Never persisted — signal only.

    ``from_docx`` distinguishes the upload path from :func:`from_nexus_job`,
    whose structured JSONB input cannot suffer a heading-recognition failure and
    must therefore never trigger the parse warnings.
    """

    from_docx: bool = False
    headings_found: int = 0
    content_sections_found: int = 0
    raw_entry_count: int = 0
    kept_entry_count: int = 0
    dropped_prose: int = 0
    dropped_overflow: int = 0

    @property
    def dropped_total(self) -> int:
        return self.dropped_prose + self.dropped_overflow

    @property
    def nothing_recognised(self) -> bool:
        """No section that can carry content was recognised at all.

        Covers both "not a single known heading" and "only boundary headings"
        — the latter still leaves ``headings_found > 0`` while producing an
        entirely empty profile, so counting headings alone would stay silent.
        """
        return bool(self.from_docx and not self.content_sections_found)

    @property
    def wiped_out(self) -> bool:
        """The skill lists had content and the guard rejected ALL of it.

        Distinct from :attr:`implausible`: nothing at all reaches the prompt,
        so the champion is effectively absent and the recruiter needs a
        different message than "some entries were skipped".
        """
        return bool(
            self.from_docx and self.raw_entry_count and not self.kept_entry_count
        )

    @property
    def implausible(self) -> bool:
        """True when the document layout was probably not recognised."""
        if not self.from_docx:
            return False
        if self.wiped_out:
            return True
        if self.dropped_overflow:
            return True
        if self.raw_entry_count >= _MIN_ENTRIES_FOR_RATIO_CHECK:
            return self.dropped_prose / self.raw_entry_count > _MAX_PROSE_RATIO
        return False


@dataclass
class ChampionProfileForPrompt:
    """Flat shape used by :func:`build_champion_section`."""

    must_have: list[str] = field(default_factory=list)
    nice_to_have: list[str] = field(default_factory=list)
    project_context: str = ""
    responsibilities: str = ""
    screening_questions: str = ""
    historical_questions: str = ""
    consultant_insight: str = ""
    diagnostics: ChampionParseDiagnostics = field(
        default_factory=ChampionParseDiagnostics
    )

    def is_empty(self) -> bool:
        return not any(
            [
                self.must_have,
                self.nice_to_have,
                self.project_context.strip(),
                self.responsibilities.strip(),
                self.screening_questions.strip(),
                self.historical_questions.strip(),
                self.consultant_insight.strip(),
            ]
        )


def from_nexus_job(
    must_skills: list[dict] | None,
    nice_skills: list[dict] | None,
    champion_profile: dict | None,
    requirements: str | None = None,
) -> ChampionProfileForPrompt:
    """Map NEXUS Job columns to the flat ChampionProfile shape.

    Args:
        must_skills: Value of ``Job.must_skills``.
        nice_skills: Value of ``Job.nice_skills``.
        champion_profile: Value of ``Job.champion_profile`` (JSONB dict).
        requirements: Optional fallback for ``responsibilities`` when the
            champion profile lacks ``project_context.responsibilities``.
    """
    # iter_skill_names handles every legacy JSONB shape the column may hold —
    # list[dict], list[str], dict {"technologies": [...]}, a JSON-encoded
    # string, or a comma list — so a dict/string column no longer collapses to
    # the literal key "technologies" or gets iterated character-by-character.
    must = iter_skill_names(must_skills)
    nice = iter_skill_names(nice_skills)

    # Przez `champion_view`, więc ta sama ścieżka obsługuje profil sprzed i po
    # przebudowie szablonu (09.2026). Bez tego generator CV dla oferty zapisanej
    # w nowym kształcie widziałby pusty `project_context` i po cichu produkował
    # CV bez kontekstu projektu — dokument wygląda poprawnie, brakuje w nim
    # tylko tego, po co był generowany.
    cp = champion_profile or {}
    proj = champion_view.project(cp)
    cli = champion_view.client(cp)

    about = str(proj.get("about") or "").strip()
    selling = str(cli.get("selling_points") or "").strip()
    project_context_parts = [p for p in (about, selling) if p]
    project_context = "\n\n".join(project_context_parts)

    responsibilities = str(proj.get("responsibilities") or "").strip()
    if not responsibilities and requirements:
        responsibilities = requirements.strip()

    questions = champion_view.screening_questions(cp)
    if isinstance(questions, list) and questions:
        lines: list[str] = []
        for q in questions:
            if not isinstance(q, dict):
                continue
            text = str(q.get("question") or "").strip()
            if not text:
                continue
            ideal = str(q.get("ideal_answer") or "").strip()
            dealbreaker = str(q.get("deal_breaker") or "").strip()
            line = f"- {text}"
            if ideal:
                line += f"\n  Idealna odpowiedź: {ideal}"
            if dealbreaker:
                line += f"\n  Deal-breaker: {dealbreaker}"
            lines.append(line)
        screening_str = "\n".join(lines)
    else:
        screening_str = ""

    historical = str(cli.get("historical_questions") or "").strip()
    insight = str(cli.get("consultant_insight") or "").strip()

    return ChampionProfileForPrompt(
        must_have=must,
        nice_to_have=nice,
        project_context=project_context,
        responsibilities=responsibilities,
        screening_questions=screening_str,
        historical_questions=historical,
        consultant_insight=insight,
    )


def build_champion_section(profile: ChampionProfileForPrompt, language: str) -> str:
    """Render the champion section appended to the Claude prompt.

    Mirrors ``buildChampionSection()`` in ``lib/cv-shared.ts``.
    """
    header = "CHAMPION PROFILE" if language == "en" else "PROFIL CHAMPIONA"
    section = f"\n\n{header}:\n"

    if profile.must_have:
        section += f"\nMUST-HAVE: {', '.join(profile.must_have)}"
    if profile.nice_to_have:
        section += f"\nNICE-TO-HAVE: {', '.join(profile.nice_to_have)}"
    if profile.project_context:
        label = "Project Context" if language == "en" else "Kontekst projektu"
        section += f"\n\n{label}: {profile.project_context}"
    if profile.responsibilities:
        label = (
            "Position Responsibilities"
            if language == "en"
            else "Obowiązki na stanowisku"
        )
        section += f"\n\n{label}: {profile.responsibilities}"
    if profile.screening_questions:
        label = "Screening Questions" if language == "en" else "Pytania screeningowe"
        section += f"\n\n{label}: {profile.screening_questions}"
    if profile.historical_questions:
        label = (
            "Historical Interview Questions"
            if language == "en"
            else "Historyczne pytania z interview"
        )
        section += f"\n\n{label}: {profile.historical_questions}"
    if profile.consultant_insight:
        label = "Consultant Insight" if language == "en" else "Insight konsultanta"
        section += f"\n\n{label}: {profile.consultant_insight}"

    return section


def build_screening_notes_section(notes: str, language: str) -> str:
    """Render the SCREENING NOTES section appended to the Claude prompt."""
    if not notes.strip():
        return ""
    header = "SCREENING NOTES" if language == "en" else "NOTATKI ZE SCREENINGU"
    return f"\n\n{header}:\n{notes.strip()}"


# ── Champion DOCX layout: known headings (Old mode) ────────────────────────
#
# Every section terminates at the NEXT known heading of ANY kind, never at
# end-of-string alone. The previous per-section regexes ended their lookahead
# with ``|$``, so a single heading spelled differently than expected made that
# section swallow the whole rest of the file: in production 738 of 739
# champion-backed generations pushed the entire document tail — screening Q&A,
# sourcing strategy, office addresses and internal notes ("Nie blokujemy
# kandydatów!", "OFFLIMIT - TAK") — into MUST-HAVE, which is then sent to Claude
# as the client's requirement list.
#
# The vocabulary below covers BOTH the original external CV-Generator template
# (PODSTAWY / PROFIL KANDYDATA / 3. KONTEKST / 4. SCREENING / 5. SUCCESS) and
# the Delivery-Lead template actually in use, whose section headings were
# recovered from the 739 stored render payloads (occurrence counts in comments).
#
# ``field`` is the ChampionProfileForPrompt attribute the section feeds, or None
# for boundary-only headings — they terminate the previous section but carry no
# content of their own.

_NUM = r"(?:\d+\s*[.)]\s*|[IVX]+\s*[.)]\s*)?"  # optional MANUAL numbering.
# Word AUTO-numbering (numPr) never appears in paragraph.text, so this prefix
# must stay optional — "3. KONTEKST" and a bare "KONTEKST" must both match.

_HEADINGS: tuple[tuple[str, str | None], ...] = (
    # ── content-bearing ──────────────────────────────────────────────────
    #
    # A content-bearing heading must stop at its colon, NEVER at end-of-line:
    # the body is `text[match.end():…]`, so a heading that ate its own line
    # would silently swallow "O projekcie: <cały opis>" written as one Word
    # paragraph — the whole field would come back empty. `[ \t]*` (not `\s*`)
    # for the same reason in reverse: greedy `\s*` with a nullable `:?` after it
    # crosses the newline, the non-overlapping scan then resumes mid-line and
    # `(?m)^` can never match again, so the NEXT heading is skipped entirely.
    (rf"{_NUM}MUST[\s\-]?HAVE\b[ \t]*:?", "must_have"),
    (rf"{_NUM}NICE[\s\-]?TO[\s\-]?HAVE\b[ \t]*:?", "nice_to_have"),
    (rf"{_NUM}O\s+projekcie\b[^\n:]*:?", "project_context"),
    (rf"{_NUM}Obowiazk\w*\s+na\s+stanowisku\b[^\n:]*:?", "responsibilities"),
    # `Lead\w*`, not `Lead\b` — Polish inflects it ("Pytania od Delivery Leada").
    (rf"{_NUM}Pytani[ae]\s+od\s+Delivery\s+Lead\w*[^\n:]*:?", "screening_questions"),
    # Szablon 09.2026 nazywa tę samą sekcję „5. Pytania screeningowe". Stary
    # nagłówek ZOSTAJE obok: wystąpił w 783 z 1095 sparsowanych dokumentów, a
    # w firmie krąży kilkaset kopii starego wzoru, które będą wgrywane jeszcze
    # długo. Zdjęcie go zamieniłoby każdy z nich w CV bez sekcji screeningu —
    # po cichu, bo brak sekcji jest u nas poprawnym wynikiem, nie błędem.
    (rf"{_NUM}Pytania\s+screeningowe\b[^\n:]*:?", "screening_questions"),
    (rf"{_NUM}Historyczne\s+pytania\b[^\n:]*:?", "historical_questions"),
    # `(?:NASZEGO\s+)?` — szablon 09.2026 pisze „Insight od NASZEGO konsultanta
    # u klienta", stary „INSIGHT OD KONSULTANTA". Bez tego wariantu pole z nowego
    # wzoru nie trafiałoby do promptu CV, a wykryć to można było wyłącznie
    # puszczając wygenerowany plik przez ten parser — replika wyrażenia w teście
    # sprawdzała same NAGŁÓWKI SEKCJI i tę lukę przepuszczała.
    (
        rf"{_NUM}INSIGHT\s+OD\s+(?:NASZEGO\s+)?KONSULTANTA\b[^\n:]*:?",
        "consultant_insight",
    ),
    # ── boundary-only: original external template ────────────────────────
    (rf"{_NUM}PODSTAWY\b[^\n]*", None),
    (rf"{_NUM}PROFIL\s+KANDYDATA\b[^\n]*", None),
    (rf"{_NUM}KONTEKST\b[^\n]*", None),
    (rf"{_NUM}SCREENING\b[^\n]*", None),
    (rf"{_NUM}SUCCESS\s+PROFILE\b[^\n]*", None),
    (rf"{_NUM}Zakres\s+obowiazk\w*\b[^\n]*", None),
    # ── boundary-only: Delivery-Lead template (counts = prod occurrences) ─
    (rf"{_NUM}Co\s+przekona\b[^\n]*", None),  # 637 — first heading after MUST-HAVE
    # Single common verbs need a colon to count as a heading, otherwise an
    # ordinary sentence ("Szukamy osoby, która…", "- Szukamy min. 5 lat")
    # truncates whatever section it sits in.
    (rf"{_NUM}Szukamy[ \t]*:", None),  # 162
    (rf"{_NUM}Strategia\s+Delivery\s+Lead\w*\b[^\n]*", None),  # 639 + 99
    (rf"{_NUM}Kluczowe\s+slowa\b[^\n]*", None),  # 611 + 103
    (rf"{_NUM}Firmy\s+docelowe\b[^\n]*", None),  # 612 + 119
    (
        rf"{_NUM}Glowne\s+(?:zrodla|zrodza)\b[^\n]*",
        None,
    ),  # 172 + 119 + 447 (typo'd variant)
    (rf"{_NUM}Co\s+powiedziec\s+o\s+Kliencie\b[^\n]*", None),  # 593
    (rf"{_NUM}Dlaczego\s+to\s+wazne\b[^\n]*", None),  # 350
    (rf"{_NUM}(?:Lokalizacja|Adresy)\s+biur\b[^\n]*", None),  # 350 + 104
    (rf"{_NUM}UWAGI[^\n:]*:", None),  # "Uwagi / plan działania:" 389+217+111
    (rf"{_NUM}OFFLIMIT\b[^\n]*", None),  # 372 + 108
    # ── boundary-only: nagłówki szablonu 09.2026 ─────────────────────────
    #
    # Same w sobie nie niosą treści dla CV, ale MUSZĄ być granicami: bez nich
    # sekcja poprzedzająca połyka je razem z całą swoją zawartością i do
    # promptu trafia „O projekcie" zawierające pół dokumentu. „Stack
    # technologiczny" jest tu, a nie wśród treściowych, bo skille siedzą w jego
    # PODsekcjach MUST-HAVE / NICE-TO-HAVE, które mają własne wzorce wyżej.
    (rf"{_NUM}Podstawowe\s+informacje\b[^\n]*", None),
    (rf"{_NUM}Co\s+wpisac\b[^\n]*", None),
    (rf"{_NUM}Stack\s+technologiczny\b[^\n]*", None),
    (rf"{_NUM}O\s+kliencie\b[^\n]*", None),
    (rf"{_NUM}Dokumenty\b[^\n]*", None),
)
#
# DELIBERATELY NOT headings: "Pytanie 1:", "Idealna odpowiedź:", "Deal breaker:".
# They occur 286/781/783 times but are the INTERNAL structure of the screening
# block — promoting them to section boundaries would truncate
# ``screening_questions`` after the first question and drop the rest.

# One alternation, MULTILINE and anchored to the START of a line. The start
# anchor is load-bearing: unanchored terminators fire mid-sentence (a lowercase
# "insight" inside prose would cut the screening section short), which is the
# symmetric failure to the one being fixed here.
#
# There is deliberately NO end-of-line anchor. Every prose heading above already
# consumes to end-of-line via `[^\n]*`, so an end anchor would only ever
# constrain MUST-HAVE / NICE-TO-HAVE — and it would break the common layout
# where the chips sit on the SAME line as the heading ("MUST-HAVE: Java,
# Python"), which would silently produce an empty skill list.
_HEADING_PREFIX = r"[ \t\-•·*]*"
_HEADING_SCAN_RE = re.compile(
    r"(?m)^" + _HEADING_PREFIX + r"(?:" + "|".join(src for src, _ in _HEADINGS) + r")",
    re.IGNORECASE,
)
_HEADING_FIELD_RES: tuple[tuple[re.Pattern[str], str | None], ...] = tuple(
    (re.compile(r"^" + _HEADING_PREFIX + r"(?:" + src + r")", re.IGNORECASE), fld)
    for src, fld in _HEADINGS
)

# Polish diacritics → ASCII and every dash variant → "-", so a heading matches
# whether the recruiter typed "Główne źródła" or "Glowne zrodla" and whether
# Word autocorrected the hyphen in "OFFLIMIT - TAK" to an en dash. Both prod
# spellings occur. str.translate over single codepoints is 1:1 and therefore
# LENGTH-PRESERVING, which is what lets the scan run on the folded mirror while
# every match offset still indexes the original text (see _segment_champion_text).
_MATCH_FOLD_MAP = str.maketrans(
    {
        **{ord(a): b for a, b in zip("ąćęłńóśźż", "acelnoszz")},
        **{ord(a): b for a, b in zip("ĄĆĘŁŃÓŚŹŻ", "ACELNOSZZ")},
        **{ord(c): "-" for c in "‐‑‒–—―−"},
        ord(" "): " ",  # non-breaking space
    }
)


def _fold_for_match(text: str) -> str:
    """Diacritic/dash-folded mirror of ``text`` with IDENTICAL indices."""
    return text.translate(_MATCH_FOLD_MAP)


# Strip leading bullet glyphs / dashes / numbering when normalizing list items.
_BULLET_STRIP_RE = re.compile(r"^[\s\-•·*]+|[\s\-•·*]+$")
_ONLY_BULLET_RE = re.compile(r"^[\s\-•·*]+$")


def _split_skills(raw: str) -> list[str]:
    r"""Split MUST-HAVE / NICE-TO-HAVE blob into discrete tech names.

    Splits on newline, and on comma/semicolon only OUTSIDE parentheses, so a
    chip like ``Java (Spring, Hibernate)`` or ``WCAG 2.1/2.2 (AA, AAA)`` stays
    whole instead of shattering at the inner comma. Trims bullets/whitespace,
    drops empty and pure-bullet fragments.

    (Deliberately diverges from the JS 1:1 port ``text.split(/[\n,;]/)`` in
    ``lib/cv-shared.ts``, which broke parenthesised list items.)
    """
    if not raw:
        return []
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in raw:
        if ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "\n" or (ch in ",;" and depth == 0):
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    out: list[str] = []
    for p in parts:
        s = _BULLET_STRIP_RE.sub("", p).strip()
        if not s or _ONLY_BULLET_RE.match(s):
            continue
        out.append(s)
    return out


# ── Shape guard on the parsed skill lists ──────────────────────────────────
#
# The segmentation above fixes the *known* layouts. This guard is the backstop
# that bounds the damage for layouts nobody has seen yet — including the case a
# perfect segmenter cannot help with: requirement PROSE written directly under a
# correctly-spelled "MUST-HAVE:" heading, which is exactly what the leading
# production entries were.
_MAX_SKILL_ENTRY_CHARS = 80
_MAX_SKILL_ENTRY_WORDS = 8
_MAX_SKILL_ENTRIES = 40
_MIN_ENTRIES_FOR_RATIO_CHECK = 12
_MAX_PROSE_RATIO = 0.25

# A sentence break INSIDE one entry — prose, never a technology chip.
_SENTENCE_BREAK_RE = re.compile(r"[.!?…]\s")
_PROSE_TAIL_RE = re.compile(r"[.!?…:;]$")
# Abbreviations whose period is NOT a sentence break. Polish requirement chips
# are full of them ("specjalista ds. compliance" is a canonical skill name in
# seed_skill_aliases.py; "j. angielski B2", "min. 3 lata"), and treating their
# period as end-of-sentence dropped legitimate entries.
_ABBREV_RE = re.compile(
    r"\b(?:ds|j|ang|min|max|ok|np|tj|itp|itd|nt|ew|zł|inz|mgr|dr|hab|"
    r"m\.in|B\.Sc|M\.Sc|Ph\.D)\.",
    re.IGNORECASE,
)
# A phrase this long that also ends in a full stop is a sentence, not a chip.
# 5 (not 3) so "Spring Boot / Spring Cloud." survives while "Project Coordinator
# lub w zarządzaniu projektami." does not.
_PROSE_TAIL_MIN_WORDS = 5


def _is_prose_entry(entry: str) -> bool:
    """True when a :func:`_split_skills` fragment is requirement prose.

    Three independent axes, any one of which disqualifies. Calibrated against
    the production artefact (256 entries, longest 200 chars, 49 over 60 chars)
    and against real chips that MUST survive: "Java (Spring, Hibernate)"
    (24 chars, 3 words), "WCAG 2.1/2.2 (AA, AAA)" (22, 3), "Microsoft Dynamics
    365 Business Central" (39, 5), "specjalista ds. compliance".

    Length and word count are measured on the entry with terminal punctuation
    stripped, and standalone separators ("/") are not counted as words — both
    made the verdict depend on typography rather than on content.
    """
    s = entry.strip()
    core = s.rstrip(".,:;!?…").strip()
    if not core:
        return True  # punctuation-only fragment
    if len(core) > _MAX_SKILL_ENTRY_CHARS:
        return True
    words = [w for w in core.split() if any(ch.isalnum() for ch in w)]
    if len(words) > _MAX_SKILL_ENTRY_WORDS:
        return True
    if _SENTENCE_BREAK_RE.search(_ABBREV_RE.sub("", s)):
        return True
    if _PROSE_TAIL_RE.search(s) and len(words) >= _PROSE_TAIL_MIN_WORDS:
        return True
    return False


def _guard_skill_lists(
    raw_must: str, raw_nice: str, diag: ChampionParseDiagnostics
) -> tuple[list[str], list[str]]:
    """Split both skill blobs and drop anything that is not chip-shaped."""
    must = _split_skills(raw_must)
    nice = _split_skills(raw_nice)
    diag.raw_entry_count = len(must) + len(nice)

    def sift(items: list[str]) -> list[str]:
        kept: list[str] = []
        for item in items:
            if _is_prose_entry(item):
                diag.dropped_prose += 1
                continue
            kept.append(item)
        return kept

    must, nice = sift(must), sift(nice)

    total = len(must) + len(nice)
    if total > _MAX_SKILL_ENTRIES:
        # Must-have is the higher-signal list, so it is never starved: it keeps
        # its entries first and nice-to-have takes whatever budget remains.
        keep_must = min(len(must), _MAX_SKILL_ENTRIES)
        keep_nice = max(0, _MAX_SKILL_ENTRIES - keep_must)
        diag.dropped_overflow = total - (keep_must + keep_nice)
        must, nice = must[:keep_must], nice[:keep_nice]

    diag.kept_entry_count = len(must) + len(nice)
    return must, nice


# ── Segmentation ───────────────────────────────────────────────────────────


@dataclass
class _Segment:
    field: str | None
    body: str
    heading: str


def _segment_champion_text(text: str) -> list[_Segment]:
    """Split the extracted DOCX text at every known heading, in document order.

    Each segment's body ends where the NEXT known heading starts, or at
    end-of-text for the final one. Content before the first heading is dropped
    (it is the document's title block).

    The scan runs over the diacritic/dash-folded mirror of ``text``; the fold is
    length-preserving, so every offset indexes back into ``text`` unchanged and
    the bodies keep their original spelling.
    """
    folded = _fold_for_match(text)
    marks = list(_HEADING_SCAN_RE.finditer(folded))
    segments: list[_Segment] = []
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        heading_folded = mark.group(0).strip()
        fld = next(
            (f for rx, f in _HEADING_FIELD_RES if rx.match(heading_folded)), None
        )
        segments.append(
            _Segment(
                field=fld,
                body=text[mark.end() : end].strip(),
                heading=text[mark.start() : mark.end()].strip(),
            )
        )
    return segments


def parse_champion_from_docx_bytes(
    data: bytes, filename: str
) -> ChampionProfileForPrompt:
    """Parse a Word-format Champion Profile into the flat prompt shape.

    Segments the extracted text at every known heading (:data:`_HEADINGS`), so
    each section stops at the next heading of any kind. Replaces the previous
    per-section regexes, whose ``|$`` lookahead let one unrecognised terminator
    swallow the rest of the document.

    A section that legitimately ends the file still runs to end-of-text — that
    is the last segment by construction, not an error.

    Used by the "Old" mode (manual upload) path only. The "New" mode uses
    :func:`from_nexus_job`, which reads structured JSONB from ``Job`` directly
    and so cannot hit any of this.
    """
    # NFC first: the fold map keys are precomposed codepoints, and pasted /
    # IME-produced text can arrive decomposed. Normalising once up front means
    # every later offset refers to this same string.
    text = unicodedata.normalize("NFC", extract_text_from_file(data, filename))
    segments = _segment_champion_text(text)

    picked: dict[str, _Segment] = {}
    for seg in segments:
        # First occurrence wins — mirrors the previous re.search() semantics.
        if seg.field and seg.field not in picked:
            picked[seg.field] = seg

    def body(name: str) -> str:
        seg = picked.get(name)
        return seg.body if seg else ""

    diag = ChampionParseDiagnostics(
        from_docx=True,
        headings_found=len(segments),
        # Boundary headings ("OFFLIMIT", "Strategia Delivery Leada") do not carry
        # content, so a document made only of those parses to an entirely empty
        # profile. Counting them as "recognised" would suppress the warning.
        content_sections_found=len(picked),
    )
    must_have, nice_to_have = _guard_skill_lists(
        body("must_have"), body("nice_to_have"), diag
    )

    # Deliberate asymmetry, preserved from the old ``_SCREENING_RE.group(0)``:
    # the screening block is the one section that carries its own heading line
    # into the prompt. Changing it would silently alter the prompt for every
    # champion that parses correctly today.
    screening_seg = picked.get("screening_questions")
    screening_questions = (
        f"{screening_seg.heading}\n{screening_seg.body}".strip()
        if screening_seg
        else ""
    )

    if not segments:
        logger.warning(
            "[champion] %r: no known heading found — champion parsed as empty "
            "(bytes=%d)",
            filename,
            len(data),
        )
    else:
        logger.debug(
            "[champion] %r: %d headings, fields=%s, entries raw=%d kept=%d",
            filename,
            len(segments),
            sorted(picked),
            diag.raw_entry_count,
            diag.kept_entry_count,
        )

    return ChampionProfileForPrompt(
        must_have=must_have,
        nice_to_have=nice_to_have,
        project_context=body("project_context"),
        responsibilities=body("responsibilities"),
        screening_questions=screening_questions,
        historical_questions=body("historical_questions"),
        consultant_insight=body("consultant_insight"),
        diagnostics=diag,
    )
