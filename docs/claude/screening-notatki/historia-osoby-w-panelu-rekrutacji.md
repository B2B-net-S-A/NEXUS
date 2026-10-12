# Historia notatek osoby w panelu rekrutacji (12.10.2026)

<!-- indeks: „Wcześniej u nas” w zakładce „Notatki i historia” i w wąskim doku, jedno zapytanie o notatki osoby, wynik rekrutacji z historii, prawdziwe ruchy pary, licznik notatek ludzi -->

Zgłoszenie Artura 12.10.2026: „historyczne notatki się nie wyświetlają”. Panel osoby w rekrutacji pytał wyłącznie
o notatki z `job_id` bieżącej rekrutacji, więc osoba z bogatą historią wyglądała jak ktoś, o kim nic nie wiemy.
Pomiar na produkcji tego dnia (odczyt, same liczby): 3 433 otwarte karty, 2 187 z napisem „Brak notatek w tej
rekrutacji.”, z czego 1 417 miało notatki ludzi gdzie indziej (mediana 7, p90 38, maks. 137). Decyzje Artura:
wariant B + C z makiet (https://claude.ai/artifact/Pm2abFRkegL3rM3CZedKsx), licznik liczy notatki ludzi.
Raport: `docs/person-history-notes-completion-report.md`.

- **Panel pyta o WSZYSTKIE notatki osoby, nie o `job_id`.** `useCandidateNotes`
  (`pages/candidate-notes-query.ts`) — ten sam klucz `candidateQueryKeys.notes(id)`, adres i surowa odpowiedź co
  „Historia” profilu, więc panel i profil dzielą jedno pobranie. „W tej rekrutacji” wylicza przeglądarka
  (`job_id === jobId`). Hak nie ma `select`: trzech czytników pod jednym kluczem musi widzieć tę samą treść.
  `useJobNotes` / `JobNotesBlock` zostają dla doków kroków i edytora CV — nie wracaj nimi do zakładki ani doku.
- **Podział i grupy liczy `person/notes-by-recruitment.ts`**, rysuje `person/PersonNotesHistory.tsx`
  (`variant="tab"` — zakładka, `variant="dock"` — sekcja „Notatki” wąskiego doku). Lista notatek to nadal
  `JobNotesList` na `NotesList`: odpowiedzi, przypięte pierwsze, zwijanie długich treści i zakryte wpisy o stawce
  do klienta działają bez kopii. Nie dokładaj tu własnej, uproszczonej karty notatki.
- **Grupy „Wcześniej u nas” idą od najświeższej notatki, także „Bez rekrutacji”.** 20 451 notatek ludzi z Traffita
  nie ma rekrutacji, a na 383 otwartych kartach są takie notatki napisane już po wejściu osoby do bieżącej
  rekrutacji (954 szt.). Grupa „Bez rekrutacji” na stałe na końcu chowałaby najświeższe rozmowy.
- **Wynik rekrutacji nie jest zgadywany.** Plakietka („Odrzucony”, „Zrezygnował”, „Zatrudniony”, „Rekrutacja
  zamknięta”) pojawia się tylko, gdy `GET /api/candidates/{id}/history` ma wiersz tej rekrutacji
  i `isRecruitmentEnded` — `recruitmentOutcome` dla nieznanego etapu zwraca „Rekrutacja zamknięta”. Rekrutacja
  w toku pokazuje etap, a notatka wskazująca rekrutację spoza historii (osoba zdjęta z rekrutacji, sama
  propozycja) dostaje tytuł z `job_title` notatki i nic więcej.
- **Wyniki czyta osobne zapytanie `useCandidateRecruitmentOutcomes`** (klucz `recruitmentOutcomes` pod
  `historyRoot`, z zakresem widza), nie `useCandidateHistoryQuery`: tamto odświeża ciężką trasę przy każdym
  montowaniu i z `gcTime: 0` gubi dane między zakładkami. W cache zostają same pola wyniku, bez stawek.
  To dodatek — jego ładowanie i awaria nie pokazują się na ekranie, grupy powstają z samych notatek.
  Wąski dok tego zapytania nie robi.
- **Jeden filtr sekcji: „Rozmowy · Wszystko”** (domyślnie rozmowy; „Wszystko” niesie próby kontaktu, wpisy
  Delivery Leada, maile i automaty). Bez „Pokaż systemowe” w każdej grupie. Gdy osoba nie ma żadnej rozmowy,
  sekcja od razu pokazuje wszystko.
- **Licznik to notatki ludzi** (`humanNoteCount`): na zakładce „Notatki i historia” (tylko gdy > 0)
  i w podpisie zwiniętej sekcji doku („0 tu · 14 wcześniej”; bez historii zostaje „N w tej rekrutacji”).
  Zapytanie o notatki stoi w doku od otwarcia karty — podpis ma mówić o historii bez rozwijania sekcji.
- **„Historia w tej rekrutacji” to prawdziwe ruchy pary**: `GET /api/pipeline/job/{job_id}/moves?candidate_id=`
  (filtr w CTE — okno jest partycjonowane po kandydacie, więc LAG widzi komplet ruchów pary). Wiersze rysuje
  wspólny `recruitment/JobMoveLog.tsx` (także okno „Historia i czat”). W kluczu zapytania jest id wiersza etapu
  karty, więc po ruchu lista odświeża się sama. Przeglądarka dodatkowo filtruje po `candidate_id`, bo serwer
  sprzed filtra oddałby ruchy wszystkich osób. Fakty z karty („Dodany do rekrutacji”) zostają tylko jako zapas,
  gdy dziennik nie ma wiersza tej osoby.
- **Awaria notatek to jeden komunikat z „Ponów”** dla obu sekcji; pusty stan („Jeszcze nic nie zapisano”,
  „Nie ma wcześniejszych notatek o tej osobie”) wisi na udanym odczycie.
- Harness: `/preview/job-detail` — pierwsza karta „Nowych” ma fikcyjną historię
  (`app/preview/person-history-fixtures.ts`), druga notatkę tylko w tej rekrutacji, reszta jest pusta.

Poza zakresem, do decyzji: podpięcie luźnych notatek z Traffita do rekrutacji
(`POST /api/admin/traffit/notes-repair/recruitments` — zapis na produkcji; po scaleniu bliźniaków podpiąłby
notatkę do zamkniętej kopii) oraz 12 notatek, które po scaleniu 27 duplikatów zostały na zamkniętych kopiach
(8 otwartych kart).
