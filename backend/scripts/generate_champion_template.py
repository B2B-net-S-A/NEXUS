#!/usr/bin/env python3
"""Wzór „Profil Championa” (.docx) do wgrania na SharePoint — JEDEN plik (09.2026).

Do 23.09.2026 ten skrypt składał osobny wzór (tabele jednokolumnowe), różny od
formularza pobieranego z aplikacji. Import takiego pliku nie przechodził przez
odczyt formularza (`champion_document.table_profile`) i szedł przez płatne AI.
Decyzja Artura 23.09.2026: jeden wzór — formularz v5 z
`app/assets/champion/Profil_Championa_v5.0.docx` (budowany skryptem
`build_champion_template_v5.py`). Ten skrypt tylko go kopiuje pod nazwą
wgrywaną na SharePoint.

**Nagłówki są kontraktem z parserami.** `SECTION_TITLES` i
`CONTENT_FIELD_LABELS` opisują to, co stoi w v5; test
`test_champion_template_agenda.py` sprawdza, że parser CV
(`cv_generator_b2b/champion_builder.py`) rozpoznaje każdy nagłówek i każdą
etykietę treściową, a sam dokument je zawiera.

Użycie:
    python scripts/generate_champion_template.py --out-dir /tmp/wzory

Plik trzeba wgrać na SharePoint — NEXUS trzyma do wzoru wyłącznie link
(`help_materials`), nie kopię.
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import sys

from docx import Document

TEMPLATE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "app"
    / "assets"
    / "champion"
    / "Profil_Championa_v5.0.docx"
)

# Nagłówki sekcji wzoru v5 (bez numerów). Kontrakt z parserem CV.
SECTION_TITLES: tuple[str, ...] = (
    "PODSTAWOWE INFORMACJE",
    "CO WPISAĆ (SEARCH)",
    "STACK TECHNOLOGICZNY",
    "DOŚWIADCZENIE POZA STACKIEM",
    "O PROJEKCIE",
    "SCREENING",
    "O KLIENCIE",
    "WIEDZA Z ROZMÓW",
)

# Etykiety pól TREŚCIOWYCH — po nich parser CV zbiera treść do promptu.
CONTENT_FIELD_LABELS: tuple[str, ...] = (
    "MUST-HAVE",
    "NICE-TO-HAVE",
    "Obowiązki na stanowisku",
    "Historyczne pytania klienta",
    "Insight od naszego konsultanta u klienta",
)


def build() -> Document:
    return Document(TEMPLATE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "Profil_Championa_WZÓR.docx"
    shutil.copyfile(TEMPLATE, path)
    print(f"zapisano: {path}")
    print(
        "\nWgranie na SharePoint jest osobnym krokiem — NEXUS trzyma do wzoru "
        "wyłącznie link (help_materials), nie kopię pliku.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
