# Przebudowa `/jobs/new` — raport

Data: 02.10.2026. Makiety zaakceptowane przez Artura:
https://claude.ai/artifact/UPDv1tSQBeo5t9kLW6WJoH

## Po co

Panel tworzenia rekrutacji ukrywał trzy sposoby startu (plik i wpisywanie ręczne były
linkami), powtarzał te same dane w kilku polach i nie pokazywał ani kategorii, ani tego,
kto dostanie rekrutację. Pomiar na 20 najnowszych rekrutacjach z produkcji (02.10.2026):

| Co | Wynik |
|---|---|
| must-have wpisane jako zdanie, nie technologia | 53 ze 185 |
| rekrutacje z wybranymi umiejętnościami krytycznymi | 0 z 20 |
| słowa z „wymagań do wyszukiwania” powtarzające must-have | 59% |
| pytania screeningowe z odpowiedzią, która odpada | 3 z 99 |
| tytuł dla rekrutera dłuższy niż 80 znaków | 10 z 20 |

## Co się zmieniło dla Delivery Leada

1. **Krok 1 — źródło.** Klient na górze (wymagany) i trzy kafle: wklej treść requestu,
   wgraj plik, wpisz ręcznie. Próba przejścia dalej bez klienta pokazuje komunikat przy
   polu klienta.
2. **Krok 2 — sześć sekcji** z paskiem, który mówi, w której sekcji czegoś brakuje:
   1. *Nazwa* — nazwa od klienta razem z numerem (numer system czyta sam; „To nie ten
      numer” pozwala go poprawić), rola, hiring manager, podgląd tytułu dla zespołu.
   2. *Wymagania — słowa kluczowe* — jedna lista zamiast trzech pól. Wiersz to wymaganie,
      słowa w wierszu to warianty, poziom: krytyczne / musi mieć / mile widziane. Przy
      wierszu liczba osób w bazie. Zdania klienta („min. 5 lat doświadczenia
      komercyjnego”) zostają w profilu, ale nie filtrują kandydatów.
   3. *Warunki* — budżet, tryb pracy, biuro, start, długość projektu.
   4. *O projekcie* — dwa zdania i „co przekona kandydata”.
   5. *Pytania do kandydata* — pytanie, dobra odpowiedź i odpowiedź, która odpada
      (wymagana). AI proponuje komplet, Delivery Lead poprawia albo zatwierdza.
   6. *Kategoria i zespół* — potwierdzenie kategorii kompetencji, rekruter prowadzący
      (automat albo wskazany ręcznie), priorytet.
3. **Bez „Fraz do LinkedIna”**, bez osobnego pola „Numer u klienta”, bez „Kolejnych osób”.

## Co się zmieniło w działaniu systemu

- **Uczestnicy rekrutacji = wszystkie osoby z jej kategorii** (1. i 2. priorytet), dopisywane
  w tle. Widzą rekrutację w „Moja kategoria” i dostają jej powiadomienia; nie są
  „Rekruterem”. Lista idzie za zmianą kategorii rekrutacji i składu kategorii, a raz na
  godzinę wyrównuje resztę przypadków. Osoba zdjęta ręcznie nie wraca.
- **Rekruter prowadzący**: w trybie `auto` automat przydziela od razu, bez akceptacji
  i bez danych o urlopach (blokuje go tylko włączony i nieaktualny Compass). Przypisana
  osoba dostaje dzwonek od razu.
- **Head of Recruitment** ma w „Czeka na Ciebie” listę „Nowe rekrutacje — kto prowadzi”
  z przyciskiem „Zmień”.
- **Wymagania zapisują się jako wiersze** (`stack.rows`); must-have, krytyczne i wiersze
  wyszukiwania serwer wyprowadza z nich sam, więc scoring, bramka krytycznych, QC CV
  i generator CV czytają to, co dotąd.
- **„Szukaj ręcznie”** dla rekrutacji z wierszami wymaga tylko wierszy krytycznych;
  pozostałe podnoszą w kolejności.
- **„Przekaż do searchu”** wymaga odpowiedzi, która odpada, przy każdym pytaniu — tylko dla
  rekrutacji jeszcze nieprzekazanych.
- **Odczyt maila (prompt v10)** oddaje wymagania jako słowa kluczowe i proponuje deal
  breaker do każdego pytania.
- **Profil Championa**: profil z wierszami ma ten sam edytor co `/jobs/new`; starszy profil
  ma przycisk „Uprość do słów kluczowych”. Kategorię zmienia w panelu „Zespół” osoba
  z pełną edycją rekrutacji.

Bez migracji bazy: wiersze żyją w JSONB profilu, uczestnicy w istniejącej tabeli
`job_collaborators`.

## Odstępstwa od makiet

- Sekcja 1 ma osobne pole „Rola” (makieta go nie pokazywała) — rola jest wymagana przez
  bramkę i z niej system podpowiada kategorię.
- „Podobne rekrutacje” zostały widoczną kartą pod formularzem, a nie pozycją w „Dodatkowe”
  — schowane traciłyby użycie, a łączenie i tak wymaga zaznaczenia ręką.
- Link „skopiuj wcześniejszą rekrutację” w kroku 1 nie powstał — jest „Skopiuj jako
  template” z historii requestów (`?from=`).
- Na liście Heada nie ma zakładek „Dziś / Ten tydzień / Zmienione przeze mnie” ani paska
  obłożenia kategorii — lista pokazuje rekrutacje z ostatnich 7 dni; obłożenie jest na
  pulpicie „Requesty i obłożenie”.

## Poza zakresem

- Wzór Word Championa i import dokumentu nadal znają „frazy do wyszukiwarki” (dane zostają,
  pole jest ukryte).
- Stare rekrutacje nie są przepisywane na wiersze — robi to „Uprość do słów kluczowych”,
  gdy ktoś otworzy profil.

## Weryfikacja

Przed otwarciem PR-a (02–03.10.2026):

| Część | Stan | Dowód |
|---|---|---|
| Backend | zielony | pełne CI na gałęzi (`workflow_dispatch`, bieg 37063338198): 12 shardów pytest + scalenie pokrycia |
| Frontend — typy i lint | zielony | `tsc --noEmit` całego frontu, `eslint` 44 zmienionych plików |
| Frontend — testy | zielony | Vitest: formularz (`NewJobPage` 60, `job-request-intake`, `requirement-rows`, `RequirementRowsEditor`), edytor Championa, „Szukaj ręcznie”, strażnicy harnessów i inwentarza funkcji |
| `/jobs/new` w przeglądarce | obejrzane | harness `/preview/new-job` przy 1280×720: `request`, `noclient` (komunikat po kliknięciu), `manual`, `review`, `gaps`, `shadow`, `off`; `review` przy 390 px bez poziomego przewijania |
| Profil Championa z wierszami | obejrzane | harness `/preview/champion-profile`, przypadek 4, 1280×720 i 390 px |
| Przegląd kodu | dwa przeglądy (backend, frontend) | backend bez blokerów; frontend: jeden błąd, poprawiony niżej |

Poprawione po przeglądzie i testach:

- „To nie ten numer” z pustym polem zapisywało numer z nazwy mimo decyzji „bez numeru”
  (formularz nie wysyłał pola, serwer czytał numer z tytułu). Formularz wysyła teraz puste
  pole, a serwer czyta numer z nazwy tylko, gdy pola w żądaniu nie ma.
- Zaraz po odczycie requestu strona pytała o kategorię dla pustej roli: podpowiedź migała
  i znikała po 0,6 s (testy formularza padały przez to losowo). Zapytanie idzie teraz tylko
  dla roli, która stoi w polu; ponowny odczyt tego samego requestu znowu podpowiada kategorię.
- Zmiana kategorii w edycji rekrutacji: błąd synchronizacji uczestników nie cofa już zapisu
  (listę wyrówna pętla godzinowa).

Świadomie zostawione (nie blokuje):

- Uczestnik z kategorii liczy się jak osoba przypisana do rekrutacji klienta
  (`client_access`), więc widzi klientów otwartych rekrutacji swojej kategorii — tak było
  dla 1. priorytetu, teraz dotyczy też 2. Zgodne z decyzją z 23.09 („rekrutacje widzą wszyscy”).
- PUT profilu z samym `stack.rows` bez klucza `critical` (inny klient API niż nasz front)
  zdejmuje zapisany wybór krytycznych.
- Wiersz, którego pierwsze słowo to „tbd”, „n/a” albo „brak”, przenosi profil z powrotem
  na stare pola.
- Import dokumentu Championa na profilu z wierszami nie był osobno sprawdzany w przeglądarce
  (reguła serwera: zapis niezgodny z wierszami kasuje wiersze — pokryta testem).

Po wdrożeniu: wynik sprawdzenia na produkcji i pomiaru odczytu v10 — w opisie PR-a.
