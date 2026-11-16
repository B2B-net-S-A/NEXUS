# Księga NEXUSA K7b (16.11.2026): pensja UoP, chorobowe, urlopowe, ekwiwalent, LP z NEXUSA, porównanie z Enovą

Druga część K7 planu „Księgowość w NEXUSIE” (https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar).
K7a (`ksiega-nexusa-k7a-place.md`) liczy brutto → netto z kwot; K7b liczy samo brutto
osoby na umowie o pracę z pensją i dekretuje listę NEXUSA do księgi. Cel: wyłączyć
Enovę 365 Kadry i Płace po 2–3 miesiącach list liczonych równolegle i zgodnych do
grosza (decyzja Artura z 13.11.2026). Migracja `0719_payroll_salaries`
(`hr_payroll_k7b_schema.py`, lustro przez `hr_schema_bundle`), kod
`backend/app/services/hr/payroll_lists/` (`salary.py` czyste reguły, `uop.py` dane
z bazy, `uop_admin.py` zapis, `ledger_post.py` LP, `enova_compare.py`), ekran
Księgowość → Lista płac → „Pensje i nieobecności”.

## Decyzje Artura z 16.11.2026

1. **Nieobecności z modułu urlopów NEXUSA.** L4 = `sick_leave` z zatwierdzonego
   wniosku; Kadry wpisują każde e-ZLA do NEXUSA (na kopii z 15.11 w całej firmie
   od 05.01.2026 nie było ani jednego L4 — e-ZLA trafiały tylko do Enovy). Płace
   oznaczają przy L4 stawkę: 80% (domyślnie), 100% (ciąża, wypadek w drodze,
   dawstwo), „zasiłek z ZUS od 1. dnia” (np. opieka nad dzieckiem) i zwolnienie
   z okresu wyczekiwania (`payroll_absence_marks`).
2. **Historia podstaw: jednorazowy import 12 miesięcy z Enovy** (`payroll_basis_months`),
   potem NEXUS bierze miesiące z zatwierdzonych list (`basis.k7b.basis`). Miesiąc
   z listą NEXUSA wygrywa z importem — jeden miesiąc, jedno źródło.
3. **Premie z placementów i Ligi poza podstawami** chorobowego i urlopowego
   (art. 41 ustawy zasiłkowej — prawo do premii zostaje w czasie choroby; § 6 pkt 1
   rozporządzenia urlopowego — jednorazowa wypłata za osiągnięcie). Do brutto
   miesiąca wchodzą jak dotąd (`payroll_lines.bonus_total`).
4. **Ręcznie zostają:** Z-3 do ZUS (zasiłek od 34. dnia, od 15. po 50. roku życia,
   płaci ZUS — firma ma do 20 ubezpieczonych chorobowo, art. 61), nadgodziny UoP
   (składnik „zmienne” Płac), zbieg zlecenia z UoP (jak w K7a — kwota Płac).

## Pensja i potrącenia (rozporządzenie MPiPS z 29.05.1996, Dz.U. 2017 poz. 927)

- Pensja (`payroll_salaries`): kwota za pełny miesiąc i etat, od 1. dnia miesiąca,
  poprzednia kończy się dzień wcześniej. Osoba z pensją ma na liście źródło
  `salary`; godziny × stawka z linii Płac nie wchodzą (problem `salary_and_rate`
  bez blokady). Kwota wpisana przez Płace (K7a) dalej wygrywa ze wszystkim.
- Najpierw § 12: nieobecność bez prawa do wynagrodzenia (urlop bezpłatny,
  wychowawczy, opiekuńczy z art. 173¹, okres wyczekiwania na chorobowe, dni poza
  umową) — pensja / godziny wymiaru × godziny nieobecności. Potem § 11: L4
  i zasiłki (także dni zasiłku z ZUS i macierzyński) — pensja / 30 × dni
  kalendarzowe. Każde potrącenie do grosza; cały miesiąc na L4 = 0 zł pensji.
- Wymiar (art. 130 KP): 8 h × etat × dni pon.–pt., minus 8 h za każde święto
  w dniu innym niż niedziela (sobota też). Dzień wolny firmy wymiaru nie obniża.
- Urlop wypoczynkowy, na żądanie, okolicznościowy, art. 188, krwiodawstwo,
  szkoleniowy, odbiór dnia za święto: pensja bez zmian. Siła wyższa (art. 148¹):
  połowa. Rodzaj „inna” — pensja bez zmian i uwaga „sprawdź”.
- FP: warunek płacy minimalnej sprawdza się na całej podstawie składek
  (premie, zmienne, urlopowe, ekwiwalent) z pensją za pełny miesiąc zamiast
  pomniejszonej — „w przeliczeniu na okres miesiąca”.
- Kwota Płac zamiast pensji (K7a) wygrywa z brutto, ale NEXUS i tak liczy
  miesiąc z pensji i zapisuje go w `basis.k7b` z `replaced` (problem
  `salary_replaced`): dni L4 z tego miesiąca liczą się do limitu 33/14 dni,
  a miesiąc wchodzi do historii podstaw. Gdy miesiąca nie da się policzyć —
  problem blokujący `salary_replaced_unknown` (dni chorobowego w otwarciu roku).

## Wynagrodzenie chorobowe (art. 92 KP, ustawa z 25.06.1999)

- Za dni kalendarzowe L4, do 33 dni w roku kalendarzowym; 14 dni od roku
  następującego po roku 50. urodzin. Licznik roku = otwarcie roku
  (`sick_pay_days`: Enova i świadectwa pracy od poprzednich pracodawców) +
  zatwierdzone listy NEXUSA tego roku. Dni ponad limit = zasiłek z ZUS: 0 zł na
  liście, problem `z3_needed`. Przy `benefit_payer = 1` w parametrach (firma
  ponad 20 ubezpieczonych na 30.11) takie dni blokują listę (`benefit_payer_manual`)
  — zasiłków NEXUS nie liczy, wtedy kwota Płac.
- Okres wyczekiwania (art. 4): 30 dni nieprzerwanego ubezpieczenia od
  `sickness_insured_since` z danych osoby (puste = zatrudnienie). Zwolnienie:
  osoba (`waiting_period_exempt`: absolwent, 10 lat ubezpieczenia) albo L4
  (wypadek w drodze). Dni w wyczekiwaniu: bez chorobowego, pensja metodą godzinową.
- Podstawa (art. 36–38, 43, 45): średnia z 12 pełnych miesięcy kalendarzowych
  przed miesiącem początku L4 (tylko u tego pracodawcy, pełne miesiące od
  zatrudnienia), po odjęciu składek pracownika (suma stawek z parametrów,
  13,71%). Miesiąc z mniej niż połową wymiaru wypada, chyba że wszystkie są takie;
  niepełny miesiąc uzupełnia się — stałe do kwoty za pełny miesiąc, zmienne
  proporcjonalnie do godzin. Bez pełnego miesiąca — pensja (art. 37). Nie mniej
  niż płaca minimalna × etat po składkach (art. 45). Przerwa krótsza niż 3 miesiące
  od poprzedniego L4 — ta sama podstawa (art. 43). Płace mogą wpisać podstawę
  same (składnik `sick_base`, np. zmiana etatu w okresie podstawy — art. 40).
- Stawka dzienna = podstawa × procent / 30, do grosza; kwota = stawka × dni.
- Chorobowe jest bez składek społecznych, FP, FGŚP i PPK, ale ze zdrowotną i PIT
  (`Title.social_exempt` w silniku K7a).

## Urlopowe i ekwiwalent (rozporządzenie MPiPS z 08.01.1997)

- Urlopowe za zmienne (§ 8–9): zmienne z 3 miesięcy przed miesiącem początku
  urlopu / godziny faktycznie przepracowane w nich × 8 h × etat × dni urlopu.
  Zmienne to składnik Płac `variable` (nadgodziny, dodatki), nie premie.
- Ekwiwalent (art. 171, § 14–19), gdy `last_working_day` wypada w miesiącu:
  (pensja + średnia zmiennych z 3 miesięcy) / (współczynnik × etat) za dzień,
  / 8 za godzinę, × 8 h × dni. Współczynnik w parametrach (`leave_coefficient`,
  2026: 251 dni / 12 = 20,92 — `salary.leave_coefficient(rok)` liczy go z kalendarza).
  Dni: pula roku z modułu urlopów proporcjonalnie do miesięcy pracy w roku
  odejścia (art. 155¹, miesiąc i dzień w górę) — dzielona przez miesiące, które
  pula pokrywa (od startu w tym roku do grudnia), bo przy starcie w trakcie roku
  Kadry wpisują ją już proporcjonalnie; + zaległy − wykorzystany przed NEXUSEM −
  płatne dni z modułu urlopów; wykorzystane ponad wymiar = 0 i uwaga (nie potrąca się). Płace mogą
  wpisać dni same (`equivalent_days`).

## Parametry K7b

`sick_pay_rate` 80, `sick_pay_days_limit` 33, `sick_pay_days_limit_senior` 14,
`sick_pay_senior_age` 50, `waiting_period_days` 30, `benefit_payer` 0,
`leave_coefficient` 20,92. Wersje zapisane przed K7b nie mają tych kluczy —
`params.parse` bierze `LATER_DEFAULTS`; zasiew 0704 w SQL zostaje bez nich.

## Dekret listy NEXUSA do księgi (LP)

- „LP do księgi” na zatwierdzonej liście: dokument LP w buforze, źródło
  `payroll_list_nexus` / `RRRR-MM:<numer listy>`, ten sam dekret co import
  z Enovy (K3c, `ledger/payroll_lists.decree`), wrażliwość `payroll` (D2), data
  operacji = koniec miesiąca pracy, data dokumentu = dzień wypłaty. Ponowny dekret
  przebudowuje szkic; zatwierdzony LP poprawia się stornem (409).
- **Jeden miesiąc = jedno źródło LP:** LP z NEXUSA odmawia przy żywym LP z Enovy
  za ten miesiąc, import z Enovy odmawia przy LP z NEXUSA (409). W okresie
  równoległym zostaje LP z Enovy; po przełączeniu storno Enovy i LP z NEXUSA.
- Anulowanie listy usuwa szkic LP; przy zatwierdzonym LP — 409 (najpierw storno).

## Porównanie z Enovą — bloker przełączenia

- „Porównaj z Enovą” przy liście: plik listy z Enovy (ten sam format co do LP
  w K3c) → różnice osoba po osobie i kwota po kwocie w groszach (brutto, składki
  pracownika, zdrowotna, PIT, PPK, do wypłaty; pracodawcy, gdy plik ma kolumny).
  Osoby po imieniu i nazwisku jako zbiór słów; kilka pozycji osoby w NEXUSIE
  (UoP + zlecenie) sumuje się. „Zgodne do grosza” tylko bez nieczytelnych
  wierszy pliku i z kolumnami brutto, składek pracownika, zdrowotnej, PIT i „Do
  wypłaty” — inaczej problem pliku. Plik nie jest zapisywany; ślad
  `payroll_enova_compared` ma same liczby osób.
- **Bloker wyłączenia Enovy:** Rozliczenia muszą dać eksporty list płac z Enovy
  za 2–3 kolejne miesiące (i otwarcie roku z dniami chorobowego) i porównanie
  ma wyjść „zgodne do grosza” na każdej osobie. Bez tego Enova zostaje.
- Przed pierwszą listą UoP w NEXUSIE: pensje w „Pensje i nieobecności”, import
  12 miesięcy historii, `sick_pay_days` w otwarciu roku, `sickness_insured_since`
  u osób zatrudnionych krócej niż 30 dni po innym tytule, e-ZLA w module urlopów.
