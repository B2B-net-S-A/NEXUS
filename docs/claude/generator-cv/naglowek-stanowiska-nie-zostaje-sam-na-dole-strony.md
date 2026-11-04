# Nagłówek stanowiska nie zostaje sam na dole strony

Zgłoszenie 22.10.2026: w CV z NEXUSA na dole strony stała sama data stanowiska
(„02.2019 - 03.2025”), a firma, stanowisko i zadania zaczynały się na następnej.

- Od #503 (16.06.2026) akapity CV w Wordzie celowo nie są sklejane
  (`keep_with_next` / `keep_together`), żeby rekruter poprawiający łamanie stron
  przesuwał tekst Enterem o jeden wiersz, a nie całe sekcje.
- Wyjątek: nagłówek stanowiska, czyli daty, „Nazwa firmy:”, „Stanowisko:”
  i „Zakres zadań:”, ma `keep_with_next`, więc trzyma się razem i z pierwszym
  zadaniem. Zadania, technologie i reszta sekcji dalej płyną wiersz po wierszu.
- Dotyczy obu dróg do Worda: generatora (`cv_generator_b2b/docx_renderer.py`,
  `render_cv_to_bytes`) i CV z edytora rekrutacji (`cv_approved_docx.py`,
  `render_role` / `labelled_line` / „Zakres zadań:”).
- Pilnuje tego `backend/tests/test_cv_role_header_keeps_with_tasks.py`. Nie dokładaj
  sklejania punktów zadań ani całych sekcji, bo wraca problem z #503.
