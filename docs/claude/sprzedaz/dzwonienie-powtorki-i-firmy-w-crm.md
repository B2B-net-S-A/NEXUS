# Dzwonienie: powtórki z kolejnych list i firmy już w CRM — decyzje Artura 17.11.2026
<!-- indeks: Już dzwoniono already_called, bramka importu po numerze adresie osobie, _same_entry numer przed nazwiskiem, Ten numer czeka już na liście, W tej firmie dzwoniono już, kolejka pomija powtórki queue_conditions, firma już w CRM szansa po rekordzie, karta earlier_calls crm_opportunity, Pobierz plik z oznaczeniami, calling_repeats.py, calling_repeats_report bieg na sucho -->

Powód: osoby dzwoniące zgłosiły 17.11.2026, że przy wgrywaniu listy wracają firmy, do
których już dzwoniły. Na kopii produkcji z 16.11 były dwa mechanizmy:

- **Powtórki z importu.** Lista z 13.11 (541 wierszy) dała 380 „Nowych” rekordów pod
  numerami, pod które dzwoniono 11.11 (77 „Nie zainteresowany”, 23 „Zły numer”, 9
  „Umówione spotkanie”). Bramka „Już w kampanii” porównywała imię i nazwisko, a lista
  miała samo nazwisko („Nowacka” zamiast „Ewa Nowacka”). NIP-u nie miało 1681 z 1720
  kart z rekordami, więc bramka NIP też nie łapała.
- **Firma już w CRM.** Rekord z Excela bez wyniku, a ofertę zapisano jako szansę na
  etapie Lead z formularza szansy (nie wynikiem na karcie). Kolejka pokazywała firmę dwa
  razy: przez szansę i przez rekord „Nowy”. 30 takich rekordów (szanse z lejka Sprzedaż).

Makiety i decyzje: https://claude.ai/artifact/MJQSHLtj6WJNywtMePX68R (prywatny artefakt).
Artur wybrał wszystkie warianty, dopasowanie „numer, adres, osoba” i bieg na sucho przed
jakimkolwiek zapisem na produkcji.

Kod: `backend/app/services/sales/calling_repeats.py`, bramka w `calling_import.py`,
warunki kolejki w `calling._own_campaign_records`, pola karty w `calling._card`. Bez migracji.

## Import: bramka „Już dzwoniono” (`already_called`)

- Wiersz, którego **numer, adres e-mail albo osoba z kontaktów** ma już wynik rozmowy
  (stan inny niż „Nowy”) w dowolnym rekordzie, w każdej kampanii, u każdej osoby, także
  zamkniętym, dostaje „Już dzwoniono” z datą, osobą, wynikiem i nazwiskiem z poprzedniego
  rekordu. Nie trafia do kolejki. Stary rekord wraca sam w swoim dniu, więc opcji „dodaj
  mimo to” nie ma.
- Numer łączy się z rekordem także przy innej karcie firmy (inna nazwa w pliku).
- Bramka stoi po sprzeciwie, kliencie NEXUSA i powtórce w pliku, przed „Już w kampanii”.
  Te same bramki ma Bot Listy i przeniesienie Excela (wspólne `plan_import`).
- **Ten sam wpis to najpierw ten sam numer albo adres**, dopiero bez nich ta sama osoba
  (`_same_entry`). Nie wracaj do porównania samych nazwisk.
- Numer, który czeka na liście jako „Nowy” w innej kampanii (u tej samej osoby albo pod
  inną kartą), dostaje „Już w kampanii” z „Ten numer czeka już na liście dzwonienia”.
- **Nowa osoba w firmie, gdzie już dzwoniono, przechodzi** („Połączono z kartą”)
  z dopiskiem „W tej firmie dzwoniono już: …”. Nie blokuj całej firmy: nowy decydent
  bywa jedyną drogą po „Nie odebrał” poprzedniej osoby.
- Okno podglądu: licznik w podsumowaniu, uwaga nad tabelą z filtrem „Pokaż je”
  i „Pobierz plik z oznaczeniami” (CSV ze średnikiem i BOM, kolumna „W NEXUSIE”,
  liczony w przeglądarce z podglądu). Kolumny tabeli mają stałe szerokości, bo przy
  1280 px „Co się stanie” było ucięte.

## Kolejka (`calling_repeats.queue_conditions`)

- Rekord kampanii firmy, która ma **otwartą szansę założoną po rekordzie** (po jego
  ostatnim wyniku albo imporcie), nie wchodzi do kolejki ani do liczników: firmę
  prowadzi się przez szansę. Szansa sprzed rekordu niczego nie zdejmuje.
- **„Nowy” rekord pod numerem, adresem albo osobą z wynikiem w innym rekordzie** nie
  wchodzi do kolejki. Rekord z wynikiem wraca sam w swoim dniu.
- **„Zły numer” blokuje sam numer**, nie osobę ani adres: ta osoba wraca z kolejnej listy
  z nowym numerem (reguła „nowy numer przychodzi z importu”). Tak samo w imporcie.
- Liczy się tylko **szansa z lejka Sprzedaż** (`DEFAULT_PIPELINE_KEY`): szansa z lejka
  botów (fabryki IT, przetargi) nie zdejmuje firmy z kolejki.
- Warunki to zbiory liczone raz na zapytanie (`NOT IN`), nie zależny `EXISTS` w `OR`:
  ta wersja liczyła się osobno dla każdego „Nowego” rekordu, ok. 13 s na kolejkę.
- Rekordy nie znikają z bazy. Od 23.11.2026 Tabela też ukrywa powtórki (przełącznik
  „Powtórki”): `dzwonienie-duplikaty-instrukcja.md`. Bieg na sucho:
  `python -m scripts.calling_repeats_report` (same liczby, `--ids` dokłada id).
  Na stagingu 17.11: 388 powtórek i 30 rekordów firm w CRM; zapytanie kolejki 0,06 s. 23.11.2026 Artur wybrał
  ukrycie po stronie serwera zamiast kasowania.

## Karta rozmowy

- `earlier_calls` (do 3): „Pod ten numer już dzwoniono” z datą, osobą, wynikiem,
  nazwiskiem i kartą firmy.
- `crm_opportunity`: „Ta firma jest już w CRM” z szansą, etapem, datą i osobą oraz
  „Otwórz szansę”. Tylko dla rekordu kampanii.
- Obie uwagi stoją nad numerem, bo „Co już było” przy 1280 × 720 jest pod krawędzią.

## Testy

`backend/tests/test_sales_calling_repeats.py`; front `sales-calling.test.tsx`
(„Już dzwoniono”, plik z oznaczeniami, uwagi na karcie). Numery w testach dzwonienia są
unikalne na test (`_record`, `_phone()`, `_segment`): ten sam numer w dwóch testach to
dla kolejki i importu powtórka, więc stały numer psuje cudze testy.
