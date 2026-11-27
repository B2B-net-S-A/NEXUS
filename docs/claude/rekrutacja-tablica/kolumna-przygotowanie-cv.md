# Kolumna „Przygotowanie CV” (dawniej „Zweryfikowany”, 27.11.2026)

Decyzja z 27.11.2026: trzecia kolumna Tablicy nazywa się „Przygotowanie CV”,
bo w niej powstaje CV firmowe, a weryfikacja w celach liczy się dopiero od
wejścia pary na „QC CV” (osobna zmiana w liczeniu KPI). Nazwa „QC CV” zostaje.

- **Kody się nie zmieniają:** `verified`, `interview`, `cv_qc`, klucze API,
  parametry filtrów i nazwy pól (`verified_required_fields`,
  `VerifiedRateModal`) zostają. Zmienia się tylko to, co czyta człowiek.
- **Jedna nazwa kolumny w trzech lustrach:** `BOARD_COLUMN_LABEL.verified`
  (`frontend/src/lib/board-stages.ts`), `move_requirements.COLUMN_LABEL`
  i `schemas/pipeline.STAGE_LABELS`. Etykiety etapów w listach, filtrach,
  „Moich ludziach” i opiekach po odejściu idą za nimi. Strażnik:
  `backend/tests/test_stage_przygotowanie_cv.py` i `board-stages.test.ts`.
- **Szablony w bazie:** migracja `0798_stage_przygotowanie_cv` (lustro
  w `entrypoint.sh`, wzór 0361) zmienia nazwę etapu „Zweryfikowany” na
  „Przygotowanie CV” jednorazowo (znacznik w `app_settings`) i tylko
  w szablonach spoza Traffita. Szablon z Traffita przepisuje nocny sync, więc
  jego etap „Zweryfikowany” (i „Kandydat Zweryfikowany”) trafia na etap
  `verified` szablonu rekrutacji po kodzie (`foreign_stage_target`). Nie
  dopasowuj etapów po nazwie „Zweryfikowany” — fixture
  `board-stage-cases.json` ma obie nazwy.
- **Proza:** podpowiedzi, okna, toasty, przewodniki Jarvisa, lekcje
  i ćwiczenia Poligonu mówią „Przygotowanie CV” z odmianą („na „Przygotowanie
  CV””, „do „Przygotowania CV””, „przed „Przygotowaniem CV””). Bez zmian
  zostają: liczby „Weryfikacje”/„Zweryfikowani” w statystykach, KPI i
  Insights, czasowniki („zweryfikował(a) kandydata”), „Zweryfikowane
  technologie” i krok „Zweryfikowane” w Kosztach Finansów.
