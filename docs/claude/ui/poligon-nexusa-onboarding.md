# Poligon NEXUSA — onboarding na rekrutacji ćwiczebnej
<!-- indeks: `/poligon`, tryb w przeglądarce (`lib/poligon/`), zapisy nie wychodzą do API, zestaw z `build_poligon_dataset.py`, strażnik `poligon-dataset.test.ts`, P1 = poziom 1 -->

Decyzja Artura z 14.11.2026 (makiety: https://claude.ai/artifact/FQGjXqm7T4Bpoi4fYCpmsk).
Co miesiąc dochodzi 7–14 nowych kont i każdą osobę HoR szkolił osobno. Start
w NEXUSIE (`start-w-nexusie.md`) idzie po prawdziwych danych, więc 7 z 15 kroków
rekrutera kończyło się przyciskiem „Rozumiem” zamiast wykonaniem. Na poligonie
osoba naprawdę przesuwa karty, odrzuca i pisze notatki — na wymyślonych danych.

## Jak działa

- **Tryb w przeglądarce, nie osobna baza.** `sessionStorage["nexus.poligon"]`
  włącza w `lib/api.ts` adapter `lib/poligon/adapter.ts`. Odczyty o rekrutacji
  ćwiczebnej (identyfikatory 990000+) i `/api/jobs` podaje zestaw
  `lib/poligon/dataset.json`; pozostałe odczyty (pasek górny, powiadomienia) idą
  do API. **Żaden zapis nie wychodzi z przeglądarki**: ruch karty, „Biorę”
  i notatka zmieniają stan w pamięci (`store.ts`), reszta dostaje 409 z
  komunikatem. Wejście i wyjście przeładowują stronę (czysta pamięć zapytań).
  Odrzucone 14.11: osobna baza ćwiczebna i osobno narysowane ekrany.
- **Ćwiczenia** (`lib/poligon/exercises.ts`) zalicza zdarzenie — klik w kotwicę
  `data-tour`/`data-help` albo ruch na rekrutacji ćwiczebnej — nigdy
  „Rozumiem”. Informacja zwrotna to stałe reguły, bez modelu AI.
- **Warstwa** `components/poligon/PoligonLayer.tsx`: żółty pasek „Poligon” nad
  treścią i panel ćwiczenia w rogu. W trybie poligonu `NoveltyLayer` milczy,
  a `useStartGate` nie blokuje ekranów.
- **Postęp** w P1 trzyma `localStorage` (`progress.ts`). P2 przenosi go do
  `novelty_progress` (id `poligon-*`) i podmienia Start dla nowych osób.

## Zestaw danych

- Buduje go `backend/scripts/build_poligon_dataset.py` z nagrania (lista,
  Tablica, panel osoby) zrobionego na stagingu z laptopa. Nagranie ma prawdziwe
  dane i zostaje w scratchpadzie sesji — nigdy w repo.
- Repo jest publiczne. Skrypt: osoby → wymyślone (`PEOPLE`, trenerzy
  „Anna Poligonowa”, „Jakub Szkoleniowy”), firma → „Bank Północny”, CV osoby →
  CV ćwiczebne, identyfikatory → 990000+, daty → względne (`@rel:-3.2`).
  Tekst spoza `safe-keys.json` znika, a tekst spod tych kluczy przechodzi przez
  filtr prawdziwych imion, nazwisk i firm z nagrania.
- **Strażnik** `lib/poligon/__tests__/poligon-dataset.test.ts`: bez e-maili,
  telefonów, adresów WWW i tekstów spoza dozwolonych kluczy. Nowy klucz do
  `safe-keys.json` dopisujesz tylko dla etykiet interfejsu i treści rekrutacji,
  nigdy dla notatek, CV ani osób.
- **Ekran zmienił się od nagrania:** adapter pisze w konsoli
  `[poligon] brak odpowiedzi w zestawie: <adres>`. Wtedy nagraj ekran jeszcze raz
  i przebuduj zestaw (opis wywołania w nagłówku skryptu), a przed commitem
  przejrzyj `--report`.
