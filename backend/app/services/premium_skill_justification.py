"""Szkic uzasadnienia dopłaty za technologię premium po angielsku (F5, 16.11.2026).

Delivery Lead prosi klienta o dopłatę z umowy ramowej (F3) i dołącza
uzasadnienie po angielsku. F4 składa je z szablonu (``premium-skills.ts``),
F5 prosi model z rejestru (``premium_skill_justification``) o płynniejszy
szkic z tych samych faktów.

Zasady (``docs/claude/klienci/stawki-ramowe-uzasadnienie-doplaty-z-modelu.md``):

* wejście to tylko fakty potrzebne do uzasadnienia — technologia i procent
  z umowy, kategoria i poziom, źródła dowodu NEXUSA, stack projektu z karty
  technicznej i przykłady wpisane przez DL-a. Bez imienia i nazwiska (z notatki
  DL-a zdejmujemy je kodem), nazwy klienta, stawki, limitu i treści CV;
* wynik jest szkicem: DL go czyta, poprawia i wysyła sam. NEXUS go nie zapisuje;
* model nie może dopisać faktów: liczby spoza wejścia wracają jako ostrzeżenie;
* brak modelu albo błąd = szablon z F4 i komunikat po polsku, nigdy blokada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

MAX_DRAFT_CHARS = 2500
MAX_NOTE_CHARS = 1500
MAX_STACK = 15

# Te same źródła co ``premium_skill_evidence.evidence_for`` (po polsku w UI),
# w zdaniu dla klienta po angielsku — jak szablon F4 na froncie.
_SOURCE_EN: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"^CV$"), "listed in the consultant's CV"),
    (
        re.compile(
            r"^oś czasu CV(?:: (?P<months>\d+) mies\.)?(?P<current>, obecnie)?$"
        ),
        "",
    ),
    (
        re.compile(r"^zweryfikowane na screeningu$"),
        "verified in our technical screening",
    ),
    (
        re.compile(r"^karta techniczna projektu \(opieka\)$"),
        "part of this project's technology stack, confirmed in our regular account review",
    ),
)


def source_en(source: str) -> str:
    for pattern, text in _SOURCE_EN:
        match = pattern.match(source)
        if not match:
            continue
        if text:
            return text
        months = match.group("months")
        use = f"{months} months of hands-on use" if months else "hands-on use"
        current = (
            ", ongoing on the current assignment" if match.group("current") else ""
        )
        return f"{use} in the consultant's career timeline{current}"
    return source


@dataclass(frozen=True)
class JustificationFacts:
    technology: str
    percent: str
    category: Optional[str]
    sources: tuple[str, ...]
    project_stack: tuple[str, ...] = field(default_factory=tuple)
    dl_note: Optional[str] = None


def scrub_names(text: Optional[str], names: Iterable[str]) -> Optional[str]:
    """Imię i nazwisko konsultanta z notatki DL-a → „the consultant”."""
    if not text or not text.strip():
        return None
    out = text.strip()[:MAX_NOTE_CHARS]
    parts = sorted(
        {p for n in names for p in re.split(r"\s+", n or "") if len(p) >= 3},
        key=len,
        reverse=True,
    )
    for part in parts:
        out = re.sub(
            rf"(?<!\w){re.escape(part)}(?!\w)", "the consultant", out, flags=re.I
        )
    out = re.sub(r"(the consultant)(\s+the consultant)+", r"\1", out, flags=re.I)
    return out


def build_facts(
    *,
    technology: str,
    percent: str,
    category: Optional[str],
    sources: Sequence[str],
    project_stack: Sequence[str],
    dl_note: Optional[str],
    person_names: Iterable[str],
) -> JustificationFacts:
    wanted = technology.casefold()
    stack = []
    for skill in project_stack:
        name = (skill or "").strip()
        if name and name.casefold() != wanted and name not in stack:
            stack.append(name)
    return JustificationFacts(
        technology=technology,
        percent=percent,
        category=category,
        sources=tuple(source_en(s) for s in sources),
        project_stack=tuple(stack[:MAX_STACK]),
        dl_note=scrub_names(dl_note, person_names),
    )


def facts_block(facts: JustificationFacts) -> str:
    lines = [
        f"- Premium technology: {facts.technology}",
        f"- Price adder in the Framework Agreement: {facts.percent}%",
        f"- Competence category and level of the assignment: {facts.category or 'not set'}",
        "- Evidence collected by us: "
        + ("; ".join(facts.sources) if facts.sources else "none"),
        # Wniosek istnieje tylko po decyzji DL-a „zna i korzysta”
        # (``premium_skills.create_claim``) — to fakt, nie założenie modelu.
        "- Our Delivery Lead confirmed: the consultant knows the technology and uses it "
        "every day on this assignment",
    ]
    if facts.project_stack:
        lines.append(
            "- Other technologies of this project: " + ", ".join(facts.project_stack)
        )
    lines.append(
        "- Examples from the project written by our Delivery Lead: "
        + (facts.dl_note or "none")
    )
    return "\n".join(lines)


def build_prompt(facts: JustificationFacts) -> str:
    return f"""You write for an IT consulting company that delivers consultants to a client under a Framework Agreement.
Our Delivery Lead asks the client to apply the Premium Technology Price Adder for one consultant. The client grants it only when the consultant knows the technology AND uses it on this assignment every day, not occasionally or as "nice to have". The technology must then be listed in "Description of knowledge and experience" of the request.

Write the justification the Delivery Lead will paste into the email to the client.

Rules:
- English, 90-170 words, one or two short paragraphs, plain text (no headings, bullet points, greeting or signature).
- Use ONLY the facts below. Do not add years, numbers, project names, tools, certificates or achievements that are not in the facts. Do not describe the consultant's tasks, the role or the project beyond the examples. If the examples are "none", say only that the technology is used every day on this assignment.
- Keep each source as given: the CV lists the technology; months of use come from the career timeline.
- Do not use the consultant's name; write "the consultant".
- Do not mention rates, prices, money or margins other than the adder percent.
- End with the request to include {facts.technology} in "Description of knowledge and experience" and to apply the adder.

Facts:
{facts_block(facts)}

Answer with the justification text only."""


_WRAPPERS = re.compile(r"^\s*(?:here is|here's|sure|justification)[^\n]*:\s*\n", re.I)


def clean_draft(raw: Optional[str]) -> Optional[str]:
    """Tekst modelu bez otoczki („Here is…”), cudzysłowów i markdownu."""
    text = (raw or "").strip()
    if not text:
        return None
    text = _WRAPPERS.sub("", text, count=1).strip()
    text = re.sub(r"^```\w*\s*|\s*```$", "", text).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'“”":
        text = text[1:-1].strip()
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:MAX_DRAFT_CHARS].strip() or None


_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def ungrounded_numbers(draft: str, facts: JustificationFacts) -> list[str]:
    """Liczby ze szkicu, których nie ma w faktach (np. wymyślone „5 years”)."""
    known = {n.replace(",", ".") for n in _NUMBER.findall(facts_block(facts))}
    known |= {n.split(".")[0] for n in known}
    out: list[str] = []
    for number in _NUMBER.findall(draft):
        value = number.replace(",", ".")
        if (
            value not in known
            and value.split(".")[0] not in known
            and number not in out
        ):
            out.append(number)
    return out


def warnings_for(draft: str, facts: JustificationFacts) -> list[str]:
    warnings: list[str] = []
    numbers = ungrounded_numbers(draft, facts)
    if numbers:
        warnings.append(
            "Szkic zawiera liczby, których nie ma w faktach NEXUSA ("
            + ", ".join(numbers)
            + ") — sprawdź albo usuń przed wysłaniem."
        )
    if facts.technology.casefold() not in draft.casefold():
        warnings.append(
            f"Szkic nie wymienia technologii {facts.technology} — dopisz ją."
        )
    return warnings


def call_model(chain: list[str], prompt: str) -> str:
    from app.services.claude_client import call_claude, text_of  # noqa: PLC0415

    message = call_claude(
        model=chain[0],
        fallback_models=chain[1:] or None,
        max_tokens=900,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": prompt}],
    )
    return text_of(message)
