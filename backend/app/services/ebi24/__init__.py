"""Integracja z EBI24 (obieg dokumentów Finansów) — na razie wyłącznie odczyt.

* ``environment`` — tryb i dane dostępowe (``EBI24_*``, domyślnie ``off``),
* ``client`` — podpisane żądania do API klienta v1, limity z podręcznika.

Etap pomiaru (02.11.2026): dane czyta tylko ``scripts/ebi24_probe.py``. Żaden
ekran, pętla ani trasa API jeszcze z tego nie korzysta. Zasady i kolejne kroki:
``docs/claude/integracje/ebi24-api-odczyt-i-pomiar.md``.
"""
