# „Kto już to robił” — wyszukiwanie po celu projektu i obowiązkach (09.11.2026)
<!-- indeks: osobny widok, nie kolejność „Dopasowania”; cytat z CV albo brak poziomu; 10 wyszukiwań dziennie; wejście z menu „Szukaj” rekrutacji i z zakładki w „Z requestu” -->

Decyzja Artura z 09.11.2026 (raport z pomiarem i makietami:
https://claude.ai/artifact/VRRjDtFCXhr5H9UX6uHk1z). Rekruter albo Head wie, co
osoba ma ZROBIĆ (migracja do AWS, postawienie Jiry), ale nie zna technologii
krytycznych. Wyszukiwanie po słowach i wektor całego CV nie widzą, że ktoś robił
coś takiego, gdy CV nazywa to inaczej: na kopii produkcji „AWS” ma 10 851 osób,
a o migracji do chmury pisze wprost 1 916; opis stanowiska po odczycie CV ma
średnio 159 znaków przy 4 319 znakach całego CV.

## Jak działa

1. **Rozbicie celu** (model z rejestru, klucz `duty_search_plan`): 3–6 zdolności
   z wagą 1–3, sygnały pośrednie, „nie liczymy”, wzorce do tekstu CV i trzy
   przykładowe akapity CV osoby, która to zrobiła. Rekruter może poprawić cel.
2. **Szeroka sieć:** wektor celu, wektory przykładowych akapitów (Qdrant
   `nexus_candidates`), wzorce w `raw_cv_text`, połączone RRF, plus dzisiejszy
   kanoniczny ranking (top 50), żeby nikogo nie zgubić. Te same kontrole
   dopuszczalności co „Z requestu” (blacklista klienta, NDA, weto).
3. **Ocena** (klucz `duty_search_judge`, to samo zadanie „znajdź i zacytuj” co
   „Oceń z AI”): ok. 100 CV, dla każdej osoby poziom `zrobil_to` /
   `bardzo_blisko` / `ma_klocki` / `brak`, pewność, zdolności tak / częściowo /
   brak, 1–3 cytaty z wnioskiem, luka i pytanie na rozmowę. Sędzia ocenia RDZEŃ
   celu; brak skali i szczegółów idzie do luki, nie obniża poziomu (bez tego
   osoba z „plan and execute migration on-prem to AWS” dostawała „ma klocki”).
4. **Cytat albo brak poziomu.** Cytat musi stać w CV dosłownie albo w ≥ 80%
   trójek słów (cytat ≥ 6 słów), bo odczyt PDF wstawia daty w środek zdania
   („optimize/ 01-2021 – Present improve JIRA…”), a model skleja zdanie.
   Ścisłe porównanie odrzucało 12% prawdziwych cytatów.

## Reguły, które łatwo cofnąć

- **Osobny widok, nie kolejność „Dopasowania”.** Ocena celu nie wchodzi do
  `canonical_fit` ani do sortowania listy, Tablicy i propozycji. Pomiar
  09.11: w rekrutacjach 4421 i 349020 przestawienie kolejności po ocenie celu
  gubiło część osób wysłanych do klienta (klient często bierze „ma klocki”).
- **„Ma klocki” nie znika.** To ludzie z umiejętnościami bez takiego projektu
  w CV; 9 z 12 wysłanych do 349020 miało ten poziom.
- **Kolejność w widoku:** najpierw „Robił to” i „Bardzo blisko” (z cytatem),
  potem reszta; w grupie RRF z kanonicznego rankingu i puli celu. Karta pokazuje
  dzisiejsze „Dop.” obok poziomu i plakietkę „znalezione po celu” dla osób
  spoza kanonicznego top 50.
- **Wejścia:** pozycja „Kto już to robił” w menu „Szukaj ▾” rekrutacji (obowiązki
  z Championa, `champion_profile.project.responsibilities`) i zakładka „Cel
  projektu” w oknie „Z requestu” na liście Kandydatów. Nie osobny przycisk
  w nagłówku listy: przy 1280 px spychał „Moje CV / Importuj / Dodaj kandydata”
  do drugiego rzędu.
- **Zapora: 10 wyszukiwań dziennie na osobę** (kalendarz firmy,
  `DUTY_SEARCH_DAILY_LIMIT`). Otwarcie zapisanego wyniku nie zużywa. To ochrona
  przed przeczesywaniem bazy hurtem, nie budżet AI.
- **Awaria AI = komunikat o awarii**, nigdy pusta lista ani „nikt nie robił”.
- **Nic nie dodaje się samo.** „Dodaj do Nowych” klika rekruter.

## Odłożone (świadomie)

- Nocne liczenie dla rekrutacji bez umiejętności krytycznych (09.11: 93 ze 185
  otwartych) i sekcja „Robił to” w „Propozycjach z bazy”.
- Indeks fragmentów CV (`cv_passages.py`, `CV_PASSAGES_ENABLED`) jako kolekcja-
  cień z pomiarem puli. Przy 4421 do 60 ocenianych trafiło tylko 2 z 7 wysłanych:
  wąskim gardłem jest wyszukanie, nie ocena.
- Pomiar na ok. 60 zamkniętych rekrutacjach (wysłani jako prawda) przed każdą
  zmianą promptu albo modelu sędziego.
