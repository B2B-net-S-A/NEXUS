# Rekrutacja bez szkiców — raport z wdrożenia (04.10.2026)

Makiety zaakceptowane przez Artura: https://claude.ai/artifact/9T6tEhBfsnyE1RsuaAxABy (wersja 2).
Reguły dla kolejnych zmian: CLAUDE.md, sekcja „Rekrutacja bez szkiców”.

## Dlaczego

Pomiar na produkcji z 04.10.2026 objął 40 rekrutacji założonych w NEXUSIE od 25.09 (tylko odczyt):

| Fakt | Liczba |
|---|---|
| Szkice, których nikt nie przekazał do searchu | 14 |
| Rekrutacje opublikowane bez przekazania (zmiana statusu w oknie edycji albo `/publish`, oba bez bramki) | 5 |
| Rekrutacje z terminem | 6 / 40 |
| Rekrutacje z hiring managerem | 10 / 40 |
| Rekrutacje z liczbą osób innej niż 1 (pola nie dało się nigdzie edytować) | 0 / 40 |
| Pary z zaznaczonym deal-breakerem w arkuszu, mimo to wysłane do klienta | 2 z 3 |

Decyzje Artura z 04.10.2026:
- rekrutacja nigdy nie jest szkicem; system wymusza komplet,
- linku udostępniania dla klienta nie robimy,
- reszta według rekomendacji z makiety.

## Co się zmieniło

**Tworzenie**
- `POST /api/jobs` robi wszystko w jednej transakcji:
  - utworzenie,
  - Champion,
  - decyzja o hiring managerze,
  - przekazanie do searchu,
  - podobne rekrutacje,
  - publikacja.
- Brak czegokolwiek kończy się odpowiedzią 422 `job_not_ready` z listą braków; w bazie nie zostaje nic.
- Rdzenie bez `commit` są w `services/job_lifecycle.py`. Dotychczasowe trasy wołają te same rdzenie.

**Nowe wymagania przekazania**
- Każde z nich ma opcję „Klient nie podał”:
  - hiring manager (`jobs.hiring_manager_not_provided`, migracja 0414),
  - termin (`jobs.deadline_not_provided`, migracja 0414).
- Do tego kategoria kompetencji i liczba osób.
- Bramka briefu automatu przydziału się nie zmieniła.

**Otwieranie i status**
- „Otwórz ponownie” oraz „Dokończ i opublikuj” wołają `POST /{id}/publish`. Obie przechodzą przez tę samą bramkę i od razu przekazują rekrutację do searchu.
- `PATCH` nie pozwala już ustawić szkicu ani opublikować rekrutacji z pominięciem bramki.

**Ochrona w trakcie pracy**
- Zapis rekrutacji w pracy jest odrzucany tylko wtedy, gdy tworzy nowy brak.
- Kod braku odsłonięty przez uzupełnienie innego pola nie liczy się jako nowy (`_REVEALED_BY`).

**Niedokończone formularze**
- Zapisują się na koncie autora: tabela `job_intake_forms`, migracja 0415, trasy `/api/job-intake/forms`.
- `/jobs/new` zapisuje formularz sam, a w kroku 1 pokazuje listę formularzy do wznowienia.

**Stare szkice**
- Pulpit „Czeka na Ciebie” ma listę „Rekrutacje do dokończenia albo zamknięcia”.
- Szkice zamykają się same 7 dni po wdrożeniu (`legacy_draft_autoclose.py`). Wystawiany jest paragon z identyfikatorami, nic nie jest kasowane.

**„Odpada, gdy…”**
- Okno „Przesuń dalej” i dok osoby ostrzegają i proponują odrzucenie.
- Karta rekomendacji pokazuje warunek. Trafienie można zaznaczyć przy odpowiedzi z arkusza screeningu.
- Przegląd zgłoszeń przez AI dostaje warunki i oznacza możliwe trafienie plakietką.

**Odczyt maila (v11)**
- Termin i liczba osób są odczytywane tylko z dosłownego cytatu.

## Weryfikacja

**Backend**
- Testy na lokalnym Postgresie 16 (proces z pakietu `pgserver`, bez Dockera), po `alembic upgrade heads` przez 0413 → 0414 → 0415:
  - `test_job_no_drafts.py`: 34/34,
  - przepięte pliki testów: zielone,
  - szeroki zestaw (~290 plików): 4166 zielonych. 5 czerwonych to dane pozostawione przez wcześniejsze przebiegi; na świeżej bazie przechodzą.
- `ruff check app/`, `ruff format --check app/` i bramka DTZ: czyste.

**Frontend**
- `npm run type-check`: czysto.
- `vitest --changed`: 464 pliki, 5169 testów zielonych.
- ESLint: 0 błędów.

**Przeglądarka**
- Harnessy sprawdzone przy 1280×720:
  - `/preview/new-job` w stanach `gaps`, `servererror`, `resume`,
  - `/preview/job-detail?closed=1&reopen=1`,
  - `/preview/custom-dashboard`,
  - `/preview/recommendation-card`.

**Recenzja bezpieczeństwa**
- Brak problemów blokujących.
- Uwaga recenzenta: kopiowanie odpowiedzi z notatki do arkusza łamałoby regułę 0413. Poprawione: trafienie da się zapisać wyłącznie przy odpowiedzi z arkusza.

## Świadomie poza zakresem

- Zapisy systemowe Championa nie są objęte ochroną: import dokumentu, weryfikacja, briefing.
- Link udostępniania dla klienta (decyzja Artura).
- „Zatrudnieni: X z N” w panelu „Zespół”: panel nie dostaje dziś liczby zatrudnionych, więc pokazuje samą liczbę osób.
- `cc_override` z kategorią spoza słownika daje 500 zamiast 422. Ten sam defekt ma stara trasa `/cc-override`; transakcja i tak jest wycofywana.

## Po wdrożeniu

- `/api/health` → SHA z maina.
- SQL tylko do odczytu:
  - liczba rekrutacji w stanie `draft`,
  - `app_settings['legacy_draft_autoclose:deployed_at']`,
  - po 7 dniach paragon `legacy_draft_autoclose:receipt`.
- `/jobs/new` przeklikane na produkcji bez zapisu.
