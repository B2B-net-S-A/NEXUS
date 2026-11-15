# Księga NEXUSA K4c (15.11.2026): rachunki walutowe, różnice kursowe, wycena walut

Etap K4 planu „Księgowość w NEXUSIE” (https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar),
część trzecia. Wyciągi: `ksiega-nexusa-k4-bank.md`, rozrachunki:
`ksiega-nexusa-k4b-rozrachunki.md`. Migracja `0707_ledger_fx`
(`ledger_fx_schema.py`, lustro przez `hr_schema_bundle`), kod w
`app/services/ledger/bank.py` (import, WB) i `settlements.py` (rozliczenie
w walucie, PK różnicy kursowej). Wycena na koniec miesiąca (K4c-2): `valuation.py`,
sekcja niżej.

## Co jest

- **Rachunek firmy ma walutę** (PLN, EUR, USD — jak E8 i R9). Plik wyciągu musi
  mieć jedną walutę i tę samą co rachunek; inaczej 422.
- **Kurs operacji**: średni kurs NBP (tabela A) z ostatniego dnia roboczego
  przed dniem operacji (art. 30 ust. 2 pkt 2 ustawy o rachunkowości),
  dokładnie z tego dnia — jak w K2 i E2 (`posting.rate_day`). Brak kursu = 422
  „pobierz kursy”, nie cichy starszy kurs (luka w pobieraniu zmieniłaby PLN bez
  śladu). Kwota w PLN zaokrąglana połowa w górę (`posting.grosze`).
- `ledger_bank_lines.amount` jest w walucie wyciągu; `amount_pln`, `fx_rate`,
  `fx_date` dla operacji walutowych (wiersze sprzed K4c: `amount_pln = amount`).
- **WB z rachunku walutowego** to dokument w PLN z pozycjami walutowymi:
  kwota PLN, kwota w walucie i **kurs pozycji** (`ledger_lines.fx_rate` /
  `fx_date` — każda operacja ma swój dzień kursu). Eksport do Symfonii (K3b)
  bierze kurs pozycji, gdy jest, inaczej kurs dokumentu.
- **Rozliczenie pary w tej samej walucie obcej** (`ledger_settlements`:
  `currency`, `amount_cur`, `credit_amount`): kwota w walucie, a każda strona
  zdejmuje swój udział PLN = PLN pozostałe × rozliczana część waluty pozostałej
  (ostatnia część bierze całą resztę). Pozycje zamykają się w walucie i w PLN
  naraz.
- **Różnica kursowa zrealizowana** = udział Wn − udział Ma. PK w buforze
  (źródło `fx_difference` / id rozliczenia): nadwyżka po Wn (wpłata dała mniej
  PLN niż faktura, albo zapłata dostawcy więcej) = ujemna — Wn konto kosztów
  finansowych, Ma konto kontrahenta; nadwyżka po Ma = dodatnia — Wn konto
  kontrahenta, Ma konto przychodów finansowych. Po zatwierdzeniu PK saldo konta
  kontrahenta zgadza się z pozycjami. Pozycje PK różnicy **nie są**
  rozrachunkami.
- Konta różnic kursowych ustawia administrator w Ustawieniach (Bank). Puste
  konto albo zamknięty okres = para czeka: rozliczenie ręczne dostaje 422
  z powodem, automat pomija parę i liczy ją w `fx_waiting` (podgląd, toast,
  lista zamknięcia miesiąca: stan „problem”).
- **Faktura w walucie zapłacona w PLN** rozlicza się w PLN jak w K4b, a z
  pozycji walutowej schodzi proporcjonalna część waluty (bez różnicy
  kursowej — tę, jeśli jest, księguje się ręcznie). Dwóch różnych walut obcych
  (EUR z USD) się nie łączy (422).

## Zasady, których łatwo nie zauważyć

- **Odcisk dokumentu**: kursy pozycji wchodzą do odcisku tylko, gdy są — odciski
  dokumentów w PLN zostały te same co przed K4c (test
  `test_pln_document_fingerprint_is_the_same_as_before_line_rates`). Inaczej
  K2 pokazałby zatwierdzone FVS/FVZ jako zmienione źródła do storna.
- **Cofnięcie rozliczenia w walucie** usuwa szkic jego PK różnicy; zaksięgowana
  PK blokuje cofnięcie (409 — najpierw storno PK).
- **Storno faktury albo wpłaty** po zaksięgowaniu różnicy zostawia PK bez
  obowiązującego rozliczenia — karta konta pokazuje ją jako „rozliczenie już nie
  obowiązuje”, trzeba zrobić jej storno (saldo konta inaczej nie zgadza się
  z pozycjami).
- Saldo zerowe liczy się w PLN; grupa z dwiema walutami obcymi jest pomijana.
- Przelew między własnymi rachunkami (wymiana waluty, „kurs faktycznie
  zastosowany”) idzie przez konto ręczne (np. środki w drodze) — automat go nie
  rozpoznaje.

## Wycena na koniec miesiąca (K4c-2)

- Art. 30 ust. 1 UoR: na dzień bilansowy (31.12) obowiązkowo, w ciągu roku na
  koniec dowolnego miesiąca (zarządczo) — karta „Wycena walut” w Rozrachunkach
  dla miesiąca z nagłówka, przycisk dla listy „Księgowi”.
- **Kurs**: średni NBP z ostatniego dnia roboczego miesiąca
  (`posting.rate_day(koniec miesiąca + 1 dzień)`), **dokładnie z tego dnia**.
  Brak kursu = blokada z datą („pobierz kursy”, a przed ogłoszeniem — „jeszcze nie
  jest pobrany”); pozycje zostają na karcie bez wyceny. Starszy kurs nigdy nie
  wchodzi po cichu.
- **Rozrachunki**: otwarte pozycje walutowe kontrahentów na ten dzień, netto per
  konto i waluta (Wn +, Ma −).
- **Rachunki walutowe** z Ustawień: saldo w walucie i PLN z zatwierdzonych
  zapisów **bieżącego roku obrotowego** (BO + obroty do końca miesiąca — jak
  w obrotach i saldach), bez wyceny tego miesiąca (wszystkich wersji) i jej storna.
  Wyceny i odwrócenia innych miesięcy zostają w saldzie — znoszą się, bo pilnuje
  tego blokada kolejności niżej.
- **Rachunek pominięty z powodem** (lista „Poza wyceną — wyceń ręcznie”), gdy:
  - ma zapisy bez kwoty w walucie rachunku, które nie znoszą się do zera (BO
    z Symfonii jest tylko w PLN, ręczna PK nie ma pola waluty) — wycena
    odpisałaby saldo PLN bez waluty jako stratę;
  - poprzedni rok w księdze ma na nim saldo, a bieżący rok nie ma BO tego konta.
  BO następnego roku tworzone w NEXUSIE (K8) musi nieść kwotę w walucie dla
  rachunków walutowych, inaczej wycena go pominie.
- **D2**: pozycje płacowe i rachunek walutowy z choćby jednym zapisem płacowym
  w roku idą osobną PK płacową (`RRRR-MM-payroll`, `sensitivity='payroll'`),
  widoczną tylko z Płacami. Osoba bez Płac widzi `payroll_hidden` bez kwot, kursów
  i numerów dokumentów, a jej „Zaksięguj” robi tylko zwykłą PK.
- Korekta konta = wartość po kursie − kwota w księdze; dodatnia → Wn konto,
  Ma przychody finansowe; ujemna → Wn koszty finansowe, Ma konto (konta różnic
  kursowych z K4c-1, zbiorczo po jednej linii).
- PK wyceny na ostatni dzień miesiąca (`fx_valuation` / RRRR-MM) i odwrócenie
  1. dnia następnego miesiąca (`fx_valuation_reversal`). Brak następnego roku
  albo zamknięty okres = odwrócenie czeka (komunikat), wycena idzie.
- **Zatwierdzonej wyceny się nie podmienia.** Odwrócenie powstaje z zaksięgowanej
  PK, nie z dzisiejszego przeliczenia — dzięki temu czekające odwrócenie powstaje
  po otwarciu roku, nawet gdy w grudniu doszedł późny dokument. Różnica
  zatwierdzonej PK od przeliczenia to flaga `changed`: karta i lista zamknięcia
  („problem”) każą zrobić storno i wycenić ponownie. Szkic jak w K2: bez zmian /
  przebudowa; zatwierdzone odwrócenie, które nie pasuje do nowej wyceny = 409.
- **Kolejność**: wycena czeka, dopóki którakolwiek wcześniejsza zatwierdzona
  wycena (nie tylko poprzedni miesiąc) nie ma zatwierdzonego odwrócenia, które
  ją dokładnie odwraca (te same konta i kwoty), albo gdy zatwierdzone odwrócenie
  zostało bez wyceny — inaczej korekta weszłaby do salda drugi raz.
- Lista zamknięcia: „problem” przy zmienionej zatwierdzonej wycenie; w grudniu
  blokada (np. brak kursu), brak wyceny albo pominięty rachunek = „do zrobienia”;
  w innych miesiącach wycena jest opcjonalna. Pozycji listy nie ma, gdy nie ma
  pozycji w walucie, pominiętych rachunków ani części płacowej.
- Pozycje PK wyceny i odwrócenia nie są rozrachunkami (`settlements.NOT_ITEMS`):
  rozrachunki są w kursach historycznych, a saldo konta po wycenie różni się od
  nich o korektę wyceny do jej odwrócenia.

## Testy

`tests/test_ledger_settlement_rules.py` (udział PLN, warunki par EUR/EUR, EUR/PLN,
EUR/USD, blokady PK, waluta pliku, WB walutowy, odcisk PLN bez zmian), sekcja
K4c-1 w `tests/test_ledger_sources_db.py` (WB z rachunku EUR po kursie NBP,
automat z różnicą kursową, brak konta = czeka, cofnięcie szkicu, 409 po
zatwierdzeniu, saldo konta = 0; zła waluta rachunku, brak kursu, waluta spoza
listy), front: `SettlementsView.test.tsx`, `settlements-model.test.ts`,
`bank-model.test.ts`.
Wycena: `tests/test_ledger_valuation_rules.py` (pozycje netto, płacowe osobno,
pozycja bez kursu, odwrócenie odwraca wycenę, stany listy zamknięcia) i sekcja
K4c-2 w `tests/test_ledger_sources_db.py`: wycena należności i rachunku EUR
z odwróceniem, bez zmian / przebudowa / zatwierdzona zostaje z flagą, kwiecień
czeka na odwrócenie marca, 403; PK płacowa rachunku z wypłatą (D2); BO z Symfonii
bez EUR = rachunek pominięty; storno własnej wyceny poza saldem; nowy rok od BO
(bez BO = pominięty); maj czeka na marzec; czekające odwrócenie z zaksięgowanej
PK po otwarciu roku; dokładny kurs i grudzień bez kursu na liście zamknięcia.
