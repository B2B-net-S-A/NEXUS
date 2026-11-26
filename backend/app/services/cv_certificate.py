"""Certyfikat wgrany jako CV nie zostaje głównym CV (decyzja Artura 26.11.2026).

Kopia produkcji z 26.11.2026: u 2 z 66 675 osób tekst CV w profilu był
certyfikatem — PRINCE2 wgrany z rekrutacji jako „CV” (najnowszy plik wygrywał)
i certyfikat Pega jako główne CV z importu. Formularz CV klienta CEZ czytał
wtedy sam certyfikat, a podsumowanie profilu brzmiało „kandydat posiadający
certyfikat PRINCE2”.

Odczyt nowo wgranego pliku CV sprawdza tekst, zanim pójdzie do modelu: krótki
tekst z formułą certyfikatu i bez sekcji CV przechodzi na rodzaj „certyfikat”,
główne CV wraca do poprzedniego pliku, a profil zostaje bez zmian. Rodzaj
„certyfikat” pomija wybór domyślny CV (`cv_source.current_cv_filters`).
Rekruter może zmienić rodzaj z powrotem — ręczne „Ustaw jako główne” tego
sprawdzenia nie przechodzi.
"""

from __future__ import annotations

import re
from typing import Optional

# Ostatni przypadek z kopii produkcji, który to nie certyfikat, miał 5487 znaków
# (CV z rozstrzelonymi nagłówkami „W O R K H I S T O R Y”); certyfikaty — 211 i 574.
MAX_CERTIFICATE_CHARS = 4000

_CERTIFICATE = re.compile(
    r"this\s+is\s+to\s+certify"
    r"|has\s+(?:successfully\s+)?(?:achieved|completed|passed)"
    r"|certificate\s+(?:number|no\b|id\b)"
    r"|certificate\s+of\s+(?:completion|achievement|attendance)"
    r"|is\s+hereby\s+awarded|has\s+been\s+awarded|credential\s+id"
    r"|zaświadcza\s+się|niniejszym\s+zaświadcza",
    re.IGNORECASE,
)
_CV_SECTION = re.compile(
    r"\b(?:experience|doświadczeni|education|wykształceni|skills|umiejętności"
    r"|employment|zatrudnieni|work\s+history|projekty|projects|profil\s+zawodowy"
    r"|summary|podsumowanie\s+zawodowe)",
    re.IGNORECASE,
)


def looks_like_certificate_text(text: Optional[str]) -> bool:
    """Krótki tekst z formułą certyfikatu i bez żadnej sekcji CV."""
    stripped = (text or "").strip()
    return (
        bool(stripped)
        and len(stripped) <= MAX_CERTIFICATE_CHARS
        and _CERTIFICATE.search(stripped) is not None
        and _CV_SECTION.search(stripped) is None
    )
