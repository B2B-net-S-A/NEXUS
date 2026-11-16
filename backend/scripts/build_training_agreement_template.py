"""Builder: wzór „Umowa B2B - Szkolenia” (Word) → szablon umowy szkoleniowej.

Wzór od Artura z 13.11.2026: umowa o współpracę B2B w zakresie usług
szkoleniowych, Załącznik nr 1 (agenda i warunki szkolenia) i Załącznik nr 2
(klauzula RODO). Zapisuje ``app/templates/contract/umowa_szkoleniowa_pl.docx``
— szablon docxtpl, który wypełnia ``services/trainings/agreement.build_context``.

Zasady jak w ``build_b2b_document_templates.py`` (te same klocki):

* formatowanie wzoru zostaje; pola do wypełnienia (``____``, ``……``,
  ``TAK / NIE``, puste linie pod etykietami Załącznika nr 1) zamieniają się
  w placeholdery, podświetlenie znika;
* formy „Panem/ią”, „prowadzącym/cą”, „zwany/ą” → ``{{ g.* }}``;
* sześć pustych „Moduł N:” → pętla po ``agenda``;
* komparycja B2B.net S.A. zostaje jak we wzorze (dane jawne spółki), Partner
  wyłącznie jako ``{{ partner.* }}`` — w szablonie nie ma danych osobowych;
* skrypt odrzuca wynik z niewypełnionym polem albo formą rodzajową ze wzoru,
  a metadane pakietu (autor, SharePoint, dodatki Worda) są czyszczone.

Uruchom po zmianie wzoru; wynik jest commitowany, wzoru NIE commitujemy.

    python scripts/build_training_agreement_template.py <wzór.docx> [katalog_wyjściowy]
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

import docx
from docx.document import Document as _Doc
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_b2b_document_templates import (  # noqa: E402
    BuildError,
    control_after,
    control_before,
    find,
    paragraphs,
    remove,
    scrub_package,
    set_text,
    sub,
    sub_in,
)

KEY = "umowa_szkoleniowa_pl"
OUT_DIR = Path(__file__).resolve().parents[1] / "app" / "templates" / "contract"
AGENDA_SLOTS = 6


def _next(p: Paragraph) -> Paragraph:
    """Następny akapit (rodzeństwo ``w:p``) — puste linie pod etykietą."""
    el = p._p.getnext()
    while el is not None and el.tag != qn("w:p"):
        el = el.getnext()
    if el is None:
        raise BuildError(f"Brak akapitu po {p.text[:50]!r}")
    return Paragraph(el, p._parent)


def _fill_below(doc: _Doc, label: str, expr: str) -> Paragraph:
    """Pusta linia pod etykietą Załącznika nr 1 → ``expr``."""
    blank = _next(find(doc, label))
    if blank.text.strip():
        raise BuildError(f"Pod {label!r} nie ma pustej linii: {blank.text[:50]!r}")
    return set_text(blank, expr)


def _fill_after(anchor: Paragraph, label: str, expr: str) -> Paragraph:
    """Jak ``_fill_below``, gdy etykieta powtarza się we wzorze („Termin
    przekazania:” w pkt 3 i 4) — szuka pierwszej etykiety za ``anchor``."""
    p = anchor
    for _ in range(12):
        p = _next(p)
        if re.fullmatch(label, p.text.strip()):
            blank = _next(p)
            if blank.text.strip():
                raise BuildError(f"Pod {label!r} nie ma pustej linii")
            return set_text(blank, expr)
    raise BuildError(f"Brak etykiety {label!r} za {anchor.text[:50]!r}")


def build(doc: _Doc) -> None:
    # ── Komparycja ──────────────────────────────────────────────────────────
    sub(doc, r"…+\.?\s+roku(?= w Warszawie)", "{{ agreement_date }} roku")
    party = find(doc, r"^Panem/ią\s*_+")
    sub_in(party, r"^Panem/ią\s*_+", "{{ g.pan }} {{ partner.name_instrumental }}")
    sub_in(party, r"prowadzącym/cą", "{{ g.prowadzacy }}")
    sub_in(party, r"(?<=pod firmą: )_+(?=,)", "{{ partner.company }}")
    sub_in(
        party,
        r"(?<=pod adresem: )_+,\s*00-000\s*_+,",
        "{{ partner.address }}{% if partner.postal_city %}, "
        "{{ partner.postal_city }}{% endif %},",
    )
    sub_in(
        party,
        r"NIP:\s*_+,\s*REGON:\s*_+,",
        "NIP: {{ partner.nip }}{% if partner.regon %}, REGON: "
        "{{ partner.regon }}{% endif %},",
    )
    contact = find(doc, r"^Tel\.\s*…+\.?\s*Adres e-mail:\s*…+\.?$")
    set_text(
        contact,
        "{% if partner.phone %}Tel. {{ partner.phone }}, {% endif %}"
        "Adres e-mail: {{ partner.email }}",
    )
    sub(doc, r"^zwany/ą(?= w dalszej części umowy)", "{{ g.zwany }}")

    # ── § 3 ust. 2 — termin, § 7 ust. 1 — wynagrodzenie, § 15 — adresy ─────
    sub(
        doc,
        r"(?<=w ustalonych przez strony terminach):$",
        ": {{ t.schedule }}.",
    )
    sub(
        doc,
        r"^_+\s*zł netto\s*\(słownie:\s*_+\s*złotych netto\),",
        "{{ fees.total }} zł netto (słownie: {{ fees.total_words }} netto),",
    )
    sub(doc, r"(?<=^Zamawiający: )_+$", "{{ company_email }}")
    sub(doc, r"(?<=^Partner: )_+$", "{{ partner.email }}")

    # ── Załącznik nr 1 ──────────────────────────────────────────────────────
    sub(
        doc,
        r"(?<=w zakresie usług szkoleniowych z dnia )_+$",
        "{{ agreement_date }} r.",
    )
    # 1. Dane szkolenia
    _fill_below(doc, r"^Nazwa szkolenia:$", "{{ t.title }}")
    _fill_below(doc, r"^Temat szkolenia:$", "{{ t.topic }}")
    _fill_below(doc, r"^Termin szkolenia:$", "{{ t.date }}")
    _fill_below(doc, r"^Godziny szkolenia:$", "{{ t.hours }}")
    _fill_below(doc, r"^Łączny przewidywany czas szkolenia:$", "{{ t.duration }}")
    _fill_below(doc, r"^Platforma:$", "{{ t.platform }}")
    _fill_below(doc, r"^Przewidywana liczba uczestników:$", "{{ t.participants }}")

    # 2. Agenda — moduł 1 to wzór pętli, moduły 2–6 znikają.
    for number in range(2, AGENDA_SLOTS + 1):
        label = find(doc, rf"^Moduł {number}:$")
        for _ in range(2):
            blank = _next(label)
            if blank.text.strip():
                raise BuildError(f"Moduł {number}: niepusta linia {blank.text!r}")
            remove(blank)
        remove(label)
    first = find(doc, r"^Moduł 1:$")
    body, spacer = _next(first), _next(_next(first))
    if body.text.strip() or spacer.text.strip():
        raise BuildError("Moduł 1: oczekiwano dwóch pustych linii")
    set_text(first, "Moduł {{ m.no }}:")
    set_text(body, "{{ m.text }}")
    control_before(first, "for m in agenda")
    control_after(spacer, "endfor")

    # 3. Materiały dla uczestników
    _fill_below(
        doc,
        r"^Partner przygotuje i przekaże uczestnikom:$",
        "{{ t.participant_materials }}",
    )
    section3 = find(doc, r"^3\. Materiały dla uczestników$")
    _fill_after(section3, r"Format materiałów:", "{{ deliv.materials.format }}")
    _fill_after(section3, r"Termin przekazania:", "{{ deliv.materials.due }}")

    # 4. Materiały przekazywane Zamawiającemu
    for label, key in (
        ("materiały szkoleniowe dla uczestników", "materials"),
        ("prezentację", "presentation"),
        ("pliki audio", "audio"),
    ):
        flag = find(doc, rf"^{label} – TAK / NIE;$")
        sub_in(flag, r"TAK / NIE", "{{ deliv." + key + ".flag }}")
    _fill_below(doc, r"^inne pliki:$", "{{ deliv.other }}")
    section4 = find(doc, r"^4\. Materiały przekazywane Zamawiającemu$")
    _fill_after(section4, r"Format plików:", "{{ deliv.files_format }}")
    _fill_after(section4, r"Termin przekazania:", "{{ deliv.files_due }}")

    # 5. Prawa autorskie
    _fill_below(
        doc,
        r"^Do następujących materiałów przygotowanych specjalnie",
        "{{ rights.works }}",
    )
    _fill_below(doc, r"^Materiały własne Partnera stworzone", "{{ rights.own }}")
    _fill_below(doc, r"^Materiały osób trzecich:$", "{{ rights.third_party }}")

    # 6. Wynagrodzenie A–E i łącznie
    for label, key in (
        (r"^A\. Przygotowanie programu", "prep"),
        (r"^B\. Przeprowadzenie szkolenia", "delivery"),
        (r"^C\. Przygotowanie i przekazanie prezentacji", "presentation"),
        (r"^D\. Przygotowanie i przekazanie plików audio", "audio"),
        (r"^E\. Wynagrodzenie związane z przeniesieniem", "rights"),
        (r"^ŁĄCZNE WYNAGRODZENIE", "total"),
    ):
        sub_in(find(doc, label), r"_+(?= zł netto$)", "{{ fees." + key + " }}")

    # 7. Egzamin — „test wiedzy” zależy od zamówienia (``knowledge_test``).
    set_text(find(doc, r"^Szkolenie nie kończy się egzaminem\.$"), "{{ exam_text }}")

    # 8. Dodatkowe ustalenia
    _fill_below(doc, r"8\. Dodatkowe ustalenia$", "{{ extra_terms }}")


# ── Kontrola wyniku ──────────────────────────────────────────────────────────

_JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)
# Linie podpisów („______ ZAMAWIAJĄCY … PARTNER”) zostają jak we wzorze.
_SIGNATURE = re.compile(r"^[\s_]*(?:ZAMAWIAJĄCY)?[\s_]*(?:PARTNER)?\s*$")
_LEFTOVERS = [
    (re.compile(r"_{3,}"), "niewypełnione pole ____"),
    (re.compile(r"\.{4,}|…{2,}"), "niewypełnione pole ……"),
    (re.compile(r"TAK / NIE"), "wybór TAK / NIE"),
    (re.compile(r"00-000"), "kod pocztowy ze wzoru"),
    (re.compile(r"\w/(ą|ią|cą)\b"), "forma rodzajowa ze wzoru"),
    (re.compile(r"^Moduł [2-9]:"), "stały moduł agendy"),
]


def verify(doc: _Doc) -> None:
    problems = []
    for p in paragraphs(doc):
        text = _JINJA.sub("", p.text)
        if _SIGNATURE.match(text):
            continue
        for rx, label in _LEFTOVERS:
            if rx.search(text):
                problems.append(f"{label}: {p.text[:90]!r}")
    if problems:
        raise BuildError(
            f"[{KEY}] wynik ma pozostałości wzoru:\n  " + "\n  ".join(problems)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "source", type=Path, help="wzór „Umowa B2B - Szkolenia” (.docx)"
    )
    parser.add_argument("out_dir", type=Path, nargs="?", default=OUT_DIR)
    args = parser.parse_args()
    doc = docx.Document(str(args.source))
    build(doc)
    verify(doc)
    buf = io.BytesIO()
    doc.save(buf)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / f"{KEY}.docx").write_bytes(
        scrub_package(
            buf.getvalue(), "Umowa o współpracę B2B w zakresie usług szkoleniowych"
        )
    )
    print(f"[{KEY}] ✓ → {args.out_dir}")


if __name__ == "__main__":
    main()
