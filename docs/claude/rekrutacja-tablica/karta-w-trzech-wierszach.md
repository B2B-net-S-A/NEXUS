# Karta na Tablicy w trzech wierszach, jedna liczba dni i nagłówek w jednym rzędzie (08.11.2026)
<!-- indeks: audyt 2, tezy U1 U3 U5, `cardPrimaryBadges`, „+N”, `waiting_workdays`, „Szukaj ▾”, „Kto dodał” w kolumnie „Nowi”, baner CPro zwinięty -->

Decyzja Artura z 08.11.2026 („2 plakietki + „+N””), audyt 2:
https://claude.ai/artifact/VXHZFJQZQbNRXAVGzNfdCu. Przy 1280 × 720 rekruter
widział 6 pełnych kart z 51, a Delivery Lead 5 ze 152, bo karta miała do 9
plakietek i trzy różne liczby dni.

## Karta

- **Wiersz 1:** numer kolejki, imię i nazwisko w jednej linii (pełne w dymku),
  inicjały właściciela (kto, kiedy i dlaczego: dymek), pierścień.
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
  Szukaj w bazie, „Otwarte podobne”, bliźniak) bez liczb, z opisem pod pozycją.
  Liczby 2080 i 6823 nie były do decyzji. Menu to popover, nie `DropdownMenu`,
  bo w środku kafle mają własne okienka.
- „Kto dodał” to ikona w nagłówku kolumny „Nowi” (`AddedByColumnFilter`).
  Włączony filtr dodatkowo stoi w linii źródeł z „✕”, a w zwiniętym nagłówku
  w linii tytułu. Działa na wszystkie kolumny, jak dotąd.
- `JobCproBanner` zwinięty do jednej linii z „Pokaż”; po otwarciu i 7 dni po
  najnowszym zdarzeniu CPro znika (pamięć w przeglądarce per rekrutacja), nowe
  odrzucenie pokazuje go znowu. „Zmień powód” i „Otwórz ponownie” są też w „⋯”.
