# Forma obowiązków w CV: EN w czasie przeszłym, PL forma rzeczownikowa (16.11.2026)
<!-- indeks: „Upgraded”, nie „Upgrade”; „Wdrażanie”, nie „Wdrażała”; także obecna rola; tylko forma, nie treść -->

Zgłoszenie z zespołu 16.11.2026: w wygenerowanym CV zadania stały w formie
„Upgrade applications…”, a powinny w czasie przeszłym („Upgraded…”). Do tego dnia
żaden prompt generatora nie mówił nic o formie czasownika, więc model przepisywał
formę ze źródłowego CV. Pomiar na stagingu (kopia produkcji, CV z 45 dni):
254 z 772 angielskich CV miało w jednym dokumencie „Develop…” i „Developed…”,
229 z 603 polskich mieszało „Wdrażanie…” z „Wdrażała…”.

Decyzja Artura z 16.11.2026 (makiety na CV ze stagingu, wariant A):

- **CV po angielsku:** każdy obowiązek we wszystkich rolach, także w obecnej
  („currently”), zaczyna się od czasownika w Past Simple („Developed…”, „Led…”).
  Nie forma podstawowa, nie „Develops…”, nie „Developing…”. Odrzucony wariant B
  (obecna rola w Present Simple): zgłaszający czyta „Perform…” jako błąd,
  a model musiałby rozpoznawać, która rola trwa.
- **CV po polsku:** forma rzeczownikowa („Wdrażanie…”, „Analiza…”) we wszystkich
  rolach. Czas przeszły po polsku wymaga rodzaju („Wdrażał” / „Wdrażała”), którego
  generator nie zna z pewnością, a pomyłka w rodzaju to widoczny błąd u klienta.
- Reguła zmienia **tylko formę gramatyczną**. Treść, zakres, kolejność i fakty
  zostają bez zmian, więc działa też w trybie „basic”.

Gdzie stoi: sekcja „FORMA OBOWIĄZKÓW” / „FORM OF RESPONSIBILITIES” w
`legacy_v7/prompts.py` (domyślna ścieżka) i `prompts.py` (v10), oraz
`RESPONSIBILITY_FORM` w `editorial_prompt.py`. Strażnik:
`tests/test_cv_responsibility_form_rule.py` (każdy język, tryb i CV anonimowe).
Punkty „Why our candidate” reguła nie obejmuje.

Dotyczy nowych generacji; gotowe CV pobiera się z zapisanego payloadu, więc
zostają w starej formie do ponownego wygenerowania.
