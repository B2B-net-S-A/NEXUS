# Znacznik „Pracuje u nas” przy dodawaniu do rekrutacji (12–13.10.2026)

Zgłoszenie Artura: osobę, która u nas pracuje (umowa + zamówienie), dało się
wyszukać i dodać do rekrutacji, a nigdzie po drodze nie było widać, że
pracuje — dopiero na profilu. Makiety (8 plansz) i decyzje D1–D5:
https://claude.ai/artifact/QekWy3zx3pXNEKDKQmikf6. Reguły dla kolejnych
zmian: `docs/claude/kandydaci-wyszukiwanie/znacznik-pracuje-u-nas.md`.

Stan sprzed zmiany (odczyt kodu): pole `employment` było w API listy
i profilu, ale czytał je tylko profil, szybki podgląd i kolumna „W procesie”
listy. Okna dodawania, karta Tablicy, panel osoby, „Potwierdź zatrudnienie”,
wyszukiwarka z górnego paska i Talent Radar go nie pokazywały. Ostrzeżenie
przy dodawaniu działało tylko dla klienta tej samej rekrutacji.

## Co się zmieniło

| Obszar | Zmiana |
|---|---|
| Reguła | `services/employment_marker.py`: jedna czysta `build_markers` — fazy „pracuje” / „kończy u nas” / „zaczyna u nas”, klient, koniec łańcucha zamówień, Delivery Lead klienta. Pole `employment_marker` w odpowiedziach listy, szczegółów i szybkiego podglądu kandydata, wyszukiwarki, Tablicy, propozycji, Talent Radaru, przeglądu bazy i „Moich ludzi”. |
| Lista Kandydaci | Znacznik pod nazwiskiem; „W procesie” wraca do liczby rekrutacji w toku. Filtr „Dostępność”: „Pracuje u nas” i nowa odpowiedź „Kończy u nas w ciągu 60 dni” (`employment=ending_soon`). |
| Okna dodawania | „Dodaj po nazwisku”, „Kandydaci do dodania” (lista, podgląd osoby, tabela i panel propozycji), „Przypisz do rekrutacji” (ramka + plakietka „ten sam klient”), „Dodaj do rekrutacji” dla kilku osób („N z M osób pracują u nas”, „Dodaj bez tych osób”). Ramka informuje, niczego nie blokuje (D2). Okno „Dodaj do rekrutacji” łączy to z wynikiem i „Przywróć” z #2151: ramka jest w widoku wyboru rekrutacji, a toast po dodaniu wymienia powody pominięcia i ostrzeżenia. |
| Tablica i panel osoby | Wiersz znacznika na karcie; krótka pigułka w głowie panelu, szczegóły w dymku. |
| Wyszukiwarki | Znacznik w wynikach wyszukiwarki z górnego paska, na karcie Talent Radaru i w przeglądzie bazy. |
| „Moi ludzie” (D5) | Osobę z grupy „Pracują” można dodać do rekrutacji; wiersz mówi, u kogo pracuje. Automat dopasowań dalej pomija pracujących. |
| Zatrudnienie (D3) | „Potwierdź zatrudnienie” pyta „Co z obecną współpracą?”, gdy osoba ma trwającą umowę u innego klienta. Odpowiedź trafia do historii ruchu, na oś czasu profilu i do dzwonka. Umów ani zamówień nie zmienia. |
| Dzwonek (D3, D4) | Nowy typ `consultant_in_other_recruitment` (migracja 0430, własna grupa do wyciszenia w „Kontrakty, zamówienia i podpisy”): Delivery Lead klienta, u którego osoba pracuje, dostaje powiadomienie, gdy jej CV idzie do innego klienta (raz na parę) albo gdy zostaje tam zatrudniona. Samo dodanie do rekrutacji nie dzwoni. |
| Pomoc | Pięć przewodników Jarvisa (lista, Tablica, karta kandydata, profil, „Do przejrzenia”) mówi, co znaczy znacznik; sześć wpisów inwentarza funkcji. |

## Znalezione po drodze i naprawione

- **Rozjechane definicje „pracuje”.** Profil i lista nie sprawdzały daty
  startu umowy, dopuszczalność i „Moi ludzie” — tak. Znacznik rozdziela to
  fazami („zaczyna” = umowa podpisana, start w przyszłości); stare pole
  `employment` zostaje i znaczy „nasza osoba” (inaczej osoba z podpisaną
  umową wpadłaby do filtra „Otwarci”). Niezmiennik w teście.
- **Tablica nie rysowała ostrzeżeń, które dostawała.** Serwer wysyłał kody
  konfliktu z klientem w `warnings`, karta pokazywała tylko weto HM
  i „ponad budżet”. Teraz NDA, czarna lista klienta, konkurent, wykluczenie
  klienta i czarna lista mają odznaki na karcie i w wierszu tabeli.
- **Okno „Dodaj do rekrutacji” gubiło ostrzeżenia z odpowiedzi serwera** —
  podsumowanie liczyło tylko dodanych i pominiętych.
- **Martwy kod:** komponent `CandidateHighlights` (plakietka „U KLIENTA”,
  nigdzie nierenderowany) i dwie nieużywane listy opcji zatrudnienia —
  usunięte.
- **Ramka na profilu pokazywała datę w formacie ISO** — teraz DD.MM.RRRR.
- **Przegląd Delivery Leada** liczył „dziś” dla zatrudnienia z daty UTC —
  teraz kalendarzem firmy.

## Odstępstwa od makiet i planu

- **Panel osoby (makieta 4):** krótka pigułka w rzędzie odznak i ramka
  w dymku zamiast stałej ramki — test wysokości doku wymaga 350 px
  przewijanej treści przy 1280 × 650.
- **Filtr (makieta 6):** nowa odpowiedź w istniejącej pigułce „Dostępność”
  zamiast osobnego przełącznika — oba sterowałyby tym samym parametrem.
- **Lista (makieta 6):** w wąskiej kolumnie znacznik jest obcinany, pełna
  treść jest w dymku.
- **Lista „Kandydaci do dodania”:** pigułka stoi w rzędzie plakietek pod
  faktami, nie obok nazwiska — nazwa przycisku i linia faktów są tam nazwą
  dostępną wiersza.
- **Bez nowej trasy API** dla okna masowego (plan zakładał trasę): okno
  dostaje osoby pracujące od ekranu, który je otwiera. Skutek: zaznaczenie
  odtworzone z adresu dla osób spoza wczytanych stron listy nie ma danych do
  ramki (po dodaniu podsumowanie i tak mówi o ostrzeżeniach z serwera).
- **Ruch zbiorczy:** znacznik i odbiorcy dzwonka są liczeni per karta, nie
  raz na paczkę — zapytania idą tylko dla kart wchodzących na „CV wysłane”
  albo „Zatrudniony”.
- **D4:** „ewentualnie przy CV wysłane” z decyzji wdrożone jako dzwonek do
  Delivery Leada obecnego klienta, raz na parę osoba–rekrutacja.

## Weryfikacja

- **Pełny bieg CI na gałęzi** (`gh workflow run CI --ref feat/employment-marker`):
  bieg 38316593108 na `8f1a6c5fc` zielony — 12 shardów pytest z Postgresem,
  front (lint, type-check, build, vitest z pokryciem), Trivy. Pierwszy bieg
  (38314126573) złapał dwa testy z atrapą bazy, które nie znały zapytania
  o znacznik (`test_candidate_search_api.py`, `test_full_search_page_telemetry.py`),
  i stemple przewodników sprzed restempla — poprawione przed drugim biegiem.
- **E2E na gałęzi** (`e2e.yml`): bieg 38316596765 na `8f1a6c5fc` zielony;
  harnessy `/preview/*` 158/158, w tym pięć testów panelu osoby przy
  1280 × 650 (wysokość przewijanej treści ≥ 350 px).
- **Po drugim scaleniu maina** (#2151 i #2152 zmieniły to samo okno „Dodaj do
  rekrutacji”, panel osoby, stempel i inwentarz): lokalnie type-check,
  vitest 48 plików / 1071 testów (panel osoby, ruch karty, inwentarz,
  dane harnessów), `check_stamps.py`, indeks reguł, `check-unreachable-modules`,
  `lint:tokens`, ruff. Pełny pytest tego stanu biegnie w kolejce merge'ów.
- **Przeglądarka:** harness listy kandydatów na `next dev` — znacznik pod
  nazwiskiem widoczny na zrzucie. Pozostałych ekranów lokalnie nie
  przeklikałem (patrz „Niepotwierdzone”).

## Przegląd kodu przed PR-em

| Część | Stan | Dowód |
|---|---|---|
| Przegląd kodu (subagent) | 1 bloker, naprawiony | Gałąź była commit za mainem z konfliktem w `stamps/jobs.person.json` i `recruitment-feature-inventory.json` — sprawdzone `git status` po scaleniu (oba pliki `UU`); scalone, przewodnik przestemplowany, `check_stamps.py` kod 0. |
| Uwaga z przeglądu kodu | wdrożona | Błąd bazy w nowym dzwonku zostawiał transakcję przerwaną dla zwykłych dzwonków ruchu (`consultant_elsewhere_notifications.py`, wołany jako pierwszy w `notify_stage_change`). Savepoint + test `test_a_database_error_in_the_bell_leaves_the_session_usable`. |
| Przegląd bezpieczeństwa (subagent) | bez blokerów | Bramki tras, `elsewhere` tylko przy dostępie do rekrutacji, odbiorcy i treść dzwonka, `Literal` w ładunku ruchu, zapytania parametryzowane — czytane z kodu, bez uruchamiania. |
| Znacznik a dostęp do zamówień | decyzja zapisana | Rekruter widzi przez znacznik koniec zamówienia i Delivery Leada, choć do zamówień w Delivery dostępu nie ma; filtr „Kończy u nas w ciągu 60 dni” daje taką listę dla całej bazy. Tak było na zatwierdzonych makietach — dopisane do reguł jako granica: żadnych stawek, numerów ani treści zamówień w znaczniku. |
| Trasy radaru a stara rola `user` | poza zakresem, zgłoszone | `POST /api/talent-radar/search`, `/api/candidate-search/*` i propozycje mają tylko bramkę sekcji; luka sprzed tej zmiany, osobne zadanie. |

## Niepotwierdzone

- **Przeklikanie w przeglądarce** poza listą kandydatów: `next dev` zapełnił
  dysk komputera (poniżej 1 GB wolnego), serwer został zatrzymany. Okna
  dodawania, Tablica, panel osoby i „Potwierdź zatrudnienie” mają testy
  komponentów i zielone E2E harnessów; przeklikanie na produkcji ze zrzutem
  po wdrożeniu.
- **Dane produkcyjne:** ile osób dostanie znacznik i ile jest w fazie „kończy”
  — odczyt produkcji wymaga zgody Artura, nie był robiony.
- **Liczba kont ze starą rolą `user`** — nie sprawdzana (to samo).
- **Test savepointu** ma dowód tylko z CI; czerwonego stanu sprzed poprawki
  nie odtworzyłem (lokalnie nie ma bazy).

## Poza zakresem

- Drugi silnik wyszukiwania (`POST /api/search/candidates`) nie ma filtra
  zatrudnienia — tak jak przed zmianą.
- Narzędzie Jarvisa do ruchu karty nie pyta o obecną współpracę (dzwonek do
  Delivery Leada i tak idzie, bez odpowiedzi).
- Zakładka „Kończące się 30d” liczy grupy zamówień MD na froncie u każdego
  klienta, alerty tylko u klientów z listy rozszerzonej — rozjazd sprzed tej
  zmiany; znacznik idzie za alertami.
- Kolory wpisane na sztywno w oknie „Przypisz do rekrutacji”
  (`QuickAssignV2.tsx`) — zostały, jak były.
