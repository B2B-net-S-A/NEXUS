# Edytor CV 3 — PR 4: asystent w kolumnie (14.10.2026)

Propozycja i makiety: https://claude.ai/artifact/1g1FJJ2TtojTJSFjmZQj5Z
(„Ekran 3”). Kierunek D1–D6 i „bardzo, bardzo prosto” — decyzje Artura
z 14.10.2026. Reguły: `docs/claude/generator-cv/edytor-cv-pelny-ekran.md`,
sekcja „Asystent w kolumnie”. Bazą jest PR 3 (prosty ekran edytora).

## Co było nie tak

- AI w edytorze miało trzy wejścia: dymek nad zaznaczeniem, menu „AI”
  w pasku i pole „Polecenie” z panelem planu zmian. Każde działało inaczej,
  a zespół i tak wklejał CV do ChatGPT.
- Zmiana z polecenia wymagała przejrzenia planu i „Zastosuj zaznaczone”;
  fakt spoza CV był po prostu odrzucany, nawet gdy kandydat mówił o nim na
  rozmowie.

## Co weszło

- **Kolumna asystenta** pod „Do poprawy”: „Napisz, co zmienić”, cztery
  podpowiedzi („Skróć do 2 stron”, „Więcej o wymaganiach klienta”, „Popraw
  język i styl”, „Usuń najstarsze role”), pole jak w czacie (Enter wysyła).
  Zaznaczony tekst to kontekst wiadomości.
- **Zmiana od razu**: operacje sprawdzone przez serwer edytor nakłada jedną
  transakcją, podświetla na zielono (dekoracja widoku, nie trafia do pliku)
  i daje „Cofnij” przy odpowiedzi.
- **Pytania tylko, gdy trzeba**:
  - fakt spoza CV, oryginału i notatek („Nie widzę „Terraform” w CV ani
    w notatkach. Kandydat mówił o tym na rozmowie?”) — „Tak, dopisz”
    zapisuje notatkę pary „Potwierdzone z kandydatem: …” (QC przyjmuje ją
    jako źródło) i dopisuje punkt;
  - usunięcie jedynego miejsca z wymaganiem klienta — „Tak, zmień” / „Nie”.
- **Nowe operacje serwera**: dopisz punkt (`add`), pogrub / odpogrub,
  „Rozważany na stanowisko”. Kod dalej sprawdza każdą operację, struktura
  Worda i klauzula RODO są poza zasięgiem modelu, kwot nie ma nigdy.
- **Rozmowa**: do 6 ostatnich wiadomości i numery zaznaczonych wierszy,
  ogrodzone w promptach jako dane (`CV_EDITOR_COMMAND` v2).
- **Kolumna przy 1280 × 720**: „Do poprawy” zwijane nagłówkiem panelu
  (rozwinięte przy blokadach wysyłki), asystent ma stałe minimum wysokości;
  rozmowa przewija się do najnowszej odpowiedzi.
- Usunięte: `CvEditorCommandBar`, `CvEditorPlan`, `useCvCommandPlan`,
  `CvEditorSelectionAi`, `useCvSelectionAi`, `CvAiProposalCard` (z testami)
  i menu „AI” w pasku. Inwentarz funkcji: wpisy przepięte na asystenta albo
  z `removed_reason`, dwa nowe (fakt z rozmowy, „Cofnij”).

## Testy

- Backend (lokalnie, bez bazy): `test_cv_command_ai.py` (67: nowe
  operacje, pytanie o źródło, „loses”, kwoty, ogrodzenie rozmowy). Testy
  tras z bazą (`test_cv_editor_ai_route.py`, `confirm-fact`, zakres
  `test_fix48_ws06_cv_editor_ai_scope.py`, wzorzec
  `authz_golden/cv_editor_ai.json`) — w CI.
- Frontend (lokalnie, pliki zmienione): okno edytora (trzy pliki), panel
  uwag, harness edytora (24, bez sieci: skrócenie z „Cofnij”, pytanie
  o Terraform, „Nie” / „Tak, zmień”, pogrubienie, „Rozważany na”,
  zaznaczenie, awaria, Escape, szkic przy pierwszej zmianie), hook asystenta
  (2), `cv-editor-command` (nowe operacje, podświetlenie), historia, harnessy,
  inwentarz. Razem 505 + 2 testy; `npm run type-check` i eslint czyste.
- Zrzuty 1280×720 (Playwright, harness `/preview/cv-editor?state=draft`):
  start, „Skróć do 2 stron” (3 zmiany na zielono), pytanie o Terraform,
  „Tak, dopisz”. Pierwsze zrzuty pokazały pole asystenta pod stopką
  (asystent miał 125 px) i dwa nagłówki „Do poprawy” — poprawione
  i sprawdzone ponownie (pole kończy się 18 px nad stopką, rozmowa 167 px).
  Drugi zrzut pokazał nowe pytanie poza widokiem rozmowy — dodane
  przewijanie do najnowszej odpowiedzi.

## Poprawione przed PR-em

- „Tak, dopisz” zapisywało notatkę, zanim sprawdziło, czy wiersz jeszcze
  jest. Gdy rekruter w międzyczasie usunął punkt, notatka powstawała, CV się
  nie zmieniało, a powtórne „Tak” zapisałoby fakt drugi raz. Teraz najpierw
  sprawdzenie, potem notatka (test hooka padał przed poprawką).

## Świadomie poza zakresem

- Trasa `cv-ai/selection` i klient `networkAiApi` zostają bez ekranu
  (`cv_selection_ai.check` woła asystent). Usunięcie trasy — osobno.
- „Napisz od nowa” — PR 5.
- Przewodnik Jarvisa ekranu osoby nie mówił o „Poleceniu” ani menu „AI” —
  bez zmian.
