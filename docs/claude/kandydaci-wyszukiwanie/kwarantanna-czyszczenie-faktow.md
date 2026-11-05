# Kwarantanna tożsamości: co znika z profilu

Gdy plik zostaje uznany za CV innej osoby, `_clear_cv_projection` usuwa z profilu
fakty z tego pliku. Decyzje z 05.11.2026, po ręcznej naprawie dwóch profili:

- Porównujesz kolumnę z tym, co naprawdę zapisał `_apply_cv_enrichment`, nie
  z surowym odczytem. Umiejętności idą przez `normalize_llm_skills`, LinkedIn przez
  `normalize_linkedin_url`, e-mail małymi literami. Wykształcenie, lata i telefon
  zapisują się bez zmian (sama przycięta spacja), więc tam wystarcza równość.
- Umiejętności dopisane z notatek zostają. Notatki dopisują na końcu listy, więc
  zgodny początek to odczyt CV. Inna kolejność nie jest dowodem pochodzenia, bo
  `FILL_EMPTY` nie nadpisuje kolumny.
- Blokady są wiążące: `skills_manually_curated` i każda `_manual_override_<pole>`.
- Decyzja człowieka (`mark_confirmed_mismatch`) sprawdza też, czy tekst CV w profilu
  jest tekstem tego pliku, i wtedy czyści fakty, choć plik nie jest główny, a odczyt
  nie ma `source_document_id`. Automat tego nie robi, bo decyzja parsera bywa
  fałszywym alarmem.
