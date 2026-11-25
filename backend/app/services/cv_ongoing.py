"""Słowa „do dziś” na końcu zakresu dat stanowiska — jedna lista dla CV.

Ta sama lista co ``CURRENT_WORD`` w Nowym CV (``cv_new_layout/facts.py``)
i ``PRESENT`` w edytorze (``frontend/src/lib/cv-new-layout-form.ts``), plus
„do dziś” i odmiany. Koniec zakresu, którego moduł nie rozpozna, gubi daty
stanowiska albo liczy je jak jeden miesiąc (zgłoszenie 25.11.2026:
„03.2023 – currently”; na stagingu 203 nagłówki stanowisk w CV etapu).
"""

from __future__ import annotations

import re

# Dłuższe warianty przed krótszymi, bo alternacja bierze pierwszy pasujący.
ONGOING_WORDS = (
    r"(?:do\s+dzi\w*|do\s+teraz|obecnie|aktualnie|teraz|nadal|dzisiaj|dziś|dzis"
    r"|present|currently|current|now|today|ongoing"
    r"|to\s+date|till\s+date|till\s+now|until\s+now)"
)
# Granice słów, bo „now” siedzi w „Snowflake”, a „present” w „presentation”.
ONGOING = re.compile(rf"\b{ONGOING_WORDS}\b", re.IGNORECASE)
