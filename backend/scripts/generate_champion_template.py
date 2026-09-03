#!/usr/bin/env python3
"""Generator wzoru „Profil Championa" (.docx) — szablon 6-sekcyjny (09.2026, karta klienta).

JEDEN wzór, bez wariantów per klient. Do 09.2026 było ich piętnaście (ogólny
i czternaście per klient), różniących się WYŁĄCZNIE treścią kliencką: ramką
„Standardy tego klienta", opisem klienta i listą dokumentów. Ta treść ma od
teraz jedno miejsce — kartę klienta w NEXUSIE (`client_playbooks`; seed z
`app/data/client_playbooks/seed.json`), więc wzór jej nie przepisuje.

Skrypt, a nie ręcznie zredagowany plik, z jednego powodu: **nagłówki są
kontraktem z parserem.** `cv_generator_b2b/champion_builder.py` rozpoznaje
sekcje wgranego dokumentu po ich NAZWACH, więc wzór rozjechany z kodem po cichu
produkuje CV bez sekcji — a brak sekcji jest u nas poprawnym wynikiem, nie
błędem. Generowanie z jednego źródła sprawia, że literówka w Wordzie nie może
tego zepsuć; pilnuje tego `test_champion_template_agenda.py`.

Użycie:
    python scripts/generate_champion_template.py --out-dir /tmp/wzory

Plik trzeba wgrać na SharePoint — NEXUS trzyma do wzoru wyłącznie link
(`help_materials`), nie kopię.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

# Nagłówki sekcji. To NIE jest kosmetyka dokumentu, tylko kontrakt z parserem —
# patrz punkt 2 w docstringu modułu. Importowane przez
# `tests/test_champion_template_agenda.py`.
SECTION_TITLES: tuple[str, ...] = (
    "PODSTAWOWE INFORMACJE",
    "CO WPISAĆ (SEARCH)",
    "STACK TECHNOLOGICZNY",
    "O PROJEKCIE",
    "PYTANIA SCREENINGOWE",
    "O KLIENCIE",
)

# Etykiety pól, które parser traktuje jako TREŚCIOWE — czyli takie, po których
# zbiera zawartość do promptu generatora CV. Osobno od `SECTION_TITLES`, bo test
# sprawdzający wyłącznie nagłówki sekcji przepuścił już jedną lukę: „Insight od
# naszego konsultanta u klienta" nie pasował do wzorca `INSIGHT OD KONSULTANTA`
# i pole z nowego wzoru cicho nie trafiało do generowanego CV.
CONTENT_FIELD_LABELS: tuple[str, ...] = (
    "MUST-HAVE",
    "NICE-TO-HAVE",
    "Obowiązki na stanowisku",
    "Historyczne pytania klienta",
    "Insight od naszego konsultanta u klienta",
)

_ACCENT = RGBColor(0x4F, 0x46, 0xE5)  # indygo — akcent design systemu
_HINT = RGBColor(0x64, 0x74, 0x8B)  # slate-500


def _section(doc: Document, number: int, title: str) -> None:
    para = doc.add_paragraph()
    para.paragraph_format.space_before = Pt(14)
    run = para.add_run(f"{number}. {title}")
    run.bold = True
    run.font.size = Pt(13)
    run.font.color.rgb = _ACCENT


def _hint(doc: Document, text: str) -> None:
    """Kursywa w kolorze pomocniczym — instrukcja, nie treść do wypełnienia."""
    para = doc.add_paragraph()
    run = para.add_run(text)
    run.italic = True
    run.font.size = Pt(9)
    run.font.color.rgb = _HINT


def _kv_table(doc: Document, rows: list[tuple[str, str]]) -> None:
    """Tabela etykieta | wartość — układ, którego DL używa od zawsze."""
    table = doc.add_table(rows=len(rows), cols=2)
    table.style = "Table Grid"
    for i, (label, value) in enumerate(rows):
        cell = table.rows[i].cells[0]
        cell.text = ""
        run = cell.paragraphs[0].add_run(label)
        run.bold = True
        run.font.size = Pt(10)
        table.rows[i].cells[1].text = value

    doc.add_paragraph()


def _block_table(doc: Document, blocks: list[tuple[str, str]]) -> None:
    """Tabela jednokolumnowa: etykieta pogrubiona, pod nią miejsce na treść."""
    table = doc.add_table(rows=len(blocks), cols=1)
    table.style = "Table Grid"
    for i, (label, value) in enumerate(blocks):
        cell = table.rows[i].cells[0]
        cell.text = ""
        run = cell.paragraphs[0].add_run(label)
        run.bold = True
        run.font.size = Pt(10)
        if value:
            for line in value.split("\n"):
                cell.add_paragraph(line)
        else:
            cell.add_paragraph("")
    doc.add_paragraph()


def build() -> Document:
    doc = Document()

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("PROFIL CHAMPIONA")
    run.bold = True
    run.font.size = Pt(20)
    run.font.color.rgb = _ACCENT

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_run = sub.add_run("Idealny kandydat zweryfikowany z klientem")
    sub_run.italic = True
    sub_run.font.size = Pt(10)
    sub_run.font.color.rgb = _HINT

    _kv_table(
        doc,
        [("Opracowano na podstawie rozmowy z", "[Manager] oraz [Konsultant wewnętrzny]")],
    )

    _hint(
        doc,
        "Wypełniaj TYLKO to, co naprawdę zmienia decyzję o kandydacie. Puste pole "
        "jest lepsze niż wypełnione na wszelki wypadek — profil czyta rekruter "
        "przed rozmową, nie archiwum.",
    )

    # 1
    _section(doc, 1, SECTION_TITLES[0])
    _kv_table(
        doc,
        [
            ("Nazwa roli", ""),
            ("Minimum lat doświadczenia", ""),
            ("Stawka kandydata (PLN/h)", ""),
            ("Tryb pracy", "[ ] Stacjonarnie   [ ] Hybrydowo   [ ] Zdalnie"),
            ("Dni pracy stacjonarnej", "___ dni / tydzień"),
            # „Lokalizacja biura", nie „kandydata": scoring porównuje tę wartość
            # z miastem KANDYDATA, więc pole od zawsze znaczyło „dokąd trzeba
            # dojechać". Stara etykieta mówiła coś odwrotnego do zachowania.
            ("Lokalizacja biura", ""),
            # Dwa różne języki, dwa wiersze. „Pracy" to wymaganie wobec
            # kandydata; język dokumentu CV stoi niżej i pochodzi z reguł
            # klienta, więc tutaj jest tylko do odczytu.
            ("Język pracy (wymagany od kandydata)", ""),
            ("Start", ""),
            ("Deadline na kandydatów", ""),
            ("Długość kontraktu", ""),
        ],
    )
    _hint(
        doc,
        "Stawka kandydata: system ODRZUCA kandydatów powyżej tej kwoty, bez "
        "marginesu. Zostaw puste, jeśli nie ma twardego limitu.",
    )

    # 2
    _section(doc, 2, SECTION_TITLES[1])
    _hint(
        doc,
        "Nie plan sourcingu — dosłownie frazy, które rekruter wkleja w wyszukiwarkę.",
    )
    _block_table(
        doc,
        [
            ("Frazy do wyszukiwarki (po przecinku):", ""),
            ("Firmy docelowe:", ""),
            ("Kogo odrzucamy od razu (jeden powód na linię):", ""),
            ("Uwagi / plan działania:", ""),
        ],
    )

    # 3
    _section(doc, 3, SECTION_TITLES[2])
    _hint(
        doc,
        "Pojedyncze technologie po przecinku (Java, Kafka), nie zdania. To z tej "
        "listy liczy się dopasowanie kandydatów: technologia wpisana TUTAJ jest "
        "wymaganiem, opisana w sekcji 4 jest tylko tekstem.",
    )
    _block_table(
        doc,
        [
            (f"{CONTENT_FIELD_LABELS[0]}:", ""),
            (f"{CONTENT_FIELD_LABELS[1]}:", ""),
            ("Niuanse wersji / zakresu:", ""),
        ],
    )

    # 4
    _section(doc, 4, SECTION_TITLES[3])
    _hint(doc, "Maksymalnie 2 zdania o projekcie — resztę pomiń, nie przenoś gdzie indziej.")
    _block_table(
        doc,
        [
            ("Czym jest projekt (max 2 zdania):", ""),
            (f"{CONTENT_FIELD_LABELS[2]}:", ""),
        ],
    )

    # 5
    _section(doc, 5, SECTION_TITLES[4])
    _hint(doc, "Rekruter musi na nie odpowiedzieć przed wysłaniem CV do klienta.")
    table = doc.add_table(rows=4, cols=2)
    table.style = "Table Grid"
    head = table.rows[0].cells
    for cell, text in ((head[0], "Pytania od Delivery Leada"), (head[1], "Sugerowane odpowiedzi")):
        cell.text = ""
        run = cell.paragraphs[0].add_run(text)
        run.bold = True
        run.font.size = Pt(10)
    for i in (1, 2, 3):
        table.rows[i].cells[0].text = f"Pytanie {i}:"
        table.rows[i].cells[1].text = "Idealna odpowiedź:\n\nDeal breaker:"
    doc.add_paragraph()

    # 6 — wyłącznie to, co zależy od TEJ roli. Standardy współpracy (SLA,
    # limit CV, off-limit, onboarding, dokumenty) NIE są tu przepisywane:
    # żyją w karcie klienta w NEXUSIE (`client_playbooks`), jedno miejsce.
    _section(doc, 6, SECTION_TITLES[5])
    _hint(
        doc,
        "Standardy klienta (SLA, limit CV, off-limit, onboarding, dokumenty) są "
        "w NEXUSIE: Klient → Zasady współpracy albo Pomoc → Klienci. Nie "
        "przepisuj ich tutaj.",
    )
    _block_table(
        doc,
        [
            ("Co przekona kandydata do tej oferty:", ""),
            (f"{CONTENT_FIELD_LABELS[4]}:", ""),
            (f"{CONTENT_FIELD_LABELS[3]}:", ""),
        ],
    )

    return doc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "Profil_Championa_WZÓR.docx"
    build().save(path)
    print(f"zapisano: {path}")
    print(
        "\nWgranie na SharePoint jest osobnym krokiem — NEXUS trzyma do wzoru "
        "wyłącznie link (help_materials), nie kopię pliku.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
