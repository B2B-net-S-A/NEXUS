"""Oświadczenia i deklaracje do umowy zlecenie — puste wzory do pobrania.

Wypełnia je zleceniobiorca (PESEL, konto, dowód), więc NEXUS ich nie
generuje i nie zapisuje — tylko wydaje plik. Źródło: SharePoint Administracja
→ „3. Wzory umów / 3. Umowa zlecenie - kontraktorzy / Oświadczenia
i deklaracje” (stan z 21.10.2026). Nowa wersja wzoru = podmiana pliku
w ``app/data/mandate_forms/`` bez metadanych autora (repo jest publiczne).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

FORMS_DIR = Path(__file__).resolve().parents[2] / "data" / "mandate_forms"

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_PDF = "application/pdf"


@dataclass(frozen=True)
class MandateForm:
    key: str
    label: str
    description: str
    filename: str
    #: Nazwa pliku u użytkownika (z polskimi znakami).
    download_name: str

    @property
    def path(self) -> Path:
        return FORMS_DIR / self.filename

    @property
    def media_type(self) -> str:
        return _PDF if self.filename.endswith(".pdf") else _DOCX

    def to_public(self) -> dict:
        data = asdict(self)
        del data["filename"]
        data["format"] = "PDF" if self.media_type == _PDF else "DOCX"
        return data


MANDATE_FORMS: tuple[MandateForm, ...] = (
    MandateForm(
        key="contractor_statement_pl",
        label="Oświadczenie zleceniobiorcy",
        description=(
            "Dane do kadr, PIT i ZUS: adresy, urząd skarbowy, NFZ, konto, "
            "status (student, inne zatrudnienie, emerytura). Wzór na 2026."
        ),
        filename="oswiadczenie_zleceniobiorcy_2026_pl.docx",
        download_name="Oświadczenie zleceniobiorcy 2026.docx",
    ),
    MandateForm(
        key="contractor_statement_pl_en",
        label="Oświadczenie zleceniobiorcy (PL/EN)",
        description="To samo oświadczenie z tłumaczeniem na angielski.",
        filename="oswiadczenie_zleceniobiorcy_2026_pl_en.docx",
        download_name="Oświadczenie zleceniobiorcy 2026 PL-EN.docx",
    ),
    MandateForm(
        key="pit_2",
        label="PIT-2",
        description=(
            "Oświadczenia i wnioski do zaliczek na podatek, m.in. kwota "
            "zmniejszająca podatek (dla osób powyżej 26 lat)."
        ),
        filename="pit_2.pdf",
        download_name="PIT-2.pdf",
    ),
    MandateForm(
        key="ppk_resignation",
        label="Deklaracja rezygnacji z wpłat do PPK",
        description="Dla zleceniobiorcy, który nie chce oszczędzać w PPK.",
        filename="deklaracja_rezygnacji_ppk.pdf",
        download_name="Deklaracja rezygnacji z PPK.pdf",
    ),
    MandateForm(
        key="foreigner_tax_statement",
        label="Oświadczenie do celów podatkowych — cudzoziemcy",
        description="Rezydencja podatkowa cudzoziemca; z kopią paszportu.",
        filename="oswiadczenie_cudzoziemca_podatki.pdf",
        download_name="Oświadczenie do celów podatkowych - cudzoziemcy.pdf",
    ),
)

FORMS_BY_KEY: dict[str, MandateForm] = {f.key: f for f in MANDATE_FORMS}
