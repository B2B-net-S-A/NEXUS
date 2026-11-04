# Archiwum pytań z rozmów u klienta — raport (25.09.2026)

## Po co

Rekruterzy latami zbierali w Excelu „Pytania z interview” to, o co klient pytał
kandydata na rozmowie. Stan przed zmianą (odczyt z produkcji 25.09):

- bank `interview_questions` był pusty (1 wpis testowy),
- cykl rozmów u klienta miał 1 zdarzenie,
- od 25.09 rekrutacje powstają w NEXUSIE.

Archiwum zasila prep-kit, panel Championa i propozycje Luny na `/jobs/new`.

## Plik źródłowy

- 28 arkuszy (klienci), 444 wiersze, z czego 432 wpisy po pominięciu arkusza „Wszystkie”.
- 190 wpisów ma numer rekrutacji w nazwie roli. Na produkcji 180 z 187 numerów
  trafia jednoznacznie w rekrutację.
- Duzi klienci: Nordea 197 wpisów, PKO BP 50, CeZ 40, BNP 37.
- W treści są oceny kandydatów (stres, życie prywatne), nazwiska i pytania
  wygenerowane przez ChatGPT.

## Co zrobiono

- Migracja `0383_legacy_interview_questions` wraz z lustrem w `entrypoint.sh`:
  - źródło `interviewquestionsource.legacy_import`,
  - klucz AI `interview_question_import` (F25, GPT-6 Luna, zapas Sonnet 5).
- `services/client_question_archive.py`: wybór pytań z archiwum po
  technologiach roli.
- Prep-kit (`question_suggestions.py`):
  - tier `client_archive`,
  - etykieta archiwum dla pytań z podobnych rekrutacji,
  - limit kubełka fallbacku (`_take_missing`).
- Luna na `/jobs/new` (`champion_client_context.py`): dostaje wyłącznie
  pytania z archiwum o technologie wymienione w requeście.
- Trasy:
  - `GET /api/interview-cycle/client-questions/archive?job_id=`,
  - `GET /api/interview-questions` domyślnie bez archiwum (`include_archive=true` je dołącza).
- Szczelność:
  - pytanie powtórzone w debriefie staje się `client_debrief`,
  - kopia z szablonu pomija przypięcia z archiwum,
  - ocena prepu nie czyta archiwum.
- Frontend:
  - plakietka „Klient pytał (archiwum rozmów)” w prep-kicie,
  - przełącznik archiwum w Bazie pytań,
  - zwinięta sekcja archiwum w panelu „Pytania klienta z rozmów”.
- Skrypt `scripts/import_legacy_interview_questions.py`:
  - przebieg próbny zapisuje plan i arkusz do przeglądu, bez zapisu do bazy,
  - apply i rollback,
  - kontrola kodem: cytat musi być z notatki, w pytaniu nie może być osoby,
    pytanie ma najwyżej 300 znaków.

## Weryfikacja

- Testy backendu z bazą biegną w CI (lokalnie jest Python 3.9):
  - `test_client_question_archive.py`,
  - `test_import_legacy_interview_questions.py`,
  - rejestr AI.
- Parser i walidacja sprawdzone ręcznie na prawdziwym pliku: 432 wpisy,
  190 z numerem, poprawne czyszczenie nazwisk z nazwy roli.
- Frontend: `vitest` na zmienionych komponentach (11/11), `tsc` bez błędów.

## Wdrożenie importu (po merge'u)

1. `/api/health` zwraca SHA z maina.
2. Przebieg próbny w kontenerze backendu (`--xlsx … --plan … --review …`).
3. Artur akceptuje arkusz przeglądu.
4. `--apply`.
5. Sprawdzenie: liczby w SQL (tylko odczyt) oraz
   `GET /api/jobs/{id}/suggested-questions` na otwartej rekrutacji Nordei.
