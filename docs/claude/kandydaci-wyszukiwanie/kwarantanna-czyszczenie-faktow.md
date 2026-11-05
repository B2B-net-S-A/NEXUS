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

## Nazwa z nagłówka CV nie daje kwarantanny

Gdy model nie poda imienia albo nazwiska, albo w ogóle nie odpowie,
`_apply_contact_fallbacks` bierze je z pierwszej linii CV o 2–4 słowach pisanych
wielką literą. Bywa to stanowisko albo nazwa firmy: 05.11.2026 przegląd 9 plików
pokazał same fałszywe alarmy, reguła odtwarza nazwę w 7 z nich, a w 4 linia nie była
nazwą osoby. Profil 91859 stracił przez to 10 pól.

- Taki odczyt ma `_name_from_header`, a wołający przekazuje go bramce jako
  `observed_name_from_header`. Inna nazwa niż w profilu daje wtedy `inconclusive`,
  zgodna nadal `confirmed_match`. Nazwa od modelu inna niż w profilu nadal daje
  `confirmed_mismatch`.
- Nie opieraj tego na `_confidence`. Model ocenia też puste pola, a `setdefault`
  zostawia jego wartość, więc nazwa z nagłówka bywa z pewnością 0,0, a nie 0,6
  (profil 662327).
- Koszt: cudze CV, w którym model nie poda nazwy, nie trafi do kwarantanny.
  `evidence.observed_name_from_header` w przeglądzie pozwala policzyć takie decyzje.
  Starsze decyzje nie mają tego pola, bo odczyt z kwarantanny nigdy nie trafił do
  profilu, więc źródła ich nazwy nie da się odtworzyć.
- Decyzja `confirmed_mismatch` zapisana wcześniej zostaje. Zwalnia ją tylko człowiek.
