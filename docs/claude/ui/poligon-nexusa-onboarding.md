# Poligon NEXUSA — onboarding pierwszego dnia na rekrutacji ćwiczebnej
<!-- indeks: `/poligon`, jedna ścieżka 19 ćwiczeń, blokada nowej osoby zamiast Startu, dzień onboardingu poza statystykami (`onboarding_day`), tryb w przeglądarce (`lib/poligon/`), zapisy nie wychodzą do API poza postępem `poligon-*`, zestaw z `build_poligon_dataset.py`, strażnik `poligon-dataset.test.ts` -->

Decyzje Artura z 14.11.2026 (makiety: https://claude.ai/artifact/FQGjXqm7T4Bpoi4fYCpmsk).
Co miesiąc dochodzi 7–14 nowych kont i każdą osobę HoR szkolił osobno. Start
w NEXUSIE (`start-w-nexusie.md`) idzie po prawdziwych danych, więc 7 z 15 kroków
rekrutera kończyło się przyciskiem „Rozumiem” zamiast wykonaniem. Na poligonie
osoba naprawdę przesuwa karty, wypełnia screening, odrzuca i przypisuje z bazy —
na wymyślonych danych.

## Jedna ścieżka, cała pierwszego dnia

- **Bez poziomów i egzaminów** (Artur, 14.11.2026, drugie podejście): wszystko
  od razu w onboardingu. 19 ćwiczeń w 6 modułach (`lib/poligon/exercises.ts`):
  lista rekrutacji, Tablica (Biorę, ruch, źródła, Moi ludzie), panel osoby
  (notatka, „@”, odrzucenie z powodem), screening i weryfikacja (formularz,
  bramka „Zweryfikowany”, zapis, weryfikacja), rekomendacja (CV dla klienta,
  QC CV) i baza kandydatów (szukanie, profil, przypisanie).
- **Blokuje pracę nowej osoby.** `GET /api/novelties/start` zwraca `poligon`
  i `redirect`. Rekruter z kontem od `required_since` (`poligon.json`) jest
  zatrzymany (`useStartGate`) i prowadzony na `/poligon`, dopóki nie zaliczy
  wszystkich ćwiczeń. Poligon zastępuje mu przeklikania Startu z `replaces`.
  Obecne osoby mogą wejść na mapę, ale poligon ich nie blokuje.
  Wyłącznik Startu (`app_settings.start_gate`) i podgląd jako inna osoba
  zdejmują też tę blokadę.
- **Dzień onboardingu nie liczy się do statystyk.** To dzień (Europe/Warsaw)
  pierwszego zaliczonego ćwiczenia, tylko u osoby, której poligon jest
  wymagany (`app/services/onboarding_day.py`). Taki dzień nie jest dniem pracy
  w żadnym mianowniku ani w żadnej normie:
  - `person_workdays.absence_by_user` (przy każdym źródle urlopów), co obejmuje
    Weryf./dz., cele KPI i Rytm;
  - `kpi_engine.personal_days_off` (tempo);
  - próg i plakietka Wyścigu Rekomendacji;
  - Porcja dnia: tego dnia osoba nie dostaje porcji (`review_batch.absent_today`).

  Rytm liczy osobę od dnia następnego. Weryfikacje i rekomendacje zrobione
  mimo to tego dnia liczą się normalnie, bo to prawdziwa praca.
- **Postęp na serwerze.** `novelty_progress` z id `poligon-…`, zdarzenie
  `used` na `POST /api/novelties/{id}/events` (bez nowej trasy i bez migracji).
  Rejestr id: `backend/app/data/novelties/poligon.json`. Test frontu pilnuje,
  że ma te same id co `exercises.ts`. `localStorage` służy tylko jako pamięć
  podręczna mapy.

## Jak działa tryb

- **Tryb w przeglądarce, nie osobna baza.** `sessionStorage["nexus.poligon"]`
  włącza w `lib/api.ts` adapter `lib/poligon/adapter.ts`.
  - Zestaw `lib/poligon/dataset.json` podaje:
    - odczyty o rekrutacji ćwiczebnej (identyfikatory 990000+);
    - `/api/jobs`;
    - bazę kandydatów (`/api/candidates` = 14 osób ćwiczebnych);
    - „Moi ludzie”;
    - listę do „@” (trenerzy poligonu).
  - Pozostałe odczyty, np. pasek górny, idą do API.
  - **Jedyny zapis, który wychodzi z przeglądarki, to zaliczone ćwiczenie**
    (`POLIGON_PROGRESS` w `store.ts`).
  - Ruch karty, „Biorę”, notatka, screening (`PUT /api/screening-form`)
    i przypisanie z profilu zmieniają tylko stan w pamięci. Reszta dostaje 409
    z komunikatem.
- **Bramka „Zweryfikowany” jest w `store.ts`**: ten sam zestaw braków co serwer
  (arkusz, lokalizacja, tryb pracy, „Dlaczego ten kandydat”). Liczy go
  i okno „Przesuń dalej” (`move-requirements`), i odmowa 409
  `VERIFIED_REQUIREMENTS_MISSING`. Zmiana reguły na serwerze
  (`pipeline_move_rules.py`) = przegląd tej kopii.
- **Ćwiczenia** zalicza zdarzenie, nigdy „Rozumiem”:
  - klik w kotwicę `data-tour`/`data-help`;
  - akcja na rekrutacji ćwiczebnej;
  - otwarcie ekranu (zdarzenie `view` z odczytu).

  Informacja zwrotna to stałe reguły, bez modelu AI.
- **Warstwa** `components/poligon/PoligonLayer.tsx`:
  - żółty pasek „Poligon” nad treścią;
  - okno ćwiczenia w lewym dolnym rogu, które da się zwinąć; nie zasłania
    panelu osoby po prawej.

  W trybie poligonu `NoveltyLayer` milczy, a `useStartGate` nie blokuje.

## Zestaw danych

- Buduje go `backend/scripts/build_poligon_dataset.py` z nagrania na stagingu
  z laptopa, zrobionego jednym kontem rekrutera. Nagranie obejmuje:
  - listę rekrutacji;
  - Tablicę;
  - panel osoby ze wszystkimi zakładkami, w tym „Screening”;
  - pasek źródeł;
  - „Moi ludzie”;
  - bazę kandydatów;
  - profil i okno przypisania.

  Nagranie ma prawdziwe dane i zostaje w scratchpadzie sesji, nigdy w repo.
- Repo jest publiczne. Skrypt zamienia:
  - osoby na wymyślone (`PEOPLE`, trenerzy „Anna Poligonowa”,
    „Jakub Szkoleniowy”);
  - firmę na „Bank Północny”;
  - CV osoby na CV ćwiczebne;
  - identyfikatory na zakres 990000+;
  - daty na względne (`@rel:-3.2`).

  Tekst spoza `safe-keys.json` znika, a tekst spod tych kluczy przechodzi przez
  filtr prawdziwych imion, nazwisk i firm z nagrania. Gdy ekran nie znosi
  `null`, wycięty tekst zastępuje stała `REQUIRED_TEXT` (np. pytanie
  screeningowe z nazwą klienta). Pozycję listy bez nazwy skrypt usuwa
  (`prune_dropped`).
- **Strażnik** `lib/poligon/__tests__/poligon-dataset.test.ts` pilnuje, że
  w zestawie nie ma:
  - e-maili;
  - telefonów;
  - adresów WWW;
  - tekstów spoza dozwolonych kluczy.

  Nowy klucz do `safe-keys.json` dopisujesz tylko dla etykiet interfejsu
  i treści rekrutacji, nigdy dla notatek, CV ani osób.
- **Ekran zmienił się od nagrania:** adapter pisze w konsoli
  `[poligon] brak odpowiedzi w zestawie: <adres>`. Wtedy nagraj ekran jeszcze raz
  i przebuduj zestaw (opis wywołania w nagłówku skryptu). Przed commitem
  przejrzyj `--report` i przejdź całą ścieżkę w przeglądarce.
- **Test całej ścieżki w CI** (`frontend/e2e/poligon-walk.spec.ts`, projekt
  `poligon-chromium`, od 15.11.2026). W kolejce merge'ów po buildzie frontendu
  przechodzi 19 ćwiczeń na podstawionym backendzie (bez bazy). Pada na każdy brak
  w zestawie, zapis poza postępem `poligon-*` i błąd strony, bo taki brak blokuje
  nową osobę na cały dzień. Odczyt, na który serwer odpowiada 404 (np.
  rekrutacja bez migawki rekomendacji), zapisuje się w zestawie jako
  `{"@status": 404}`, nie jako brak. Powłoka (pasek, powiadomienia) dostaje 404,
  poza szablonem etapów z `e2e/fixtures/poligon-shell.json`. Nowe ćwiczenie
  dopisujesz też do tego testu.
- Stan poligonu żyje w pamięci karty: przeładowanie strony cofa ruchy,
  notatki i screening z ćwiczeń (postęp ćwiczeń zostaje).
- Nowe ćwiczenie dopisujesz w czterech miejscach:
  - `exercises.ts`;
  - `poligon.json` (to samo id z przedrostkiem `poligon-`);
  - test oceny w `store.test.ts`;
  - krok w `e2e/poligon-walk.spec.ts`.
