# Karta na Tablicy w trzech wierszach, jedna liczba dni i nagłówek w jednym rzędzie (08.11.2026)
<!-- indeks: audyt 2, tezy U1 U3 U5, `cardPrimaryBadges`, „+N”, `waiting_workdays`, „Szukaj ▾”, „Kto dodał” na pasku rekrutacji, baner CPro zwinięty, wyjątek: dwie linie przy oknie < 800 px (`low-screen:`) -->

Decyzja Artura z 08.11.2026 („2 plakietki + „+N””), audyt 2:
https://claude.ai/artifact/VXHZFJQZQbNRXAVGzNfdCu. Przy 1280 × 720 rekruter
widział 6 pełnych kart z 51, a Delivery Lead 5 ze 152, bo karta miała do 9
plakietek i trzy różne liczby dni.

## Karta

- **Wiersz 1:** numer kolejki, imię i nazwisko w jednej linii (pełne w dymku),
  pod nimi imię właściciela (kto, kiedy i dlaczego: dymek), pierścień obok.
  Imię zamiast inicjałów od 09.11.2026, po zgłoszeniu Delivery Leada: kółko 16 px
  z czcionką 7 px było nieczytelne. Decyzja Artura z makiet (wariant A): karta
  o 5 px wyższa przy 1280 × 720, plakietki bez zmian. Nie wstawiaj imienia do
  wiersza plakietek (ucina je) ani obok nazwiska (zostają 3–4 litery kandydata).
- **Wiersz 2:** najwyżej dwie plakietki z `cardPrimaryBadges`
  (`lib/board-card-badges.ts`). Reszta idzie do „+N”: dymek (natywny `title`)
  i okienko po kliknięciu z pełną treścią i przyciskami (QC, Scorecard,
  Screening, „+1 rekrutacja”). Treści się nie kasuje, tylko przenosi.
- **Priorytet jest stały:** blokery (weto HM, czarna lista, off-limits), potem
  ruch z terminem (Champion, umówiony telefon, follow-up, cudza blokada, „QC: N
  do poprawy”…), potem ostrzeżenia (ponad budżet, brak krytycznej, cautions),
  potem stan. Nie dokładaj nowej plakietki przed blokerami, dopisz ją do
  `WITHIN_GROUP` i `badgeGroup`.
- **Tylko w „+N”, także gdy jest miejsce:** `autofill_due`, `new_in_base`,
  `other_jobs`, fakty kolejki („U klienta 3×”, „Jeszcze bez procesu”), ocena,
  status kontaktu. Te same fakty są w panelu osoby (`dock-autofill-known`).
- **Wiersz 3:** kto ma ruch i krok albo jeden przycisk (Przejrzyj i wyślij,
  Dzwonię/Biorę/Przejmij, Zaznacz akceptację, Uzupełnij screening), jedna liczba
  dni i strzałka. Plakietki `dl_review` na karcie nie ma: mówi to przycisk.

W widoku przeglądowym (kafelek, ponad 10 kolumn) wiersza plakietek i ruchu nie
ma, zostaje ikona screeningu, resztę daje klik w kafelek i panel osoby.

## Wyjątek: dwie linie przy oknie niższym niż 800 px (23.11.2026)

Decyzja Artura z 23.11.2026 po analizie dnia rekrutera
(https://claude.ai/artifact/Bf7wiygZoxpTPq9G8oHgiL, „4 · Karta w dwóch
liniach”). Przy 1280 × 720 nad Tablicą jest ok. 330 px nagłówka, a karta
w trzech wierszach miała 104–117 px: w „Nowych” było widać 2,6 karty z 43,
w „Screeningu” 3 z 8 (Tablica 758737 na stagingu, konto rekrutera).
W dwóch liniach karta ma 52 px i widać 5,2 i 6 kart. **Na oknie od 800 px
w górę karta zostaje w trzech wierszach** — tego nie zmieniaj „przy okazji”.

- **Próg to media query, nie hak:** wariant `low-screen:` w `globals.css`
  (`max-height: 799px` i `pointer: fine`). Hak na `innerHeight` dawał skok
  karty przy hydracji, bo serwer nie zna okna. Dotyk zostaje przy trzech
  wierszach: bez najechania podpowiedź stanu byłaby nieosiągalna.
- **Linia 1:** imię i nazwisko, pierścień 20 px zamiast 28. Imię właściciela
  schodzi do dymku karty.
- **Linia 2:** przycisk („Biorę”, „Dzwonię”, „Przejrzyj i wyślij”…) albo „kto
  ma ruch” z krokiem, liczba dni jako „4 d” w tych samych kolorach, jeden stan
  (`card-low-state`) i strzałka. Stan to pierwsza plakietka z
  `cardPrimaryBadges`, a „+N” mówi, ile jest reszty; to, co stoi wyłącznie
  w „+N”, nie wchodzi na stan także tutaj.
- **Nic nie znika:** wiersz plakietek ma `low-screen:hidden`, ale wszystkie
  plakietki z treścią i „Dla:/Prowadzi:” są w podpowiedzi stanu
  (`twoLineStateTitle`), w dymku karty i w panelu osoby. Numer „Zadzwoń
  najpierw” zostaje w rogu karty. Przyciski z plakietek (QC, Scorecard,
  Screening, „+1 rekrutacja”) są w panelu osoby.
- Zaznaczanie, przeciąganie, strzałka z „Cofnij” i nazwy dostępne karty bez
  zmian. W widoku przeglądowym (kafelek) wariant nie działa.
- jsdom nie liczy CSS, więc oba układy są w DOM naraz; testy
  (`KanbanBoardV2.test.tsx`, „karta w dwóch liniach”) sprawdzają klasy.

## Jedna liczba dni (U5)

- `waiting_workdays` w odpowiedzi tablicy liczy serwer:
  `dl_send_queue.board_waiting_workdays`, ta sama funkcja co pas „Do wysłania do
  klienta” (karta gotowa w „QC CV” od `max(moved_at, qc.ok_at)`), a osoba od
  systemu od terminu decyzji (`entry_autofill.waiting_days`), karta u klienta
  z zegara ciszy (`client_wait.client_clocks`, ten sam co „Klient milczy”, więc
  „Klient odpowiedział” zeruje też wiersz ruchu). Reszta od wejścia
  na etap. 0 dni nie ma napisu, a zatrudniony i zamknięty nie mają liczby
  (`None`), bo proces się skończył.
- Na karcie stoi raz: „czeka 2 dni rob.” (przy przycisku „2 dni rob.”). Liczby
  kalendarzowe („44 dni bez odpowiedzi”, „Czeka na Ciebie · 2 dni”, „zaległy 31
  dni”) zeszły do dymku; dni kalendarzowe zostają w „na etapie od 03.11”.
- „najstarszy N d rob.” w nagłówku kolumny i „czeka N dni rob.” przy następnej
  osobie biorą tę samą liczbę z serwera. „Bez decyzji” nie ma liczby, bo stoi
  ona w wierszu ruchu, a „Nowy · od 28.10” mówi datą, bo to wiek w bazie, nie
  czekanie.
- Nie licz dni na froncie z `moved_at`: tak powstały trzy arytmetyki na jednej
  karcie (`dlWaitingDays`, `days_in_stage`, `waitingFor`).

## Nagłówek (U3)

- Źródła w jednym rzędzie: kafle „Nowi z ogłoszeń” (z liczbą), „Moi ludzie”,
  „Aplikacje”, potem menu „Szukaj ▾” (Podobne rekrutacje, Propozycje z bazy,
  Szukaj w bazie, „Otwarte podobne”) bez liczb, z opisem pod pozycją.
  Bliźniak (chip i „⇄ Połącz bliźniaka”) od 10.11.2026 stoi za „Dodaj” na
  końcu rzędu, nie w menu — `blizniacze-rekrutacje-jeden-screening-pod-kilka.md`.
  Liczby 2080 i 6823 nie były do decyzji. Menu to popover, nie `DropdownMenu`,
  bo w środku kafle mają własne okienka.
- „Kto dodał” stoi na stałe po prawej w linii źródeł (`AddedByFilterButton`,
  wysokość kafli obok), a włączony pokazuje wybór, „N z M” i „✕”. Decyzja Artura
  z makiet z 09.11.2026 (wariant A): filtr działa na wszystkie kolumny, a ikona
  w nagłówku kolumny „Nowi” (08.11.2026) wyglądała jak filtr samych „Nowych”.
  Nie wracaj z nim do kolumny.
- W zwiniętym nagłówku filtr to sama ikona obok „⋯” (`AddedByCompactFilter`),
  podświetlona przy włączonym filtrze, a „Profil Championa” skraca się do ikony.
  Pełny przycisk w linii tytułu przy 1280 px wchodził pod „Tablicę” i na status.
- `JobCproBanner` zwinięty do jednej linii z „Pokaż”; po otwarciu i 7 dni po
  najnowszym zdarzeniu CPro znika (pamięć w przeglądarce per rekrutacja), nowe
  odrzucenie pokazuje go znowu. „Zmień powód” i „Otwórz ponownie” są też w „⋯”.
