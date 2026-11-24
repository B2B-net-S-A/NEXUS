# Rabat od obrotu rocznego klienta: rabat % na każdym wierszu, wyższa stawka od nadwyżki (16.11.2026)

Zgłoszenie Artura 16.11.2026: faktury Nordei nie uwzględniają rabatu 2,5%, a po przekroczeniu progu
obrotu stawka rośnie do 3%. Umowa ramowa (Appendix 6, aneks od 01.03.2026) liczy rabat od rocznego
obrotu za usługi (1.01–31.12) z progiem w EUR. Kwot, progów i stawek nie ma w repo, bo repo jest
publiczne. Wpisują je Finanse w ustawieniach.

## Decyzje Artura (16.11.2026)

Umowa przewiduje roczną notę do 31.01. Artur ustalił inną praktykę i ona obowiązuje. Pierwsza odpowiedź
z tego dnia („korekta roczna”, „3% od całego obrotu”) została zastąpiona drugą, opisaną niżej.

- **Rabat to procent na każdym wierszu usługi, tak jak Nordea dostaje go z eBI24.** Wiersz ma cenę
  przed rabatem, rabat % i wartość po rabacie. Przykład: 157,00 − 2,5% = 153,08, a 80 × 153,08 =
  12 246,40. W FA(3): `P_9A` to cena przed rabatem, `P_10` to kwota opustu na wierszu, `P_11` to wartość
  po rabacie. PDF pokazuje rabat i cenę po rabacie w kolumnie ceny.
  Pierwsza wersja z PR #3498 dawała osobną ujemną pozycję. Zastąpiło ją ustalenie Artura z 16.11
  na przykładzie faktury z eBI24.
- **Obrót do progu liczymy przed rabatem** (ilość × cena), a nie po nim (decyzja Artura 16.11).
- **Stawka pochodzi z obrotu sprzed miesiąca faktury.** Faktury za miesiąc M mają stawkę progu, w którym
  jest narastający obrót roku do końca miesiąca M−1. Faktury za miesiąc, w którym obrót przekroczył
  próg, idą jeszcze po niższej stawce. Wyższa stawka obowiązuje od następnego miesiąca.
- **Wyższa stawka dotyczy tylko nadwyżki ponad próg**, nie całego obrotu.
- **Za miesiąc przekroczenia trzeba wystawić korektę.** Wynosi ona różnicę stawek (np. 0,5%) od części
  obrotu tego miesiąca ponad próg. NEXUS pokazuje jej kwotę na karcie faktury. Do KSeF wysyłamy ją
  tylko po „tak” Artura.
- **Próg w EUR liczymy po kursie NBP z każdej faktury.** Bierzemy średni kurs z ostatniej tabeli przed
  datą sprzedaży. Gdy kursu brak, faktura wypada z obrotu progu i karta ostrzega. Kursu 1:1 nie
  stosujemy nigdy.
- **Podróże i faktury nieusługowe nie wchodzą ani do obrotu, ani do bazy rabatu.**

## Jak to działa w kodzie

- Warunki zapisane są w `app_settings['client_invoice_issue'].clients[<id>].rebate`. Finanse wpisują je
  w Ustawieniach wystawiania, w sekcji „Rabat roczny od obrotu” przy kliencie:
  - waluta progu;
  - okresy „od roku” z progami (górna granica włącznie, ostatni próg bez granicy, stawka w %);
  - słowa wyłączające: pozycja z takim słowem w nazwie wypada z obrotu i z bazy rabatu.

  Zapis ze złymi warunkami kończy się odmową z komunikatem. Złe dane w bazie odpadają przy odczycie
  z wpisem w logu.
- Obrót to faktury sprzedaży z KSeF (`client_sales_invoices`) za miesiące roku. Miesiąc wyznacza okres
  usługi, a gdy go brak, data wystawienia. Liczy się netto faktury plus opust z każdego wiersza
  (ilość × cena − netto), bez pozycji wyłączonych (`rebate.service_base`). Korekty wchodzą jako różnica
  stanów. W KSeF od 4.08.2026 rabat 2,5% na wierszach ma 1 114 z 1 128 faktur Nordei. Pozostałe 14 jest
  poprawnych bez rabatu (sprawdzone z archiwum eBI24, decyzja Artura 16.11.2026: bez korekt):
  - 9 to w całości refaktury podróży (hotel, samolot, PKP, diety, transport, opłaty); wiersze „szt.” to
    bilety i opłaty z tych faktur;
  - 5 faktur w EUR to pentesty z osobnej umowy (rabat jest tylko w głównej umowie ramowej); w eBI24
    pentesty też zawsze szły bez rabatu.

  Faktury sprzed KSeF dochodzą do obrotu z archiwum eBI24 (sekcja „Obrót sprzed KSeF” niżej).
- Słowa wyłączające muszą pasować do nazw pozycji klienta. U Nordei ogólne „podróż” niczego nie łapie.
  Finanse wpisują nazwy z faktur (Hotel, PKP, Airplane, Transaction fee, Diems, Transport, Security Test),
  inaczej podróże i pentesty wejdą do obrotu progu.
- `issue.apply_rebate` wpisuje `discount_pct` na wiersze usług w szkicach z „Wystaw za miesiąc”.
  Finanse mogą go zmienić w polu „Rabat %” wiersza. Edycja nie nadpisuje go automatycznie.
- Karta faktury (`rebate` w `GET /api/finance/issued-invoices/{id}`, ramka „Rabat od obrotu”) pokazuje:
  - stawkę;
  - obrót do końca poprzedniego miesiąca;
  - obrót z tą fakturą;
  - licznik do progu;
  - sumę rabatu z wierszy;
  - korekty za miesiące przekroczenia.

  Gdy klient ma rabat, a żaden wiersz go nie ma, karta pokazuje ostrzeżenie.
- Porównanie faktury z zamówieniem („Do faktury”, `ledger.check`, dopasowanie po kwocie) idzie po
  `Chain.order_net`, czyli netto przed rabatem % na wierszach (`rebate.pre_discount`). Zamówienie ma cenę
  przed rabatem, więc bez tego każdy wiersz klienta z rabatem pokazywałby różnicę 2,5%. Do zapłaty
  i sumy liczą się z rabatem. U pozostałych klientów netto wiersza równa się ilości × cenie (576 wierszy,
  22 klientów, odczyt 16.11), więc ich to nie zmienia.
- Kod: `services/client_invoicing/rebate.py`, `issue.apply_rebate`, `issue_settings.client_rebate`.

## Szkic korekty za miesiąc przekroczenia (16.11.2026)

Przy korekcie na karcie faktury jest przycisk „Szkic korekty rabatu za <miesiąc>”
(`GET /api/finance/issued-invoices/rebate-correction`, XML: `…/rebate-correction/xml`,
kod: `services/client_invoicing/rebate_correction.py`). Sam podgląd niczego nie zapisuje.
Zapis to „Wystaw korektę” (sekcja niżej). Do KSeF korekta idzie dopiero po „tak” Artura.

- Kwota to `YearRebate.corrections` z karty, czyli różnica stawek × nadwyżka w walucie progu.
  Na walutę faktur przelicza ją ten sam udział, którego używa karta.
- Forma w FA(3) to jedna korekta zbiorcza za miesiąc (art. 106j ust. 3):
  - `RodzajFaktury` = `KOR`;
  - `TypKorekty` = 2, bo to obniżka ceny po sprzedaży i skutek liczy się w dacie korekty;
  - `DaneFaKorygowanej` dla każdej faktury pierwotnej z miesiąca w tej walucie, która ma obrót usług.
    Wpisy mają numer KSeF, więc faktury z eBI24 też się liczą. Schemat pozwala na 50 000 wpisów;
  - `OkresFaKorygowanej` = miesiąc;
  - `FaWiersz` po jednym na stawkę VAT z nazwą usług objętych opustem, bo rabat nie obejmuje podróży.
    Kwota dzieli się na stawki według obrotu usług przed rabatem.
- Waluta inna niż PLN dostaje osobny szkic. Kurs NBP bierzemy z dnia roboczego przed końcem miesiąca
  i księgowa go sprawdza.
- Odmowa: klient bez warunków, rok poza warunkami, miesiąc bez przekroczenia, waluta bez faktur.
  XML nie powstaje przy stawce VAT spoza FA(3) i przy braku danych sprzedawcy.
- Testy: `tests/test_client_invoice_rebate_correction.py` sprawdzają XML schematem
  z `tests/data/fa3_schema/` (kopia schematu MF z lokalnymi importami).

## Wystawienie korekty (22.11.2026)

W oknie szkicu jest przycisk „Wystaw korektę” (`POST /api/finance/issued-invoices/rebate-correction`,
`rebate_correction.create`). Zapisuje podgląd jako szkic `ClientIssuedInvoice` typu `KOR` i otwiera
jego kartę.

- Faktury korygowane, okres (`OkresFaKorygowanej`) i `TypKorekty` leżą w kolumnie JSONB
  `collective_correction` (migracja 0749, lustro przez `hr_schema_bundle`). `corrects_id` jest pusty.
  CHECK `ck_client_issued_invoices_correction`: `KOR` ma albo `corrects_id`, albo `collective_correction`.
- Jedna korekta na klienta, miesiąc i walutę. Pilnuje tego unikalny indeks
  `uq_client_issued_invoices_collective_month`, a wycofana się nie liczy. Druga próba kończy się
  odmową 409 z numerem istniejącej. Okno podglądu i ramka rabatu na karcie pokazują wtedy odnośnik
  do istniejącej korekty.
- Numer z serii `KOR` (`KORUE` dla nabywcy z UE) korekta dostaje dopiero przy wysyłce. Wysyłka
  działa jak dla każdej faktury: przyciskiem Finansów na karcie. Na produkcji wysyłamy tylko po
  „tak” Artura w czacie. PDF wymienia faktury korygowane.
- Kwota i lista faktur zostają zamrożone w chwili wystawienia. Jeśli faktura za ten miesiąc dojdzie
  później, trzeba usunąć szkic i wystawić go od nowa.
- Przyjęta korekta trafia do `client_sales_invoices` bez `corrects_invoice_id`, bo dotyczy całego
  miesiąca, a nie pierwszej faktury z listy. Inaczej „Do faktury” pokazałby różnicę na tamtej
  fakturze. Pozycja zaczyna się od `rebate.REBATE_LINE_PREFIX` („Opust (rabat od obrotu)”), więc
  `service_base` pomija ją w obrocie do progu: opust jest rabatem, nie obrotem.
  Dlatego edycja szkicu nie może zmienić tego początku nazwy: zapis kończy się wtedy odmową 422.
- Inny błąd zapisu niż drugi szkic za ten sam miesiąc (np. stary CHECK, gdy krok lustra
  pominął `lock_timeout`) trafia do logu jako 500. Nie udaje „korekta już powstała”.

## Warunki Nordei w ustawieniach (24.11.2026)

Warunki są na produkcji od 24.11.2026, wpisane po „tak” Artura w Ustawieniach wystawiania przy kliencie
Nordei. Źródło to umowa ramowa w module umów klienta. Liczb nie ma w repo, są tylko w ustawieniach.

- Dwa okresy „od roku”:
  - od 2024 według Appendix 6 z 2024 r.: jedna stawka, bez progu;
  - od 2026 według Appendix 6 od 01.03.2026 (sekcja „Spend discount”): próg w EUR i wyższa stawka
    od nadwyżki. Amendment 2 opisuje to jako zmianę sekcji „Spend discount”.
- Słowa wyłączające pochodzą z nazw pozycji faktur Nordei z 2026 r. Oprócz listy wyżej są tam też:
  - „trasaction fee”, bo literówka występuje w nazwach;
  - „taxi”;
  - „it services_”, bo dwa pentesty z osobnej umowy nie mają w nazwie „Security Test”.

  Na fakturach z 2026 r. słowa nie łapią żadnego wiersza z rabatem i łapią wszystkie wiersze bez rabatu
  poza trzema wierszami podróży, które nie mają w nazwie rodzaju pozycji.
- **Do obrotu progu liczą się tylko faktury przy kliencie Nordei w NEXUS-ie, czyli dla nabywcy Nordea
  Bank Abp** (decyzja Artura 24.11.2026). Nie liczą się faktury dla oddziału w Polsce ani dla spółek
  Nordei (Rahoitus, Liv), choć mają rabat ramowy na wierszach. Nie przypinaj ich do obrotu bez nowej
  decyzji.
- Sprawdzenie 24.11.2026:
  - na kopii produkcji szkic NEXUS-a za IX–X równa się co do grosza fakturom Finansów z eBI24;
  - na produkcji szkic z „Wystaw za miesiąc” dostał rabat % na wierszu i ramkę „Rabat od obrotu”.
    Szkic został potem usunięty.

## Obrót sprzed KSeF z archiwum eBI24 (24.11.2026)

Faktury Nordei z KSeF (`client_sales_invoices`) zaczynają się od okresu IV 2026. Styczeń–marzec jest
tylko w archiwum eBI24 (`finance_archive_documents`, pozycje w plikach JSON). Bez tych miesięcy licznik
do progu był zaniżony, wyższa stawka nie wchodziła sama, a karta nie pokazywała korekty za miesiąc
przekroczenia. Od 24.11.2026 `rebate.year_rebate` dolicza je z archiwum
(`client_invoicing/rebate_archive.py`). Finanse niczego nie wpisują i nie ma migracji.

- Do obrotu idzie dokument z archiwum, który spełnia wszystkie warunki:
  - jest fakturą sprzedaży wystawioną w eBI24 (`INCOME_INVOICE` albo `EUROPEAN_INCOME_INVOICE`, plik
    JSON). PDF wgrany do eBI24 nie ma pozycji, a proforma, zamówienie i nota nie są obrotem;
  - nie ma numeru KSeF, bo dokument z numerem jest już w `client_sales_invoices`. Odpada też dokument
    bez numeru KSeF, którego numer faktury klient ma w KSeF, bo eksport archiwum bywa starszy niż
    wysyłka. Ten sam numer w archiwum drugi raz to duplikat faktury z eBI24 (na kopii z 24.11.2026:
    15 takich par z lat 2023–2025), więc liczy się raz;
  - ma nabywcę, którego numer prowadzi do klienta tak samo jak przy fakturach z KSeF
    (`clients.nip_registry`). Oddział i spółki z grupy mają inne numery, więc się nie liczą (decyzja
    Artura 24.11.2026);
  - jest za miesiąc roku według daty sprzedaży (`transactionDate`), a bez niej według daty wystawienia.
- Obrót z pliku liczy ten sam `rebate.service_base` co przy KSeF. Cena jednostkowa w eBI24 jest przed
  rabatem, a netto pozycji po nim. Korekta to stan po korekcie minus stan przed, wzięty z treści faktury
  korygowanej; bez tej treści zostaje sama różnica netto. Kurs NBP jest ten sam co przy KSeF: z ostatniej
  tabeli przed datą sprzedaży.
- Pliki leżą na dysku w `UPLOADS_DIR/ebi24_archive/<rok>/`. Proces czyta je raz, w wątku, i trzyma wynik
  w pamięci (klucz: ścieżka i SHA-256 z bazy), bo plik archiwum się nie zmienia. Pierwsza karta po
  wdrożeniu czyta kilkaset plików, następne już nie.
- Karta faktury pokazuje, ile faktur z archiwum weszło do obrotu. Dokument bez czytelnego pliku nie
  wchodzi do obrotu, a karta pokazuje na czerwono, ile takich jest, bo obrót jest wtedy zaniżony.
- Raport „Rabat od obrotu rocznego” (`client_reports/generators/annual_spend.py`) dolicza te same faktury
  tak samo jak `year_rebate` i pokazuje je na liście faktur. Pyta archiwum o zakres dat sprzedaży
  (`rebate_archive.pre_ksef_between`), a nie o rok: miesiąc wchodzi, gdy jego pierwszy dzień leży w okresie,
  jak przy fakturach z KSeF. Dziś raport ma tylko rytm roczny, ale okres może kiedyś objąć dwa lata (rok
  umowy). Ostrzeżenie o niepełnym okresie liczy od najwcześniejszej faktury z KSeF albo z archiwum.
  Nieczytelne pliki trafiają do kontroli raportu. Test: `tests/test_client_reports_annual_spend_db.py`.
- Sprawdzenie na kopii produkcji 24.11.2026: obrót I–III z kodu równa się co do grosza osobnemu
  przeliczeniu plików eBI24. Miesiąc przekroczenia progu, stawka faktur za następny miesiąc i kwota
  korekty wychodzą tak samo jak w tym przeliczeniu.
- Testy: `tests/test_client_invoice_rebate_archive_db.py` (z bazą) i parser pliku w
  `tests/test_client_invoice_rebate.py`.

## Czego jeszcze nie ma

- Korekty za miesiąc sprzed KSeF. Szkic korekty bierze faktury korygowane i stawki VAT z faktur z KSeF.
  Gdy próg pada w miesiącu, który jest tylko w archiwum eBI24, szkic pokaże kwotę, ale bez XML-a
  („Faktury z miesiąca nie mają pozycji usług ze stawką VAT”). U Nordei w 2026 r. próg pada później,
  a okres od 2024 ma jedną stawkę bez progu.
