# Trzy nazwy rekrutacji (0380, 25.09.2026)

Decyzja Artura: rekruter ma widzieć, czego szukamy, a klient dostaje swoje nazwy.

- **`jobs.title` = nazwa od klienta** — bez zmiany znaczenia: idzie do klienta
  (stanowisko w CV, nazwa pliku, Cpro) i do wektora oferty, podobnych
  rekrutacji i strony kariery. Tytuł dla rekrutera tam NIE wchodzi (zmiana
  wektorów = osobne A/B).
- **`client_reference`** = numer zapytania klienta (ZOB, SAP…). Numer projektu
  w CV (`cv_packages.pko_job_reference`) czyta go przed regexem ZOB z tytułu;
  podpowiedź w generatorze dostaje każda reguła z `require_project_ref`.
  Kolejka Cpro kopiuje go do schowka. Bez UNIQUE.
- **`working_title` + `working_title_auto`** = tytuł dla rekrutera, składany
  KODEM (`services/job_working_title.py`, lustro `lib/job-names.ts`, wspólny
  `__fixtures__/job-working-title-cases.json`): rola · 2 must · N+ lat ·
  dziedzina „must”. Przelicza się przy zapisie Championa i PATCH
  `title`/`must_skills`, dopóki nikt go nie wpisze ręcznie; PATCH z pustym
  przywraca automat. Ekrany wewnętrzne pokazują `working_title ?? title`
  (`jobDisplayTitle`, SQL `job_display_title_expr`); nigdy do klienta.
- Odczyt maila (`JOB_REQUEST_INTAKE` v3) daje `client_title`/`client_reference`
  wyłącznie jako dosłowny cytat (`_in_text`) i `working_title_suggestion`.
- Kolumny są w `NEXUS_OWNED` (Traffit ich nie pisze). Istniejące rekrutacje
  uzupełnił jednorazowy krok `job-names-backfill` w `entrypoint.sh`.
